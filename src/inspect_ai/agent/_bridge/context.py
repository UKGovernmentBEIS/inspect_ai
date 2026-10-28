from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator, Literal, Mapping


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

    subagent_id: str | None = None
    """Identity of the sub-agent instance (only when `kind == "subagent"`).

    Stable across all of one sub-agent's requests and distinct between
    sub-agents, so filters can keep per-sub-agent state (turn counts,
    separate steering). Its format is up to whoever sets the context (e.g.
    a spawned thread id or the tool call id that delegated the work); treat
    it as opaque. `None` is an honest answer, like `"unknown"`: the request
    is known to come from a sub-agent but not which one.
    """

    subagent_type: str | None = None
    """Kind of sub-agent (only when `kind == "subagent"`).

    The scaffold's own name for it, e.g. `"explore"`, `"general"`, or a
    custom agent's name. `None` when the scaffold doesn't say or it can't
    be determined.
    """

    def __post_init__(self) -> None:
        if self.kind != "subagent" and (
            self.subagent_id is not None or self.subagent_type is not None
        ):
            raise ValueError(
                "subagent_id and subagent_type are only valid when "
                f'kind == "subagent" (kind is "{self.kind}").'
            )


@dataclass(frozen=True)
class BridgeRequest:
    """Facts about the bridged request currently being handled."""

    model: str
    """Model slug requested by the scaffold (before model alias resolution)."""

    headers: dict[str, str] = field(default_factory=dict, hash=False)
    """Client request headers listed in `expose_client_headers` (lowercase names)."""


def _exposed_headers(headers: object, names: frozenset[str]) -> dict[str, str]:
    exposed: dict[str, str] = {}
    if not names or not isinstance(headers, Mapping):
        return exposed
    for name, value in headers.items():
        if isinstance(name, str) and isinstance(value, str):
            lower_name = name.lower()
            if lower_name in names:
                exposed[lower_name] = (
                    f"{exposed[lower_name]}, {value}"
                    if lower_name in exposed
                    else value
                )
    return exposed


_UNKNOWN_CONTEXT = AgentBridgeContext("unknown")
_UTILITY_CONTEXT = AgentBridgeContext("utility")

_agent_bridge_context: ContextVar[AgentBridgeContext | None] = ContextVar(
    "_agent_bridge_context", default=None
)

_bridge_request: ContextVar[BridgeRequest | None] = ContextVar(
    "_bridge_request", default=None
)

# set at each bridge entry point, read by `bridged_request_scope`
_client_request_headers: ContextVar[dict[str, str] | None] = ContextVar(
    "_client_request_headers", default=None
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
def client_request_headers_scope(
    headers: object, names: frozenset[str]
) -> Iterator[None]:
    """Record the client's `names` headers for the bridged request handled within."""
    token = _client_request_headers.set(_exposed_headers(headers, names))
    try:
        yield
    finally:
        _client_request_headers.reset(token)


@contextmanager
def bridged_request_scope(requested_model: str | None) -> Iterator[None]:
    """Stamp default context around one bridged request (bridge_generate only).

    Sets the agent context to unknown (so bridged requests read as "unknown"
    rather than "not bridged") and records the requested model slug and the
    client's request headers (from `client_request_headers_scope`), then
    resets both on exit so no value leaks across sequential requests that
    share a task (the in-process bridge path). The reset applies to the
    current task only: tasks spawned during the request keep the snapshot
    they were spawned with.
    """
    context_token = _agent_bridge_context.set(_UNKNOWN_CONTEXT)
    # consume them so a nested bridged request doesn't inherit them
    headers = _client_request_headers.get()
    headers_token = _client_request_headers.set(None)
    request_token = _bridge_request.set(
        BridgeRequest(model=requested_model, headers=dict(headers or {}))
        if requested_model is not None
        else None
    )
    try:
        yield
    finally:
        _agent_bridge_context.reset(context_token)
        _client_request_headers.reset(headers_token)
        _bridge_request.reset(request_token)


@contextmanager
def agent_bridge_context_scope(context: AgentBridgeContext) -> Iterator[None]:
    """Temporarily install a specific agent context (bridge internals)."""
    token = _agent_bridge_context.set(context)
    try:
        yield
    finally:
        _agent_bridge_context.reset(token)
