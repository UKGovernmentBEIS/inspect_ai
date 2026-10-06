from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import AsyncIterator, Iterator, Literal


@dataclass(frozen=True)
class AgentBridgeContext:
    """Identity of the agent behind the current bridged model request.

    Read it with `current_agent_bridge_context()` from code running inside a
    bridged request (e.g. a generate filter). For mid-episode control, prefer
    the `is_root_agent()` gate — it is False only for requests attributed to
    a "subagent" or "utility" thread.
    """

    kind: Literal["root", "subagent", "utility", "unknown"]
    """Which agent this bridged model request belongs to.

    - "root": the top-level agent's own thread.
    - "subagent": a delegated agent with its own goal and conversation thread
      (e.g. a Claude Code Task agent or a Codex spawned agent).
    - "utility": model calls made by bridge machinery serving the agent
      (compaction, a tool approver) — no delegated goal or thread. Matches the
      timeline's utility-agent concept.
    - "unknown": the bridge could not determine the calling agent.
    """


@dataclass(frozen=True)
class BridgeRequest:
    """Facts about the bridged request currently being handled."""

    model: str
    """Model slug requested by the scaffold (before model alias resolution)."""


_UNKNOWN_CONTEXT = AgentBridgeContext("unknown")
_UTILITY_CONTEXT = AgentBridgeContext("utility")

_agent_bridge_context: ContextVar[AgentBridgeContext | None] = ContextVar(
    "_agent_bridge_context", default=None
)

_utility_model_calls: ContextVar[bool] = ContextVar(
    "_utility_model_calls", default=False
)

_bridge_request: ContextVar[BridgeRequest | None] = ContextVar(
    "_bridge_request", default=None
)


def current_agent_bridge_context() -> AgentBridgeContext | None:
    """Context for the current bridged model request.

    Returns `None` when not executing within a bridged model request (which
    is distinct from `kind == "root"` — a positive claim that the current
    bridged request belongs to the top-level agent).
    """
    return _agent_bridge_context.get()


def is_sub_agent() -> bool:
    """Does the current bridged model request belong to a sub-agent?

    True only when the current context has `kind == "subagent"`. Conservative
    by design: no context, "root", "utility" and "unknown" all return False.
    """
    context = _agent_bridge_context.get()
    return context is not None and context.kind == "subagent"


def is_root_agent() -> bool:
    """Should the current code treat itself as the top-level agent?

    False only when the current bridged request is attributed to a delegated
    agent's thread (`kind == "subagent"`) or an internal machinery call
    (`kind == "utility"`). True otherwise — including outside bridged
    requests and when attribution is `"unknown"` — so mid-episode control
    keeps working on bridges with no attribution rather than silently
    disabling itself. Consumers that require positive confirmation of root
    should check `current_agent_bridge_context()` for `kind == "root"`
    explicitly.
    """
    context = _agent_bridge_context.get()
    return context is None or context.kind not in ("subagent", "utility")


def set_agent_bridge_context(context: AgentBridgeContext) -> None:
    """Set the agent context for the remainder of the current bridged request.

    For bridge implementers (generate-filter wrappers, in-process scaffolds
    that know their own delegation structure). Call it from the task running
    the filter itself: a set made inside a task the filter spawns (e.g. a task
    group child) changes only that task's copy, so the request keeps its
    previous value and nothing reports the miss.

    Within the current task, the value lasts until the enclosing
    `bridged_request_scope` installed by `bridge_generate` exits, so it cannot
    leak into later requests. Raises `RuntimeError` when called outside a
    bridged request, since the value would otherwise persist, unbounded, in
    the current task. A task spawned during a request keeps a snapshot of the
    context taken when it was spawned, including after the request ends; this
    check does not apply there.

    Args:
        context: Agent context for the current bridged request.

    Raises:
        RuntimeError: If called outside a bridged request (no
            `bridged_request_scope` currently active).
    """
    if _agent_bridge_context.get() is None:
        raise RuntimeError(
            "set_agent_bridge_context() is only valid while a bridged model "
            "request is in flight."
        )
    _agent_bridge_context.set(context)


def current_bridge_request() -> BridgeRequest | None:
    """Facts about the bridged request currently being handled (or None)."""
    return _bridge_request.get()


@contextmanager
def bridged_request_scope(requested_model: str | None) -> Iterator[None]:
    """Stamp default context around one bridged request (bridge_generate only).

    Sets the agent context to unknown (so bridged requests read as "unknown"
    rather than "not bridged") and records the requested model slug, then
    resets both on exit so no value leaks across sequential requests that
    share a task (the in-process bridge path). The reset applies to the
    current task only: tasks spawned during the request keep the snapshot
    they were spawned with.
    """
    context_token = _agent_bridge_context.set(_UNKNOWN_CONTEXT)
    request_token = _bridge_request.set(
        BridgeRequest(model=requested_model) if requested_model is not None else None
    )
    try:
        yield
    finally:
        _agent_bridge_context.reset(context_token)
        _bridge_request.reset(request_token)


@contextmanager
def utility_model_calls() -> Iterator[None]:
    """Attribute model calls made within the block to "utility" (bridge internals).

    For bridge machinery that serves the agent rather than acting as it
    (compaction, tool approval). Only `Model.generate()` calls switch to
    "utility"; other code in the block, such as an approval policy deciding
    on a call, keeps reading the attribution of the request under review.
    """
    token = _utility_model_calls.set(True)
    try:
        yield
    finally:
        _utility_model_calls.reset(token)


@asynccontextmanager
async def utility_model_generate() -> AsyncIterator[None]:
    """Read as "utility" for one `Model.generate()` within `utility_model_calls`."""
    if not _utility_model_calls.get() or _agent_bridge_context.get() is None:
        yield
        return
    token = _agent_bridge_context.set(_UTILITY_CONTEXT)
    try:
        yield
    finally:
        _agent_bridge_context.reset(token)
