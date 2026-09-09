"""Shared HTTP client defaults for provider SDK clients.

The SDK defaults are tuned for a caller whose event loop is responsive. An
inspect runner's loop is not: long CPU-bound sections (payload transforms,
transcript scans) hold it for seconds at a time, and a connect deadline that
expires during one of those blocks fails a connection that the kernel already
completed — anyio's cancellation lands on the first checkpoint after the loop
resumes, so a finished connect is no defence.

Three defaults follow, all overridable by environment variable:

* ``connect`` at 60s rather than 5s. A partial raise buys nothing (a 26s block
  failed 75% at 5s and 76.7% at 15s, 0% at 30s), and the deadline has to clear
  *several* blocks: a connect that misses its window waits out whole blocks, so
  failure latency quantises to multiples of the block length (a 3s block
  against a 5s deadline failed 77% of the time, median 6.1s). The cost is that
  a dead endpoint takes 120s to detect, since the retry below gives it a second
  full deadline; httpcore charges the deadline separately to the TCP connect
  and the TLS handshake, so a slow-then-stalling endpoint can reach 4x, and an
  SDK that retries multiplies that again.

* ``max_keepalive_connections`` at the connection limit rather than 100. Above
  the cap every connection is destroyed the moment it goes idle, stepping the
  new-connection rate ~20x once concurrency passes ~120, and only new
  connections run the connect path at all.

* One connection-establishment retry. httpcore retries the connect only and
  never re-sends the request, so it is safe for non-idempotent calls. It needs
  the loop running again by the time it fires, so it rescues a lightly loaded
  caller and does little for a saturated one.

The transport also carries the TCP keepalive socket options the Anthropic SDK
sets on its own, since they live on the transport and supplying one drops them.
Supplying a transport likewise turns off httpx's environment proxy discovery,
so the proxy mounts are rebuilt here and given the same settings.

``keepalive_expiry`` stays at httpx's 5s default: raising it past an
intermediary's idle timeout (an ALB commonly defaults to 60s) trades these
failures for stale-connection ones. Note this leaves the
``max_keepalive_connections`` raise inert whenever blocks outlast the expiry,
which is the case that motivated it (at a 6s block, 100 versus 1000 changed
nothing, both failing every request). A deployment that knows its own topology
should raise the expiry alongside the cap.
"""

from __future__ import annotations

import os
import socket
from logging import getLogger
from typing import Any, overload

import httpx

from inspect_ai._util.logger import warn_once

logger = getLogger(__name__)


def _no_environment_proxies() -> dict[str, str | None]:
    return {}


try:
    # Private to httpx, but replicating its NO_PROXY rules would drift; the
    # anthropic SDK vendors a copy for the same reason. Degrade to no mounts
    # rather than failing to import if httpx moves it.
    from httpx._utils import get_environment_proxies as _get_environment_proxies
except ImportError:  # pragma: no cover - httpx moved its internals
    _get_environment_proxies = _no_environment_proxies

DEFAULT_CONNECT_TIMEOUT = 60.0
DEFAULT_REQUEST_TIMEOUT = 600.0
DEFAULT_POOL_CONNECTIONS = 1000
DEFAULT_KEEPALIVE_EXPIRY = 5.0
DEFAULT_CONNECT_RETRIES = 1

CONNECT_TIMEOUT_ENV = "INSPECT_HTTP_CONNECT_TIMEOUT"
REQUEST_TIMEOUT_ENV = "INSPECT_HTTP_REQUEST_TIMEOUT"
POOL_CONNECTIONS_ENV = "INSPECT_HTTP_POOL_CONNECTIONS"
POOL_KEEPALIVE_CONNECTIONS_ENV = "INSPECT_HTTP_POOL_KEEPALIVE_CONNECTIONS"
KEEPALIVE_EXPIRY_ENV = "INSPECT_HTTP_KEEPALIVE_EXPIRY"
CONNECT_RETRIES_ENV = "INSPECT_HTTP_CONNECT_RETRIES"


def _ignored(name: str, raw: str, reason: str, fallback: object) -> None:
    # Silence would leave an operator believing a setting took effect.
    warn_once(logger, f"Ignoring {name}={raw!r} ({reason}); using {fallback} instead.")


def _env_float(name: str, fallback: float) -> float:
    """A non-negative float from the environment, `fallback` on unset or junk."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return fallback
    try:
        value = float(raw)
    except ValueError:
        _ignored(name, raw, "not a number", fallback)
        return fallback
    if value < 0:
        _ignored(name, raw, "must be >= 0", fallback)
        return fallback
    return value


@overload
def _env_int(name: str, fallback: int, *, minimum: int = 0) -> int: ...


@overload
def _env_int(name: str, fallback: None, *, minimum: int = 0) -> int | None: ...


def _env_int(name: str, fallback: int | None, *, minimum: int = 0) -> int | None:
    """A whole number >= `minimum` from the environment, `fallback` on unset or junk."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return fallback
    try:
        value = int(raw)
    except ValueError:
        _ignored(name, raw, "not a whole number", fallback)
        return fallback
    if value < minimum:
        _ignored(name, raw, f"must be >= {minimum}", fallback)
        return fallback
    return value


def connect_timeout() -> float:
    return _env_float(CONNECT_TIMEOUT_ENV, DEFAULT_CONNECT_TIMEOUT)


def default_timeout(
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> httpx.Timeout:
    """Timeouts, with the environment overriding `request_timeout`.

    The argument is only the fallback, so a provider whose SDK has a budget of
    its own can pass it and keep it until an operator sets the variable.
    """
    return httpx.Timeout(
        timeout=_env_float(REQUEST_TIMEOUT_ENV, request_timeout),
        connect=connect_timeout(),
    )


def default_limits(
    max_connections: int | None = DEFAULT_POOL_CONNECTIONS,
) -> httpx.Limits:
    """Pool limits, with the environment overriding `max_connections`.

    The argument is only the fallback, so a provider whose pool is deliberately
    uncapped can pass None and keep it until an operator sets the variable.
    """
    # A zero-connection pool can never issue a request, so it is junk not a setting.
    connections = _env_int(POOL_CONNECTIONS_ENV, max_connections, minimum=1)
    return httpx.Limits(
        max_connections=connections,
        # Tracks the pool size unless set outright, so lowering the limit
        # cannot leave a keepalive cap above it.
        max_keepalive_connections=_env_int(POOL_KEEPALIVE_CONNECTIONS_ENV, connections),
        keepalive_expiry=_env_float(KEEPALIVE_EXPIRY_ENV, DEFAULT_KEEPALIVE_EXPIRY),
    )


def _default_socket_options() -> list[tuple[int, int, int]]:
    """TCP keepalive options matching the ones the Anthropic SDK installs."""
    options: list[tuple[int, int, int]] = [
        (socket.SOL_SOCKET, socket.SO_KEEPALIVE, True)
    ]
    # Not every knob exists on every platform.
    for name, value in (
        ("TCP_KEEPINTVL", 60),
        ("TCP_KEEPCNT", 5),
        ("TCP_KEEPIDLE", 60),
    ):
        option = getattr(socket, name, None)
        if isinstance(option, int):
            options.append((socket.IPPROTO_TCP, option, value))
    return options


async def _floor_connect_timeout(request: httpx.Request) -> None:
    """Stop a scalar SDK timeout from shortening the connect deadline.

    SDKs stamp their own per-request timeout over whatever the client was built
    with, and httpx expands a bare float to all four phases, so an overall
    budget such as `-M client_timeout=30` would become the connect deadline
    too. Only ever raises it, leaving a longer deadline and a `None` (no limit)
    alone.
    """
    extension = request.extensions.get("timeout")
    if not isinstance(extension, dict):
        return
    # Safe to mutate: httpx.Timeout.as_dict() builds this fresh per request.
    timeout: dict[str, float | None] = extension
    connect = timeout.get("connect")
    floor = connect_timeout()
    if connect is not None and connect < floor:
        timeout["connect"] = floor


def _transport_kwargs(
    limits: httpx.Limits, overrides: dict[str, Any]
) -> dict[str, Any]:
    """Settings httpx would apply itself if it were building the transport."""
    kwargs: dict[str, Any] = {
        "retries": _env_int(CONNECT_RETRIES_ENV, DEFAULT_CONNECT_RETRIES),
        "limits": limits,
        "socket_options": _default_socket_options(),
    }
    # httpx applies these only to a transport it builds itself, so a caller
    # passing verify=... would otherwise have it silently dropped.
    kwargs.update(
        {
            arg: overrides[arg]
            for arg in ("verify", "cert", "trust_env", "http1", "http2")
            if arg in overrides
        }
    )
    return kwargs


def default_client_kwargs(**overrides: Any) -> dict[str, Any]:
    """`httpx.AsyncClient` kwargs carrying these defaults; caller overrides win."""
    kwargs = dict(overrides)
    # `limits` resolves first because httpx applies `limits=` only to a
    # transport it builds itself, so the transport has to bake them in.
    limits = kwargs.setdefault("limits", default_limits())
    kwargs.setdefault("timeout", default_timeout())
    kwargs.setdefault("follow_redirects", True)

    if "transport" not in kwargs:
        transport_kwargs = _transport_kwargs(limits, kwargs)
        # Supplying a transport turns off httpx's environment proxy discovery,
        # so rebuild the mounts with the same settings rather than losing
        # either the proxy or the retry and keepalive options. httpx itself
        # gates that discovery on `trust_env`, so mirror that here rather than
        # rebuilding proxy mounts a caller explicitly asked us not to.
        environment_proxies = (
            _get_environment_proxies()
            if kwargs.get("trust_env", True) is not False
            else {}
        )
        mounts: dict[str, httpx.AsyncBaseTransport | None] = {
            key: None
            if url is None
            else httpx.AsyncHTTPTransport(proxy=httpx.Proxy(url), **transport_kwargs)
            for key, url in environment_proxies.items()
        }
        mounts.update(kwargs.get("mounts") or {})
        kwargs["mounts"] = mounts
        kwargs["transport"] = httpx.AsyncHTTPTransport(**transport_kwargs)

    hooks = dict(kwargs.get("event_hooks") or {})
    hooks["request"] = [_floor_connect_timeout, *hooks.get("request", [])]
    kwargs["event_hooks"] = hooks
    return kwargs


def default_async_client(**overrides: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(**default_client_kwargs(**overrides))
