import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Mapping


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


class _ReadOnlyHeaders(Mapping[str, str]):
    """Immutable header mapping that (unlike `MappingProxyType`) copies and pickles."""

    __slots__ = ("_headers",)

    def __init__(self, headers: Mapping[str, str] | None = None) -> None:
        self._headers = dict(headers or {})

    def __getitem__(self, key: str) -> str:
        return self._headers[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._headers)

    def __len__(self) -> int:
        return len(self._headers)

    def __repr__(self) -> str:
        return repr(self._headers)

    def __reduce__(self) -> tuple[Any, ...]:
        return (_ReadOnlyHeaders, (self._headers,))


@dataclass(frozen=True)
class BridgeRequest:
    """Facts about the bridged request currently being handled."""

    model: str
    """Model slug requested by the scaffold (before model alias resolution)."""

    headers: Mapping[str, str] = field(default_factory=_ReadOnlyHeaders, hash=False)
    """Client request headers (lowercased, read-only), minus credential headers."""

    def __post_init__(self) -> None:
        if not isinstance(self.headers, _ReadOnlyHeaders):
            object.__setattr__(self, "headers", _ReadOnlyHeaders(self.headers))


_EMPTY_HEADERS: Mapping[str, str] = _ReadOnlyHeaders()

# Credential header names (lowercase): never exposed on `BridgeRequest.headers`
# and never forwarded from a sandboxed client to the provider (`bridge.py`)
CREDENTIAL_HEADERS = frozenset(
    [
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "x-goog-api-key",
        "cookie",
    ]
)
CREDENTIAL_HEADER_PREFIXES = ("x-amz-",)
_CREDENTIAL_HEADER_FRAGMENTS = (
    "key",
    "signature",
    "auth",
    "token",
    "secret",
    "password",
    "credential",
    "cookie",
)


_CREDENTIAL_VALUE = re.compile(r"\s*((bearer|basic|token)\s|sk-)", re.IGNORECASE)


def _is_credential_header(lower_name: str) -> bool:
    name = lower_name.replace("_", "-")
    return (
        name in CREDENTIAL_HEADERS
        or name.startswith(CREDENTIAL_HEADER_PREFIXES)
        or any(fragment in name for fragment in _CREDENTIAL_HEADER_FRAGMENTS)
    )


def _is_credential_value(value: str) -> bool:
    # repeated headers arrive joined with ", ", so check each part
    return any(_CREDENTIAL_VALUE.match(part) for part in value.split(","))


def sanitize_client_headers(headers: object) -> Mapping[str, str]:
    """Client request headers as exposed on `BridgeRequest.headers`.

    Lowercases names, joins repeated names with ", ", drops non-string names
    or values and credential headers, and returns a read-only mapping.
    """
    if not isinstance(headers, Mapping) or not headers:
        return _EMPTY_HEADERS
    sanitized: dict[str, str] = {}
    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        lower_name = name.lower()
        if _is_credential_header(lower_name) or _is_credential_value(value):
            continue
        if lower_name in sanitized:
            sanitized[lower_name] = f"{sanitized[lower_name]}, {value}"
        else:
            sanitized[lower_name] = value
    return _ReadOnlyHeaders(sanitized) if sanitized else _EMPTY_HEADERS


_UNKNOWN_CONTEXT = AgentBridgeContext("unknown")
_UTILITY_CONTEXT = AgentBridgeContext("utility")

_agent_bridge_context: ContextVar[AgentBridgeContext | None] = ContextVar(
    "_agent_bridge_context", default=None
)

_bridge_request: ContextVar[BridgeRequest | None] = ContextVar(
    "_bridge_request", default=None
)

# Client headers of the request being handled, set by the bridge's entry
# point (sandbox model service or in-process SDK patch) and read by the
# `bridged_request_scope` that `bridge_generate` opens for that request.
_client_request_headers: ContextVar[Mapping[str, str]] = ContextVar(
    "_client_request_headers", default=_EMPTY_HEADERS
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
def client_request_headers_scope(headers: object) -> Iterator[None]:
    """Record the client's request headers for the bridged request handled within.

    For bridge entry points: wrap the call that translates and generates one
    client request. The headers are sanitized (`sanitize_client_headers`) and
    exposed as `BridgeRequest.headers`. They are never forwarded anywhere.
    """
    token = _client_request_headers.set(sanitize_client_headers(headers))
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
    # consume the client headers: they belong to this request only, not to a
    # bridged request nested inside it that has no entry point of its own
    headers = _client_request_headers.get()
    headers_token = _client_request_headers.set(_EMPTY_HEADERS)
    request_token = _bridge_request.set(
        BridgeRequest(model=requested_model, headers=headers)
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
