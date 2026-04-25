from typing import Callable, Sequence

from inspect_ai.agent._agent import Agent, AgentState
from inspect_ai.agent._react import react
from inspect_ai.agent._run import run
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.tool._tool import Tool, ToolError, ToolSource, tool, tool_result_content
from inspect_ai.tool._tool_def import ToolDef

from .subagent import Subagent


def task_tool(
    subagents: list[Subagent],
    parent_tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    depth: int = 0,
    max_depth: int = 1,
    get_messages: Callable[[], list[ChatMessage]] | None = None,
) -> Tool:
    """Create a task multiplexer tool for dispatching to subagents.

    Args:
        subagents: List of available subagent configurations.
        parent_tools: Tools from the parent agent (flow to general()).
        depth: Current recursion depth.
        max_depth: Maximum recursion depth.
        get_messages: Callback returning parent messages (required for
            forked dispatch).
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
            resolved = SUBAGENT_ALIASES.get(subagent_type, subagent_type)
            sa = subagent_map.get(resolved)
            if sa is None:
                available = ", ".join(subagent_map.keys())
                raise ToolError(
                    f"Unknown subagent_type: {subagent_type!r}. "
                    f"Available types: {available}"
                )

            child_tools = _resolve_tools(
                sa, subagents, parent_tools, depth, max_depth, get_messages
            )

            child_agent = react(
                name=sa.name,
                description=sa.description,
                prompt=sa.prompt,
                tools=child_tools,
                model=sa.model,
                submit=False,
            )

            if sa.fork:
                input = _prepare_forked_input(prompt, sa, get_messages)
                return await _dispatch_forked(child_agent, sa, input)
            else:
                return await _dispatch(child_agent, sa, prompt)

        execute.__doc__ = tool_description
        return execute

    return task()


def _build_task_description(subagents: list[Subagent]) -> str:
    lines = ["Delegate a task to a specialized subagent.\n"]
    lines.append("Available subagent types:\n")
    for sa in subagents:
        lines.append(f"- **{sa.name}**: {sa.description}")
    lines.append("")
    lines.append(
        "Delegate when the work is complex, independent, or would benefit "
        "from a fresh context. Do the work directly when it's a simple "
        "lookup or single tool call."
    )
    lines.append("")
    lines.append("Args:")
    lines.append("    subagent_type: Which subagent to use.")
    lines.append(
        "    prompt: Detailed instructions for the subagent. Include"
        " all necessary context — the subagent starts with a fresh"
        " context and cannot see your conversation history unless"
        " it uses forked mode."
    )
    lines.append("    task_description: Brief description of the task.")
    return "\n".join(lines)


async def _dispatch(
    agent: Agent,
    sa: Subagent,
    input: str | list[ChatMessage],
) -> str:
    limits = sa.limits or []
    if limits:
        state, limit_error = await run(agent, input=input, limits=limits, name=sa.name)
        if limit_error:
            return f"Subagent '{sa.name}' stopped: {limit_error}"
    else:
        state = await run(agent, input=input, name=sa.name)
    return _extract_result(state)


async def _dispatch_forked(
    agent: Agent,
    sa: Subagent,
    input: list[ChatMessage],
) -> str:
    from inspect_ai.event._timeline import timeline_branch
    from inspect_ai.util._span import current_span_id

    from_span = current_span_id() or ""
    from_message = _last_message_id(input)

    async with timeline_branch(
        name=sa.name, from_span=from_span, from_message=from_message
    ):
        return await _dispatch(agent, sa, input)


def _prepare_forked_input(
    prompt: str,
    sa: Subagent,
    get_messages: Callable[[], list[ChatMessage]] | None,
) -> list[ChatMessage]:
    if get_messages is None:
        raise ToolError(
            f"Forked dispatch for '{sa.name}' requires parent messages, "
            "but no get_messages callback was provided."
        )
    messages = list(get_messages())
    messages.append(ChatMessageUser(content=prompt, source="input"))
    return messages


def _extract_result(state: AgentState) -> str:
    if not state.output.empty:
        result = tool_result_content(state.output.message.content)
        return result if isinstance(result, str) else ""
    elif len(state.messages) > 0 and isinstance(
        state.messages[-1], ChatMessageAssistant
    ):
        result = tool_result_content(state.messages[-1].content)
        return result if isinstance(result, str) else ""
    else:
        return ""


def _resolve_tools(
    sa: Subagent,
    subagents: list[Subagent],
    parent_tools: Sequence[Tool | ToolDef | ToolSource] | None,
    depth: int,
    max_depth: int,
    get_messages: Callable[[], list[ChatMessage]] | None,
) -> list[Tool | ToolDef | ToolSource]:
    tools: list[Tool | ToolDef | ToolSource] = []
    if sa.tools is not None:
        tools.extend(sa.tools)
    if sa.extra_tools is not None:
        tools.extend(sa.extra_tools)
    if depth < max_depth:
        tools.append(
            task_tool(subagents, parent_tools, depth + 1, max_depth, get_messages)
        )
    return tools


def _last_message_id(messages: list[ChatMessage]) -> str:
    for msg in reversed(messages):
        if msg.id:
            return msg.id
    return ""


SUBAGENT_ALIASES: dict[str, str] = {
    "general_purpose": "general",
}
