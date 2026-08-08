from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Literal


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
    - "utility": machinery calls serving the main agent's plumbing (compaction,
      approval review, internal helper models) — no delegated goal or thread.
      Matches the timeline's utility-agent concept.
    - "unknown": the bridge could not determine the calling agent.
    """


@dataclass(frozen=True)
class BridgeRequest:
    """Facts about the bridged request currently being handled."""

    model: str
    """Model slug requested by the scaffold (before model alias resolution)."""


_agent_bridge_context: ContextVar[AgentBridgeContext | None] = ContextVar(
    "_agent_bridge_context", default=None
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
    that know their own delegation structure). The value's lifetime is
    bounded by the enclosing `bridged_request_scope` installed by
    `bridge_generate` — it cannot leak across requests. Raises `RuntimeError`
    when called outside a bridged request (no scope active), since the value
    would otherwise leak, unbounded, into the current context.

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
    share a task (the in-process bridge path).
    """
    context_token = _agent_bridge_context.set(AgentBridgeContext("unknown"))
    request_token = _bridge_request.set(
        BridgeRequest(model=requested_model) if requested_model is not None else None
    )
    try:
        yield
    finally:
        _agent_bridge_context.reset(context_token)
        _bridge_request.reset(request_token)


@contextmanager
def agent_bridge_context_scope(context: AgentBridgeContext) -> Iterator[None]:
    """Temporarily install a specific agent context (bridge internals)."""
    token = _agent_bridge_context.set(context)
    try:
        yield
    finally:
        _agent_bridge_context.reset(token)


def reset_agent_bridge_context_default() -> None:
    """Re-stamp the ambient agent context to the default (bridge internals)."""
    _agent_bridge_context.set(AgentBridgeContext("unknown"))
