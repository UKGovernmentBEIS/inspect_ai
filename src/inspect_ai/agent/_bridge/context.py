from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Literal

AgentBridgeContextKind = Literal["root", "subagent", "utility", "unknown"]
"""Which agent a bridged model request belongs to.

- "root": the top-level agent's own thread.
- "subagent": a delegated agent with its own goal and conversation thread
  (e.g. a Claude Code Task agent or a Codex spawned agent).
- "utility": machinery calls serving the main agent's plumbing (compaction,
  approval review, internal helper models) — no delegated goal or thread.
  Matches the timeline's utility-agent concept.
- "unknown": the bridge could not determine the calling agent.
"""

AgentBridgeContextCertainty = Literal["structural", "inferred"]
"""How the kind was determined.

- "structural": derived from a protocol or configuration signal (e.g. a
  distinct requested model slug, an inter-agent message address, or a
  scaffold with no delegation capability).
- "inferred": derived from a heuristic (e.g. spawn-prompt matching). By
  convention "inferred" is also used when kind is "unknown".
"""


@dataclass(frozen=True)
class AgentBridgeContext:
    """Identity of the agent behind the current bridged model request.

    Read it with `current_agent_bridge_context()` from code running inside a
    bridged request (e.g. a generate filter). The safe steering idiom for
    mid-episode control is to act only when the context is None (not a
    bridged request) or `kind == "root"` — "subagent", "utility" and
    "unknown" all land on the don't-intervene side.
    """

    kind: AgentBridgeContextKind
    """Which agent this bridged model request belongs to."""

    certainty: AgentBridgeContextCertainty
    """How kind was determined ('structural' signal vs 'inferred' heuristic)."""

    @property
    def is_root(self) -> bool:
        """Is this the top-level agent's own thread?"""
        return self.kind == "root"


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
    """Does the current bridged model request belong to the top-level agent?

    True only when the current context has `kind == "root"` — a positive
    attribution claim. False otherwise, including outside bridged requests
    and when attribution is `"unknown"`.

    This is the strict gate for mid-episode control: act only on confirmed
    root. Prefer it when the bridge is run by a package that provides
    attribution (e.g. inspect_swe). When attribution may be absent (a plain
    bridge where every request reads `"unknown"`), use `not is_sub_agent()`
    as the permissive gate instead.
    """
    context = _agent_bridge_context.get()
    return context is not None and context.kind == "root"


def set_agent_bridge_context(context: AgentBridgeContext) -> None:
    """Set the agent context for the remainder of the current bridged request.

    For bridge implementers (generate-filter wrappers, in-process scaffolds
    that know their own delegation structure). The value's lifetime is
    bounded by the enclosing `bridged_request_scope` installed by
    `bridge_generate` — it cannot leak across requests. Only valid while a
    bridged request is in flight; calling it outside one leaves an unbounded
    value in the current context.
    """
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
    context_token = _agent_bridge_context.set(AgentBridgeContext("unknown", "inferred"))
    request_token = _bridge_request.set(
        BridgeRequest(model=requested_model) if requested_model is not None else None
    )
    try:
        yield
    finally:
        _agent_bridge_context.reset(context_token)
        _bridge_request.reset(request_token)
