from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable, Sequence

if TYPE_CHECKING:
    from inspect_ai.approval._policy import ApprovalPolicy
    from inspect_ai.tool._tools._skill import Skill

from shortuuid import uuid as shortuuid

from inspect_ai.agent._agent import Agent, AgentState
from inspect_ai.agent._react import react
from inspect_ai.agent._run import run
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.model._model import Model
from inspect_ai.tool._tool import Tool, ToolError, ToolSource, tool
from inspect_ai.tool._tool_def import ToolDef

from .subagent import Subagent


def task_tool(
    subagents: list[Subagent],
    parent_tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    parent_model: str | Model | None = None,
    parent_skills: list[str | Path | Skill] | None = None,
    depth: int = 0,
    max_depth: int = 1,
    get_messages: Callable[[], list[ChatMessage]] | None = None,
    retry_refusals: int | None = None,
    approval: list[ApprovalPolicy] | None = None,
) -> Tool:
    """Create a task multiplexer tool for dispatching to subagents.

    Args:
        subagents: List of available subagent configurations.
        parent_tools: Tools from the parent agent (flow to general()).
        parent_model: Parent agent's model (inherited by subagents
            that don't set their own).
        parent_skills: Parent agent's skills (merged with subagent
            skills at dispatch time).
        depth: Current recursion depth.
        max_depth: Maximum recursion depth.
        get_messages: Callback returning parent messages (required for
            forked dispatch).
        retry_refusals: Number of times to retry on content filter
            refusals.
        approval: Approval policies for tool calls.
    """
    subagent_map = {s.name: s for s in subagents}
    tool_description = _build_task_description(subagents)

    @tool
    def task() -> Tool:
        """Delegate a task to a specialized subagent."""

        async def execute(
            subagent_type: str,
            prompt: str,
            task_description: str | None = None,
        ) -> str:
            """Delegate a task to a specialized subagent.

            Args:
                subagent_type: Which subagent to use.
                prompt: Detailed instructions for the subagent. Include
                    all necessary context — the subagent starts with a
                    fresh context and cannot see your conversation history
                    unless it uses forked mode.
                task_description: Brief description of the task.
            """
            sa = subagent_map.get(subagent_type)
            if sa is None:
                available = ", ".join(subagent_map.keys())
                raise ToolError(
                    f"Unknown subagent_type: {subagent_type!r}. "
                    f"Available types: {available}"
                )

            child_tools = _resolve_tools(
                sa,
                subagents,
                parent_tools,
                parent_model,
                parent_skills,
                depth,
                max_depth,
                get_messages,
                retry_refusals,
                approval,
            )

            agent_span_id = shortuuid()

            if sa.fork:
                child_agent = react(
                    name=sa.name,
                    description=sa.description,
                    prompt=None,
                    tools=child_tools,
                    model=sa.model or parent_model,
                    submit=False,
                    compaction=sa.compaction,
                    retry_refusals=retry_refusals,
                    approval=approval,
                )
                input, from_message = _prepare_forked_input(prompt, sa, get_messages)
                result = await _dispatch_forked(
                    child_agent, sa, input, from_message, span_id=agent_span_id
                )
            else:
                child_agent = react(
                    name=sa.name,
                    description=sa.description,
                    prompt=sa.prompt,
                    tools=child_tools,
                    model=sa.model or parent_model,
                    submit=False,
                    compaction=sa.compaction,
                    retry_refusals=retry_refusals,
                    approval=approval,
                )
                result = await _dispatch(child_agent, sa, prompt, span_id=agent_span_id)

            execute.agent_span_id = agent_span_id  # type: ignore[attr-defined]
            return result

        execute.__doc__ = tool_description
        return execute

    result = task()
    _apply_subagent_type_enum(result, subagents)
    return result


def _build_task_description(subagents: list[Subagent]) -> str:
    lines = ["Delegate a task to a specialized subagent.\n"]
    lines.append("Available subagent types:\n")
    for sa in subagents:
        suffix = " (has conversation context)" if sa.fork else ""
        lines.append(f"- **{sa.name}**: {sa.description}{suffix}")
    lines.append("")
    lines.append(
        "Delegate when the work is complex, independent, or would benefit "
        "from a fresh context. Do the work directly when it's a simple "
        "lookup or single tool call."
    )
    lines.append("")
    has_forked = any(sa.fork for sa in subagents)
    lines.append("Args:")
    lines.append("    subagent_type: Which subagent to use.")
    if has_forked:
        lines.append(
            "    prompt: Detailed instructions for the subagent. Non-forked"
            " subagents start with a fresh context and cannot see your"
            " conversation history — include all necessary context for them."
            " Forked subagents already have your full conversation context."
        )
    else:
        lines.append(
            "    prompt: Detailed instructions for the subagent. Include"
            " all necessary context — the subagent starts with a fresh"
            " context and cannot see your conversation history."
        )
    lines.append("    task_description: Brief description of the task.")
    return "\n".join(lines)


async def _dispatch(
    agent: Agent,
    sa: Subagent,
    input: str | list[ChatMessage],
    span_id: str | None = None,
) -> str:
    from copy import deepcopy

    # deepcopy limits per dispatch — Limit objects are single-use
    limits = deepcopy(sa.limits) if sa.limits else []
    if limits:
        state, limit_error = await run(
            agent, input=input, limits=limits, name=sa.name, span_id=span_id
        )
        if limit_error:
            return f"Subagent '{sa.name}' stopped: {limit_error.message}"
    else:
        state = await run(agent, input=input, name=sa.name, span_id=span_id)
    return _extract_result(state)


async def _dispatch_forked(
    agent: Agent,
    sa: Subagent,
    input: list[ChatMessage],
    from_message: str,
    span_id: str | None = None,
) -> str:
    from inspect_ai.event._timeline import timeline_branch
    from inspect_ai.util._span import current_span_id

    from_span = current_span_id() or ""

    async with timeline_branch(
        name=sa.name, from_span=from_span, from_message=from_message
    ):
        return await _dispatch(agent, sa, input, span_id=span_id)


def _prepare_forked_input(
    prompt: str,
    sa: Subagent,
    get_messages: Callable[[], list[ChatMessage]] | None,
) -> tuple[list[ChatMessage], str]:
    if get_messages is None:
        raise ToolError(
            f"Forked dispatch for '{sa.name}' requires parent messages, "
            "but no get_messages callback was provided."
        )

    # Keep parent system message (preserves prompt cache on all providers).
    # Strip the trailing assistant message (in-flight task() call).
    # Subagent instructions + task prompt go in a single user message
    # appended after the cached prefix.
    messages = list(get_messages())
    if messages and isinstance(messages[-1], ChatMessageAssistant):
        messages.pop()

    # Capture branch point before appending the synthetic child prompt.
    from_message = _last_message_id(messages)

    content = prompt
    if sa.prompt:
        content = f"{sa.prompt}\n\n{content}"
    messages.append(ChatMessageUser(content=content, source="input"))
    return messages, from_message


def _extract_result(state: AgentState) -> str:
    if not state.output.empty:
        return state.output.message.text
    elif len(state.messages) > 0 and isinstance(
        state.messages[-1], ChatMessageAssistant
    ):
        return state.messages[-1].text
    else:
        return ""


def _apply_subagent_type_enum(tool: Tool, subagents: list[Subagent]) -> None:
    """Patch the subagent_type parameter with an enum constraint.

    Sets all three ToolDescription fields (name, description, parameters)
    so parse_tool_info() uses them directly instead of re-parsing.
    """
    from inspect_ai._util.registry import registry_unqualified_name
    from inspect_ai.tool._tool_description import (
        ToolDescription,
        set_tool_description,
    )
    from inspect_ai.tool._tool_info import parse_tool_info

    info = parse_tool_info(tool)
    param = info.parameters.properties.get("subagent_type")
    if param:
        param.enum = [sa.name for sa in subagents]

    set_tool_description(
        tool,
        ToolDescription(
            name=registry_unqualified_name(tool),
            description=info.description,
            parameters=info.parameters,
        ),
    )


def _has_memory_tool(tools: Sequence[Tool | ToolDef | ToolSource]) -> bool:
    return _find_memory_tool(tools) is not None


def _find_memory_tool(
    tools: Sequence[Tool | ToolDef | ToolSource],
) -> Tool | ToolDef | None:
    from inspect_ai._util.registry import is_registry_object, registry_unqualified_name

    for t in tools:
        if is_registry_object(t):
            if registry_unqualified_name(t) == "memory":
                return t  # type: ignore[return-value]
        elif isinstance(t, ToolDef) and t.name == "memory":
            return t
    return None


def _get_memory_initial_data(
    tools: Sequence[Tool | ToolDef | ToolSource],
) -> dict[str, str] | None:
    mem = _find_memory_tool(tools)
    if mem is None:
        return None
    # Tool stores the callable directly; ToolDef stores it on .tool
    callable_ = getattr(mem, "tool", None) or getattr(mem, "execute", mem)
    return getattr(callable_, "initial_data", None)


def _resolve_tools(
    sa: Subagent,
    subagents: list[Subagent],
    parent_tools: Sequence[Tool | ToolDef | ToolSource] | None,
    parent_model: str | Model | None,
    parent_skills: list[str | Path | Skill] | None,
    depth: int,
    max_depth: int,
    get_messages: Callable[[], list[ChatMessage]] | None,
    retry_refusals: int | None = None,
    approval: list[ApprovalPolicy] | None = None,
) -> list[Tool | ToolDef | ToolSource]:
    tools: list[Tool | ToolDef | ToolSource] = []
    if sa.tools is not None:
        tools.extend(sa.tools)
    else:
        tools.extend(_default_readonly_tools())
    if sa.extra_tools is not None:
        tools.extend(sa.extra_tools)
    if sa.memory and not _has_memory_tool(tools):
        from inspect_ai.tool._tools._memory import memory

        parent_initial_data = _get_memory_initial_data(parent_tools or [])
        if sa.memory == "readwrite":
            tools.append(memory(initial_data=parent_initial_data))
        elif sa.memory == "readonly":
            tools.append(memory(initial_data=parent_initial_data, readonly=True))

    # Merge parent + subagent skills with instance scoping.
    # Duplicate names are validated globally in deepagent.execute().
    merged_skills = list(parent_skills or []) + list(sa.skills or [])
    if merged_skills:
        from inspect_ai.tool._tools._skill import skill as skill_fn

        tools.append(skill_fn(merged_skills, instance=sa.name))

    if depth + 1 < max_depth:
        # Pass the effective model (sa.model or parent_model) so nested
        # subagents inherit the calling subagent's model, not the top-level
        effective_model = sa.model or parent_model
        tools.append(
            task_tool(
                subagents,
                parent_tools,
                effective_model,
                parent_skills,
                depth + 1,
                max_depth,
                get_messages,
                retry_refusals=retry_refusals,
                approval=approval,
            )
        )
    return tools


def _default_readonly_tools() -> list[Tool | ToolDef | ToolSource]:
    from inspect_ai.util._sandbox.context import sandbox_environments_context_var

    if sandbox_environments_context_var.get(None) is None:
        return []
    from inspect_ai.tool._tools._grep import grep
    from inspect_ai.tool._tools._list_files import list_files
    from inspect_ai.tool._tools._read_file import read_file

    return [read_file(), list_files(), grep()]


def _last_message_id(messages: list[ChatMessage]) -> str:
    for msg in reversed(messages):
        if msg.id:
            return msg.id
    return ""
