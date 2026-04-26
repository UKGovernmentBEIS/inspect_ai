"""Top-level deep agent assembly."""

from dataclasses import replace
from typing import Sequence

from inspect_ai.agent._agent import Agent, AgentState, agent
from inspect_ai.agent._react import react
from inspect_ai.agent._types import AgentAttempts, AgentPrompt, AgentSubmit
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._compaction import CompactionStrategy
from inspect_ai.model._model import Model
from inspect_ai.tool._tool import Tool, ToolSource
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._skill import Skill

from .general import general
from .plan import plan
from .prompt import build_system_prompt, expand_prompt_placeholders
from .research import research
from .subagent import Subagent
from .task_tool import task_tool


@agent
def deepagent(
    *,
    tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    subagents: list[Subagent] | None = None,
    todo_write: bool = True,
    memory: bool = True,
    web_search: bool | Tool = False,
    skills: list[Skill] | None = None,
    compaction: CompactionStrategy | None = None,
    submit: AgentSubmit | bool | None = None,
    attempts: int | AgentAttempts = 1,
    model: str | Model | None = None,
    instructions: str | None = None,
    prompt: str | None = None,
    max_depth: int = 1,
) -> Agent:
    """Deep agent with subagent delegation, memory, and planning.

    A batteries-included agent that bundles the patterns popularized by
    Claude Code and Codex CLI into a single
    entry point. Builds on `react()` with subagent delegation via a task
    tool, persistent memory, structured planning, and an opinionated
    system prompt.

    Args:
        tools: Additional tools beyond defaults. Flow to the top-level
            agent and to general() subagents.
        subagents: Subagent configurations. Defaults to
            [research(), plan(), general()].
        todo_write: Include the todo_write planning tool.
        memory: Include the memory tool. False disables memory for the
            top-level agent and all subagents.
        web_search: Include web_search tool for all agents. Pass True
            for default config, or a pre-configured web_search() tool
            instance for custom setup.
        skills: Skills available to the agent.
        compaction: Compaction strategy for context management.
        submit: Submit tool configuration.
        attempts: Number of submission attempts.
        model: Model to use.
        instructions: Additional instructions appended to the system
            prompt.
        prompt: Full replacement system prompt. Supports placeholders:
            {core_behavior}, {subagent_dispatch}, {memory_instructions},
            {instructions}. When provided, replaces the default system
            prompt entirely.
        max_depth: Maximum subagent recursion depth.
    """

    async def execute(state: AgentState) -> AgentState:
        # All setup runs per-sample inside execute() so there is no
        # shared mutable state across concurrent samples.
        resolved_subagents = (
            [_clone_subagent(sa) for sa in subagents]
            if subagents is not None
            else [research(), plan(), general()]
        )

        _apply_memory_kill_switch(resolved_subagents, memory)
        _apply_compaction(resolved_subagents, compaction)

        # Build shared tool instances once so they appear in both
        # top-level tools and general()'s inherited set
        # Subagents that inherit parent tools get web_search/skill
        # through parent_tools — skip them to avoid duplicates
        inherits_parent = {
            sa.name
            for sa in resolved_subagents
            if sa.name == "general" and sa.tools is None
        }

        ws_tool_instance = _resolve_web_search(web_search)
        if ws_tool_instance:
            _inject_extra_tool(
                resolved_subagents, ws_tool_instance, skip=inherits_parent
            )

        skill_tool_instance: Tool | None = None
        if skills:
            from inspect_ai.tool._tools._skill import skill as skill_tool

            skill_tool_instance = skill_tool(skills)

        # Parent tools = user tools + web_search + skill. Flow to general().
        parent_tools: list[Tool | ToolDef | ToolSource] = list(tools or [])
        if ws_tool_instance:
            parent_tools.append(ws_tool_instance)
        if skill_tool_instance:
            parent_tools.append(skill_tool_instance)

        _apply_parent_tools_to_general(resolved_subagents, parent_tools)

        def get_messages() -> list[ChatMessage]:
            return list(state.messages)

        task = task_tool(
            subagents=resolved_subagents,
            parent_tools=parent_tools,
            parent_model=model,
            depth=0,
            max_depth=max_depth,
            get_messages=get_messages,
        )

        # Top-level tools = parent tools + task + memory + todo_write
        all_tools: list[Tool | ToolDef | ToolSource] = list(parent_tools)
        all_tools.append(task)
        if memory:
            from inspect_ai.tool._tools._memory import memory as memory_tool

            all_tools.append(memory_tool())
        if todo_write:
            from inspect_ai.tool._tools._todo_write import (
                todo_write as todo_write_tool,
            )

            all_tools.append(todo_write_tool())

        if prompt is not None:
            system_prompt = expand_prompt_placeholders(
                prompt,
                subagents=resolved_subagents,
                memory=memory,
                todo_write=todo_write,
                instructions=instructions,
            )
        else:
            system_prompt = build_system_prompt(
                subagents=resolved_subagents,
                memory=memory,
                todo_write=todo_write,
                instructions=instructions,
            )

        agent_prompt = AgentPrompt(
            instructions=system_prompt,
            handoff_prompt=None,
            assistant_prompt=None,
        )

        inner = react(
            tools=all_tools,
            prompt=agent_prompt,
            model=model,
            submit=submit,
            attempts=attempts,
            compaction=compaction,
        )

        return await inner(state)

    return execute


def _resolve_web_search(web_search: Tool | bool) -> Tool | None:
    """Build web_search tool instance if configured."""
    if not web_search:
        return None
    if web_search is True:
        from inspect_ai.tool._tools._web_search import web_search as ws_factory

        return ws_factory()
    return web_search


def _inject_extra_tool(
    subagents: list[Subagent], tool: Tool, skip: set[str] | None = None
) -> None:
    """Add a tool to subagents' extra_tools.

    Args:
        subagents: Subagents to modify.
        tool: Tool to inject.
        skip: Subagent names to skip (e.g. those that inherit parent
            tools which already include this tool).
    """
    for sa in subagents:
        if skip and sa.name in skip:
            continue
        if sa.extra_tools is None:
            sa.extra_tools = [tool]
        else:
            sa.extra_tools.append(tool)


def _apply_memory_kill_switch(subagents: list[Subagent], memory: bool) -> None:
    if memory:
        return
    for sa in subagents:
        sa.memory = False


def _apply_compaction(
    subagents: list[Subagent], compaction: CompactionStrategy | None
) -> None:
    """Propagate parent compaction to subagents that don't set their own."""
    if compaction is None:
        return
    for sa in subagents:
        if sa.compaction is None:
            sa.compaction = compaction


def _apply_parent_tools_to_general(
    subagents: list[Subagent],
    tools: Sequence[Tool | ToolDef | ToolSource] | None,
) -> None:
    """Set general() subagent's tools to parent tools if still defaulted."""
    for sa in subagents:
        if sa.name == "general" and sa.tools is None:
            sa.tools = list(tools or [])


def _clone_subagent(sa: Subagent) -> Subagent:
    """Shallow clone a Subagent with fresh list copies.

    Preserves Tool/Model/Limit object identity but avoids mutating the
    caller's Subagent objects or their list fields.
    """
    return replace(
        sa,
        tools=list(sa.tools) if sa.tools is not None else None,
        extra_tools=list(sa.extra_tools) if sa.extra_tools is not None else None,
        limits=list(sa.limits) if sa.limits is not None else None,
    )
