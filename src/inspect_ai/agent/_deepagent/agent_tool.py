from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterator, Literal, Sequence

if TYPE_CHECKING:
    from inspect_ai.approval._policy import ApprovalPolicy
    from inspect_ai.tool._tools._skill import Skill

import anyio
from shortuuid import uuid as shortuuid

from inspect_ai.agent._agent import Agent, AgentState
from inspect_ai.agent._react import react
from inspect_ai.agent._run import run
from inspect_ai.agent._types import (
    PARALLEL_TOOLS_PROMPT,
    AgentPrompt,
    AgentSubmit,
)
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.model._model import Model
from inspect_ai.tool._tool import Tool, ToolError, ToolSource, tool
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallContent,
    ToolCallView,
)
from inspect_ai.tool._tool_def import ToolDef

from .prompt import SUBAGENT_SUBMIT_PROMPT
from .subagent import Subagent

logger = getLogger(__name__)

# ---------------------------------------------------------------------------
# Background dispatch registry
# ---------------------------------------------------------------------------

BackgroundStatus = Literal["running", "completed", "errored", "cancelled"]


@dataclass
class AgentFuture:
    """Live state of a background-dispatched subagent.

    Construction is sync-safe: the ``cancel_scope`` and ``started_at``
    fields need an active event loop to populate, so they are passed
    explicitly by ``_dispatch_background`` (which runs inside the loop).
    They are typed ``Optional`` only to allow tests / unit-level use
    outside an event loop; production code always sets them.
    """

    agent_id: str
    """Model-facing handle, e.g. "AGENT-1"."""

    span_id: str
    """Internal shortuuid for log-viewer span correlation."""

    subagent_name: str
    """Subagent type name, e.g. "research"."""

    cancel_scope: anyio.CancelScope | None = None
    """Cancel scope used by ``agent_cancel`` to terminate the child.
    Set by ``_dispatch_background`` before the background coroutine
    is kicked off."""

    started_at: float = 0.0
    """Monotonic time the dispatch was initiated. Set by
    ``_dispatch_background`` via ``anyio.current_time()``."""

    status: BackgroundStatus = "running"
    result: str | None = None
    error: str | None = None
    done: anyio.Event = field(default_factory=anyio.Event)
    child_state: AgentState | None = None
    """Live reference to the child's AgentState — populated by
    ``_run_background`` so the parent can peek messages while running.
    None during the brief window before the background coroutine sets it."""


@dataclass
class BackgroundRegistry:
    """Per-deepagent registry of background agent futures.

    Lives in a ContextVar set/reset in ``deepagent.execute()``. Nested
    deepagents get isolated namespaces because ContextVars carry per-task
    semantics.
    """

    max_background: int
    counter: int = 0
    futures: dict[str, AgentFuture] = field(default_factory=dict)
    notified: set[str] = field(default_factory=set)
    """Agent ids the model has already been shown in a terminal
    (completed/errored) state — either by a lifecycle tool rendering that
    status or by the eager completion push. Gates the injected nudges (the
    eager push and the periodic reminder's "collect" list) so neither
    re-announces a finish the model already saw; never filters what any tool
    displays."""

    def next_id(self) -> str:
        """Allocate the next AGENT-N handle. Counter never reuses."""
        self.counter += 1
        return f"AGENT-{self.counter}"

    def running_count(self) -> int:
        """Number of futures currently in 'running' state.

        Only running futures count toward ``max_background`` — terminal
        futures (completed/errored/cancelled) stay in the registry but
        don't occupy a slot.
        """
        return sum(1 for f in self.futures.values() if f.status == "running")


_background_registry: ContextVar[BackgroundRegistry | None] = ContextVar(
    "_background_registry", default=None
)


@contextmanager
def background_registry(registry: BackgroundRegistry) -> Iterator[BackgroundRegistry]:
    """Install ``registry`` on the ContextVar for the duration of the block.

    The agent tool and lifecycle tools read it via
    ``current_background_registry()``. Nested deepagents get isolated
    namespaces because ContextVars carry per-task semantics. Mirrors the
    set/reset idiom in ``src/inspect_ai/util/_span.py``.
    """
    token = _background_registry.set(registry)
    try:
        yield registry
    finally:
        try:
            _background_registry.reset(token)
        except ValueError:
            # Token belonged to a different context (cleanup across an async
            # boundary). Best-effort — matches the pattern in _span.py.
            pass


def current_background_registry() -> BackgroundRegistry | None:
    """Read the active deepagent's background registry.

    Returns None if no deepagent is currently running on this task.
    """
    return _background_registry.get()


def active_background_agents() -> list[AgentFuture]:
    """Snapshot futures in the current registry.

    Returns an empty list if no registry is active. Reader exposed for
    Phase 4 compaction integration.
    """
    reg = _background_registry.get()
    if reg is None:
        return []
    return list(reg.futures.values())


def _agent_viewer(call: ToolCall) -> ToolCallView:
    """Render an agent() dispatch as a markdown header + prompt body.

    The viewer's content uses ``{{key}}`` placeholders that the framework
    substitutes with the actual tool arguments at render time. When the
    model provides a ``task_description``, it renders as a heading above
    the prompt; when absent, the heading is omitted (otherwise the
    literal ``{{task_description}}`` would render).
    """
    subagent_type = call.arguments.get("subagent_type") or ""
    has_description = bool(call.arguments.get("task_description"))
    content = (
        "### {{task_description}}\n\n{{prompt}}" if has_description else "{{prompt}}"
    )
    return ToolCallView(
        call=ToolCallContent(
            title=f"agent: {subagent_type}",
            format="markdown",
            content=content,
        )
    )


def agent_tool(
    subagents: list[Subagent],
    parent_tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    parent_model: str | Model | None = None,
    parent_skills: list[str | Path | Skill] | None = None,
    depth: int = 0,
    max_depth: int = 1,
    get_messages: Callable[[], list[ChatMessage]] | None = None,
    retry_refusals: int | None = None,
    approval: list[ApprovalPolicy] | None = None,
    background_enabled: bool = True,
) -> Tool:
    """Create an agent multiplexer tool for dispatching to subagents.

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
        background_enabled: When True, the returned tool's schema
            includes a ``background`` parameter and background dispatch
            is available (requires a ``BackgroundRegistry`` on the
            ContextVar). When False, the tool exposes only synchronous
            dispatch — the ``background`` parameter is omitted from the
            schema entirely.
    """
    subagent_map = {s.name: s for s in subagents}
    tool_description = _build_agent_description(
        subagents, background_enabled=background_enabled
    )
    can_parallel = _subagents_parallel_safe(subagents, parent_skills)

    def _prepare_dispatch(
        subagent_type: str,
        prompt: str,
    ) -> tuple[Subagent, Agent, str | list[ChatMessage], str, str | None]:
        """Validate the subagent type and build everything needed for dispatch.

        Returns (sa, child_agent, dispatch_input, agent_span_id, from_message).
        ``dispatch_input`` is a string for non-forked dispatch or a list of
        ChatMessages for forked dispatch. ``from_message`` is the anchor
        for ``timeline_branch`` (forked only) or None.
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
                submit=AgentSubmit(answer_only=True, keep_in_messages=True),
                compaction=sa.compaction,
                retry_refusals=retry_refusals,
                approval=approval,
            )
            dispatch_input, from_message = _prepare_forked_input(
                prompt, sa, get_messages
            )
            return sa, child_agent, dispatch_input, agent_span_id, from_message
        else:
            child_agent = react(
                name=sa.name,
                description=sa.description,
                prompt=AgentPrompt(
                    instructions=sa.prompt,
                    assistant_prompt=f"{PARALLEL_TOOLS_PROMPT}\n\n{SUBAGENT_SUBMIT_PROMPT}",
                    submit_prompt=None,
                    handoff_prompt=None,
                ),
                tools=child_tools,
                model=sa.model or parent_model,
                submit=AgentSubmit(answer_only=True, keep_in_messages=True),
                compaction=sa.compaction,
                retry_refusals=retry_refusals,
                approval=approval,
            )
            return sa, child_agent, prompt, agent_span_id, None

    async def _run_sync(
        sa: Subagent,
        child_agent: Agent,
        dispatch_input: str | list[ChatMessage],
        agent_span_id: str,
        from_message: str | None,
    ) -> str:
        """Synchronous dispatch.

        Blocks until the child returns its final assistant message.
        """
        if sa.fork:
            assert isinstance(dispatch_input, list)
            assert from_message is not None
            return await _dispatch_forked(
                child_agent, sa, dispatch_input, from_message, span_id=agent_span_id
            )
        else:
            return await _dispatch(
                child_agent, sa, dispatch_input, span_id=agent_span_id
            )

    if background_enabled:

        @tool(parallel=can_parallel, viewer=_agent_viewer)
        def agent() -> Tool:
            """Delegate a task to a specialized subagent."""

            async def execute(
                subagent_type: str,
                prompt: str,
                background: bool = False,
                task_description: str | None = None,
            ) -> str:
                """Delegate a task to a specialized subagent.

                Args:
                    subagent_type: Which subagent to use.
                    prompt: Detailed instructions for the subagent. Include
                        all necessary context — the subagent starts with a
                        fresh context and cannot see your conversation history
                        unless it uses forked mode.
                    background: When True, dispatch the subagent in the
                        background and return immediately with an
                        ``AGENT-N`` handle.
                    task_description: Brief description of the task.
                """
                sa, child_agent, dispatch_input, agent_span_id, from_message = (
                    _prepare_dispatch(subagent_type, prompt)
                )

                if background:
                    handle = _dispatch_background(
                        child_agent,
                        sa,
                        dispatch_input,
                        agent_span_id,
                        sa.fork,
                        from_message,
                    )
                    execute.agent_span_id = agent_span_id  # type: ignore[attr-defined]
                    return handle

                result = await _run_sync(
                    sa, child_agent, dispatch_input, agent_span_id, from_message
                )
                execute.agent_span_id = agent_span_id  # type: ignore[attr-defined]
                return result

            execute.__doc__ = tool_description
            return execute

    else:

        @tool(parallel=can_parallel, viewer=_agent_viewer)
        def agent() -> Tool:  # type: ignore[no-redef]
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
                sa, child_agent, dispatch_input, agent_span_id, from_message = (
                    _prepare_dispatch(subagent_type, prompt)
                )
                result = await _run_sync(
                    sa, child_agent, dispatch_input, agent_span_id, from_message
                )
                execute.agent_span_id = agent_span_id  # type: ignore[attr-defined]
                return result

            execute.__doc__ = tool_description
            return execute

    result = agent()
    _apply_subagent_type_enum(result, subagents)
    return result


def _build_agent_description(
    subagents: list[Subagent], background_enabled: bool = True
) -> str:
    lines = ["Delegate a task to a specialized subagent.\n"]
    lines.append("Available subagent types:\n")
    for sa in subagents:
        suffix = " (has conversation context)" if sa.fork else ""
        lines.append(f"- **{sa.name}**: {sa.description}{suffix}")
    lines.append("")
    lines.append(
        "Delegate when the work is multi-step, benefits from tool isolation, "
        "or requires independent research or analysis. Do the work directly "
        "when it's a single tool call, a quick lookup, or a tightly coupled "
        "step whose context would be harder to reconstruct in a subagent prompt."
    )
    lines.append("")
    lines.append(
        "Examples — delegate: 'Search the codebase for all logging "
        "configurations and summarize what each one does.' "
        "Don't delegate: 'Read the file config.yaml and tell me the "
        "timeout value.'"
    )
    lines.append("")
    has_forked = any(sa.fork for sa in subagents)
    if has_forked:
        lines.append(
            "Non-forked subagents start with a fresh context and cannot see "
            "your conversation history. Write the prompt as a self-contained "
            "brief: state the goal, include any relevant findings or data, "
            "and specify what you need back. Forked subagents already have "
            "your full conversation context."
        )
    else:
        lines.append(
            "The subagent starts with a fresh context and cannot see your "
            "conversation history. Write the prompt as a self-contained "
            "brief: state the goal, include any relevant findings or data, "
            "and specify what you need back."
        )
    lines.append("")
    lines.append(
        "The agent tool returns the subagent's final text response. If you "
        "need a specific format, ask for it explicitly in the prompt."
    )
    lines.append("")
    lines.append("Args:")
    lines.append("    subagent_type: Which subagent to use.")
    lines.append(
        "    prompt: Self-contained instructions for the subagent, "
        "including all necessary context."
    )
    if background_enabled:
        lines.append(
            "    background: When True, dispatch the subagent in the "
            "background and return an AGENT-N handle immediately so you "
            "can continue with other work."
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


def _dispatch_background(
    child_agent: Agent,
    sa: Subagent,
    dispatch_input: str | list[ChatMessage],
    span_id: str,
    forked: bool,
    from_message: str | None,
) -> str:
    """Spawn the child agent in the background and return the AGENT-N handle.

    Validates the cap, registers an ``AgentFuture``, and kicks the child
    off via ``background()`` (sample-scoped lifetime).

    All registration is synchronous (no awaits) so the cap check and
    insert form an atomic critical section under cooperative scheduling —
    two parallel ``agent(background=True)`` calls cannot both succeed past
    the cap.
    """
    from inspect_ai.util._background import background

    registry = current_background_registry()
    if registry is None:
        raise ToolError(
            "Background dispatch is not available in this context. "
            "(No deepagent background registry on the current ContextVar.)"
        )

    # Cap check + registration is a single synchronous critical section:
    # there is no `await` between reading running_count() and inserting the
    # future, so the cooperative scheduler cannot interleave a sibling
    # dispatch between the check and the insert (no cap-overrun race). In v1
    # tool calls also execute sequentially, so siblings never even contend.
    if registry.running_count() >= registry.max_background:
        raise ToolError(
            f"Maximum {registry.max_background} background agents reached. "
            f"Call agent_wait or agent_cancel to free a slot."
        )

    agent_id = registry.next_id()
    future = AgentFuture(
        agent_id=agent_id,
        span_id=span_id,
        subagent_name=sa.name,
        cancel_scope=anyio.CancelScope(),
        started_at=anyio.current_time(),
    )
    registry.futures[agent_id] = future

    background(
        _run_background,
        future,
        child_agent,
        sa,
        dispatch_input,
        span_id,
        forked,
        from_message,
    )

    return f"Dispatched {agent_id}."


async def _run_background(
    future: AgentFuture,
    child_agent: Agent,
    sa: Subagent,
    input: str | list[ChatMessage],
    span_id: str,
    forked: bool,
    from_message: str | None,
) -> None:
    """Background coroutine that drives the child agent.

    Inline replication of ``run()``'s body (``src/inspect_ai/agent/_run.py``
    lines 69-104). We construct the ``AgentState`` here so we can hold a
    reference in ``future.child_state`` for the parent's status-peek to
    read — ``run()``'s internal state is unreachable from outside.

    On cancellation (``future.cancel_scope`` is cancelled, or the sample
    ends), we record ``cancelled`` status and re-raise. ``CancelledError``
    derives from ``BaseException`` so the ``except Exception`` in
    ``background()`` (``_background.py:62-65``) will not log it as an
    error.
    """
    from copy import copy, deepcopy

    from inspect_ai._util.exception import TerminateSampleError
    from inspect_ai.event._timeline import timeline_branch
    from inspect_ai.util._limit import LimitExceededError, apply_limits
    from inspect_ai.util._span import AGENT_SPAN_TYPE, span

    assert future.cancel_scope is not None, (
        "_run_background requires a cancel_scope; "
        "_dispatch_background should set this before kicking off."
    )
    try:
        with future.cancel_scope:
            # Coerce input to messages (mirrors _run.py:69-84)
            input = copy(input)
            if isinstance(input, str):
                input_messages: list[ChatMessage] = [
                    ChatMessageUser(content=input, source="input")
                ]
            else:
                input_messages = [
                    msg.model_copy(update=dict(source="input")) for msg in input
                ]

            state = AgentState(messages=input_messages)
            future.child_state = state  # live reference for status peek

            # deepcopy limits per dispatch — Limit objects are single-use
            limits = deepcopy(sa.limits) if sa.limits else []

            with apply_limits(limits, catch_errors=True) as limit_scope:
                async with span(name=sa.name, type=AGENT_SPAN_TYPE, id=span_id):
                    if forked:
                        async with timeline_branch(
                            name=sa.name, from_anchor=from_message or ""
                        ):
                            state = await child_agent(state)
                    else:
                        state = await child_agent(state)

            if limit_scope.limit_error is not None:
                future.result = (
                    f"Subagent '{sa.name}' stopped: {limit_scope.limit_error.message}"
                )
            else:
                future.result = _extract_result(state)
            future.status = "completed"
        # If `agent_cancel` cancelled *our* scope, the CancelledError is
        # absorbed at the `with` boundary (anyio scopes swallow their own
        # cancellation) — so it never reaches the except below. Detect it
        # via cancelled_caught and record the terminal state.
        if future.cancel_scope.cancelled_caught:
            future.status = "cancelled"
    except anyio.get_cancelled_exc_class():
        # Outer cancellation (sample teardown) propagates *through* our
        # inner scope rather than being absorbed. Record and re-raise —
        # structured concurrency requires it to propagate.
        future.status = "cancelled"
        raise
    except (LimitExceededError, TerminateSampleError):
        # Sample-level control flow must propagate so the sample runner
        # records/enforces it (run.py catches these off sample.tg). The
        # subagent's OWN limits were already caught into limit_scope by
        # apply_limits(catch_errors=True), so any LimitExceededError that
        # reaches here belongs to an outer (sample/parent) scope and must
        # not be downgraded to a per-agent "errored" result. The sample is
        # terminating; record a terminal status so the `finally: done.set()`
        # below never wakes a waiter with a stale "running" status.
        future.status = "cancelled"
        raise
    except Exception as ex:
        # A background subagent failure is captured on the future and
        # surfaced via agent_status / agent_wait — it must NOT propagate
        # to sample.tg (that would fail the whole sample). Swallow after
        # recording; log so the failure is still visible in the eval log.
        future.status = "errored"
        future.error = f"{type(ex).__name__}: {ex}"
        logger.warning(
            f"Background agent '{future.agent_id}' ({sa.name}) errored: {ex}"
        )
    finally:
        future.done.set()


async def _dispatch_forked(
    agent: Agent,
    sa: Subagent,
    input: list[ChatMessage],
    from_message: str,
    span_id: str | None = None,
) -> str:
    from inspect_ai.event._timeline import timeline_branch

    async with timeline_branch(name=sa.name, from_anchor=from_message):
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
    # Strip the trailing assistant message (in-flight agent() call).
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
    submit_text = SUBAGENT_SUBMIT_PROMPT.format(submit="submit")
    content = f"{content}\n\n{submit_text}"
    messages.append(ChatMessageUser(content=content, source="input"))
    return messages, from_message


def _extract_result(state: AgentState) -> str:
    if state.output.completion:
        return state.output.completion
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

        if sa.memory == "readwrite":
            tools.append(memory())
        elif sa.memory == "readonly":
            tools.append(memory(readonly=True))

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
        # Background dispatch is a top-level orchestration capability only:
        # the BackgroundRegistry and the agent_status/wait/cancel/list tools
        # live solely at the top level (deepagent.execute). Nested subagents
        # therefore get synchronous dispatch — no `background` parameter —
        # so they can never spawn AGENT-N work they have no tools to manage.
        tools.append(
            agent_tool(
                subagents,
                parent_tools,
                effective_model,
                parent_skills,
                depth + 1,
                max_depth,
                get_messages,
                retry_refusals=retry_refusals,
                approval=approval,
                background_enabled=False,
            )
        )
    return tools


def _subagents_parallel_safe(
    subagents: list[Subagent],
    parent_skills: list[str | Path | Skill] | None,
) -> bool:
    """Can multiple agent() dispatches run concurrently?

    True iff every subagent's effective tool set is itself parallel-safe.
    `memory` and `skill` are both parallel-safe under the current
    implementations (memory has no await points and runs atomically per
    call; skill serialises its lazy install with a per-instance lock).
    """
    for sa in subagents:
        # `sa.tools is None` means the runtime falls back to the read-only
        # defaults (read_file/list_files/grep), all of which are
        # parallel-safe — treat as safe without instantiating them.
        explicit_tools: list[Tool | ToolDef | ToolSource] = []
        if sa.tools is not None:
            explicit_tools.extend(sa.tools)
        if sa.extra_tools is not None:
            explicit_tools.extend(sa.extra_tools)
        for t in explicit_tools:
            if not _tool_is_parallel_safe(t):
                return False
    return True


def _tool_is_parallel_safe(t: Tool | ToolDef | ToolSource) -> bool:
    from inspect_ai._util.registry import is_registry_object
    from inspect_ai.tool._tool_def import tool_def_fields

    if isinstance(t, ToolDef):
        return t.parallel
    if isinstance(t, ToolSource):
        # ToolSources resolve dynamically and we can't introspect their
        # contents at agent_tool() construction time — be conservative.
        return False
    if is_registry_object(t):
        return tool_def_fields(t).parallel
    return False


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
