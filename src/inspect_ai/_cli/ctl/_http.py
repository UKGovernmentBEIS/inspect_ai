"""Server discovery/targeting and the HTTP transport.

Busy narration, retry budgets, ``_request_json``, and the error-detail
helpers shared by every route caller.
"""

from __future__ import annotations

import functools
import random
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, NoReturn

import anyio
import httpx

from inspect_ai._control.discovery import DiscoveredControlServer

# Explicit re-export: this module is `list_discovered_servers`'s one canonical
# home inside the ctl package — every other module calls
# `_http.list_discovered_servers` so tests can intercept all consumers by
# patching `inspect_ai._cli.ctl._http.list_discovered_servers` alone.
from inspect_ai._control.discovery import (
    list_discovered_servers as list_discovered_servers,
)
from inspect_ai._util._async import configured_async_backend, tg_collect

from ._failure import _T, _CtlFailure, _ErrorKind, _exception_name, _fail
from ._group import _anomalies_pointer
from ._render import _echo


def _unreachable_failure(message: str, exc: "_ServerUnreachable") -> _CtlFailure:
    """The envelope failure for a terminal unreachable-server error.

    Busy (retry-exhausted timeouts) is its own kind — it means "alive but
    starved; retry shortly" where the transport kinds mean "gone" — carrying
    the last attempt's timeout class; other failures classify by their
    transport ``__cause__``.
    """
    if isinstance(exc, _ServerBusy):
        last = exc.last_timeout
        return _CtlFailure(
            "busy", message, exception=_exception_name(last) if last else None
        )
    cause = exc.__cause__
    return _CtlFailure.from_exception(
        message, cause if isinstance(cause, Exception) else exc
    )


def _resolve_target_server(pid: int | None) -> DiscoveredControlServer:
    """Pick the single process a ``keep`` / ``release`` targets, or exit.

    With a ``PID`` the matching process is used (error if none matches);
    without it, the sole running process is the default, and an ambiguous
    set (more than one) errors with the candidate pids. (Keep / release are
    idempotent, last-write-wins lifecycle toggles, so they get the
    sole-target default rather than requiring the selector outright.)
    """
    servers = list_discovered_servers()
    if not servers:
        _fail("not_found", "No running inspect processes found.")

    if pid is not None:
        matching = [s for s in servers if s.pid == pid]
        if not matching:
            _fail("not_found", f"No running inspect process with pid {pid}.")
        return matching[0]
    if len(servers) == 1:
        return servers[0]

    pids = ", ".join(str(s.pid) for s in servers)
    _fail(
        "ambiguous",
        f"Multiple inspect processes are running (pids: {pids}). "
        "Pass a PID to disambiguate (see `inspect ctl process`).",
    )


# The control server is embedded in the eval process and shares its event
# loop, which a busy eval can monopolize for several seconds at a time
# (large-transcript serialization, log flushes — see
# https://github.com/meridianlabs-ai/inspect_ai/issues/14). A perfectly
# healthy server can therefore miss a short read window, so reads use a
# generous timeout and retry a timeout several times before giving up, rather
# than silently reporting the eval as gone.
_REQUEST_TIMEOUT = 15.0
_REQUEST_ATTEMPTS = 8

# Default attempt budget for ``raise_on_busy`` reads (the pairing is resolved
# in `_get_response_with_retry`): enough to ride out a momentary stall without
# a fan-out spending the full `_REQUEST_ATTEMPTS * _REQUEST_TIMEOUT` (2 min)
# per eval hosted by one wedged process. A raise_on_busy caller that fails
# rather than degrades (the scoped samples read) overrides ``attempts``, as
# does the sole-server summaries fetch (one server is no fan-out).
_DEGRADED_READ_ATTEMPTS = 2

# Ceiling on a fan-out's in-flight reads (see `_collect_reads`). The reads are
# cheap and their cost is round-trip, so a wave of this size already collapses
# the wall clock of any realistic eval set to a couple of round-trips; raising
# it buys no time, because the server answering them shares the eval's single
# event loop and handles them one at a time whatever the client does. What it
# would buy is a wider blast radius: a fan-out spans *every* task in the run
# (completed ones included), so an uncapped one opens a connection per task
# into the process it is inspecting — and a client-side fd exhaustion is an
# OSError, which this module reads as "the eval has gone away".
_MAX_CONCURRENT_READS = 32

# A mutation (flush / buffer set) is issued once — it isn't idempotent, so it
# must not be retried — but it gets the same total wall-clock budget a retried
# read would consume (one attempt of `_REQUEST_ATTEMPTS * _REQUEST_TIMEOUT`, ie.
# 2 min) so a slow remote (eg. S3) write isn't cut short. That budget is the
# *read* leg; connect over the local UDS is effectively instant, so it's capped
# short rather than getting the full budget too.
_MUTATION_TIMEOUT = _REQUEST_ATTEMPTS * _REQUEST_TIMEOUT
_CONNECT_TIMEOUT = 10.0

# A bare 503 is the server's connection-limit backstop (uvicorn
# `limit_concurrency` — see `_MAX_CONCURRENT_CONNECTIONS` in
# `inspect_ai._control.server`): the request was rejected before any handler
# ran, so the process is alive but saturated — busy semantics ("retry
# shortly"), like a timeout, not unreachable. Unlike a timeout the rejection
# comes back instantly, so retries pause about this long (jittered, so a
# fan-out's rejected wave doesn't re-arrive in lockstep) rather than
# hammering a server that just said it's overloaded.
_REJECTED_RETRY_DELAY = 2.0

# The rejection's cause clause — shared by the per-attempt narration, both
# terminal errors, and the mutation failure so the wording can't drift.
_REJECTED_PROBLEM = "the server is at its concurrent-connection limit"

# The all-timeouts cause clause (the busy policy's default terminal wording).
_TIMEOUT_CAUSE = (
    f"every attempt timed out after {_REQUEST_TIMEOUT:.0f}s "
    "(the eval's event loop is busy)"
)


def _busy_cause(timeouts: int, rejections: int) -> str:
    """The cause clause for a retry-exhausted read's terminal error.

    Worded from what the attempts actually hit, so a mixed run (some
    timeouts, some connection-limit rejections) doesn't falsely claim a
    single cause — or a per-attempt duration — for all of them.
    """
    if rejections == 0:
        return _TIMEOUT_CAUSE
    if timeouts == 0:
        return _REJECTED_PROBLEM
    return (
        f"{timeouts} timed out and {rejections} hit the server's "
        "concurrent-connection limit"
    )


class _ServerUnreachable(Exception):
    """A control read failed for a non-timeout reason.

    Distinct from a timeout — which means the server is present but its loop is
    busy, and is worth retrying. This covers the non-retryable failures: a
    connection refused (the process has exited or never came up), a server-side
    ``500``, or a malformed response. Carries the originating error as
    ``__cause__`` (so callers can surface its detail); the caller decides
    whether to warn-and-skip (enumerating many servers) or fail (a single
    targeted read).
    """


class _ServerBusy(_ServerUnreachable):
    """A read exhausted its busy retries (opt-in — see ``raise_on_busy``).

    A subclass, so a caller's existing ``except _ServerUnreachable``
    warn-and-skip covers it; carries its message as the detail (there is no
    transport ``__cause__`` — every attempt timed out or was rejected).
    ``last_timeout`` records the last timed-out attempt's exception, if any
    attempt timed out, for the ``--json`` error envelope's ``exception``
    field (an attribute rather than ``__cause__``, whose presence would swap
    the human detail from the busy narration to the bare timeout string).
    ``busy_cause`` carries the composed :func:`_busy_cause` clause (a
    ``str``, named to avoid colliding with ``Exception.__cause__``) so a
    caller re-raising the terminal error (see :func:`_exit_busy`) words it
    from what the attempts actually hit.
    """

    def __init__(
        self,
        message: str,
        last_timeout: httpx.TimeoutException | None = None,
        busy_cause: str = _TIMEOUT_CAUSE,
    ) -> None:
        super().__init__(message)
        self.last_timeout = last_timeout
        self.busy_cause = busy_cause


class _BusyNarrator:
    """Narrates a fan-out's busy retries once per attempt, not once per target.

    A single read narrates each of its own timed-out attempts (progress
    feedback: the eval is busy, we're still trying). Concurrently that
    multiplies — the targets start together and every attempt costs the same
    timeout, so a wedged eval set produces one line per target per attempt.
    Sharing one narrator across a fan-out collapses each round to a single
    line, named for the fan-out (``what``) rather than for whichever target
    happened to get there first, which is not stable across backends.

    The dedup key includes the ``problem`` clause: 503 rejections pace
    differently from timeouts (2s vs 15s per attempt), so a fast-rejected
    target reaching an attempt number first must not silence a slower
    target's differently-caused narration for the same attempt.
    """

    def __init__(self, what: str) -> None:
        self._what = what
        self._narrated: set[tuple[int, str | None]] = set()

    def narrate(self, attempt: int, attempts: int, problem: str | None = None) -> None:
        if (attempt, problem) in self._narrated:
            return
        self._narrated.add((attempt, problem))
        _echo_busy_attempt(self._what, attempt, attempts, problem)


def _echo_busy_attempt(
    what: str, attempt: int, attempts: int, problem: str | None = None
) -> None:
    """Report one busy attempt (stderr, so ``--json`` stdout stays clean).

    ``problem`` is the attempt's failure clause — defaults to the timeout
    wording; a 503 rejection passes :data:`_REJECTED_PROBLEM`.
    """
    retrying = "; retrying…" if attempt < attempts else "."
    problem = problem or f"no response after {_REQUEST_TIMEOUT:.0f}s"
    _echo(
        f"{what}: {problem} "
        f"(attempt {attempt}/{attempts}) — the eval may be busy{retrying}",
        err=True,
    )


async def _get_response_with_retry_async(
    socket_path: str | Path,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    what: str,
    method: Literal["get", "post", "patch"] = "get",
    raise_on_busy: bool = False,
    attempts: int | None = None,
    pid: int | None = None,
    narrator: _BusyNarrator | None = None,
) -> httpx.Response:
    """Request ``path`` over the UDS, retrying a read timeout or a 503.

    Retries a read timeout up to ``attempts`` times, printing a status to the
    console (stderr, so ``--json`` stdout stays clean) on each — the eval is
    most likely just busy. A ``503`` — the server's connection-limit backstop,
    rejected before any handler ran (so retrying is safe even for the
    idempotent mutations that ride this path) — is retried the same way, but
    paced by :data:`_REJECTED_RETRY_DELAY` since it answers instantly.
    On exhaustion, raises :class:`_ServerBusy` when
    ``raise_on_busy`` is set — handing the caller the terminal outcome (a
    fan-out warns and skips the busy eval, a supplemental read degrades in
    place, a scoped read exits with a targeted error), along with its
    narration — otherwise prints an error and exits non-zero, with the
    :func:`_anomalies_pointer` escalation on stderr (scoped to ``pid`` when
    the caller knows the target process — pass it whenever it's at hand, so
    the pointer doesn't suggest scanning every process after a narration
    that named one).
    Raises :class:`_ServerUnreachable` for a non-timeout transport error
    (eg. a refused/reset connection) so the caller can skip or fail as
    appropriate.

    ``attempts`` defaults from ``raise_on_busy``: degradable reads get the
    smaller :data:`_DEGRADED_READ_ATTEMPTS` budget, exit-on-busy reads the
    full :data:`_REQUEST_ATTEMPTS`. Pass it explicitly to override — the
    scoped samples read raises on busy but keeps the full budget.

    ``method`` extends the retry policy to **idempotent** mutations only
    (keep/release's last-write-wins latches); a non-idempotent mutation must
    not be retried and takes the single-shot path in :func:`_request_json`.

    Returns the raw response without inspecting its status (except the 503
    consumed above, which no control endpoint returns itself), so callers
    that need to handle a meaningful status (eg. a 404) can;
    :func:`_get_with_retry_async` is the JSON-decoding wrapper for the common
    case.

    Async so a fan-out over many evals can issue its reads concurrently (see
    :func:`_read_all_task_rows` / :func:`_read_all_eval_samples`); single-read
    call sites use the :func:`_get_response_with_retry` sync facade. A fan-out
    passes a shared ``narrator`` so the retry narration below reports each
    attempt once for the invocation rather than once per target (see
    :class:`_BusyNarrator`).
    """
    if attempts is None:
        attempts = _DEGRADED_READ_ATTEMPTS if raise_on_busy else _REQUEST_ATTEMPTS
    if narrator is None:
        # a private narrator: a single read's attempt numbers never repeat,
        # so its dedup can't fire — this is exactly per-attempt narration
        narrator = _BusyNarrator(what)
    transport = httpx.AsyncHTTPTransport(uds=str(socket_path))
    last_timeout: httpx.TimeoutException | None = None
    timeouts = 0
    rejections = 0
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://localhost",
                timeout=_REQUEST_TIMEOUT,
            ) as client:
                response = await client.request(method, path, params=params or {})
        except httpx.TimeoutException as exc:
            last_timeout = exc
            timeouts += 1
            narrator.narrate(attempt, attempts)
            continue
        except (httpx.HTTPError, OSError) as exc:
            raise _ServerUnreachable() from exc
        if response.status_code != 503 or not _rejection_503(response):
            return response
        # a capacity rejection — retry like a timeout, jitter-paced (see
        # _REJECTED_RETRY_DELAY)
        rejections += 1
        narrator.narrate(attempt, attempts, _REJECTED_PROBLEM)
        if attempt < attempts:
            await anyio.sleep(_REJECTED_RETRY_DELAY * (0.5 + random.random()))
    busy_cause = _busy_cause(timeouts, rejections)
    if raise_on_busy:
        raise _ServerBusy(
            f"gave up after {attempts} attempts — {busy_cause}",
            last_timeout=last_timeout,
            busy_cause=busy_cause,
        )
    _exit_busy(
        what, attempts, last_timeout=last_timeout, pid=pid, busy_cause=busy_cause
    )


def _exit_busy(
    what: str,
    attempts: int,
    *,
    last_timeout: httpx.TimeoutException | None,
    pid: int | None,
    busy_cause: str = _TIMEOUT_CAUSE,
) -> NoReturn:
    """Narrate a read that stayed busy through its retries, and fail the command.

    The terminal half of the busy policy, split out so a fan-out can raise it
    **once** for the whole invocation: its per-target reads take the
    ``raise_on_busy`` path (which doesn't narrate), so a run where every
    process is wedged reports one failure naming one pid, rather than one per
    process — the reads are concurrent, so without this they would all reach
    their deadline together and each print its own terminal error.

    ``busy_cause`` is the :func:`_busy_cause` clause naming what the attempts
    actually hit (timeouts, connection-limit rejections, or both).
    """
    message = (
        f"{what}: gave up after {attempts} attempts — {busy_cause}; try again shortly."
    )
    _echo(message, err=True)
    _echo(f"{_anomalies_pointer(pid)}.", err=True)
    raise _CtlFailure(
        "busy",
        message,
        exception=_exception_name(last_timeout) if last_timeout else None,
    )


def _run_async(func: Callable[[], Awaitable[_T]]) -> _T:
    """Run one control-channel coroutine to completion from sync CLI code.

    The ctl commands are synchronous click callbacks, so every async read
    bottoms out here. Never call this (or the sync facades built on it) from
    async code — it starts its own event loop; a fan-out awaits the ``_async``
    form directly instead.
    """
    return anyio.run(func, backend=configured_async_backend())


async def _collect_reads(reads: list[Callable[[], Awaitable[_T]]]) -> list[_T]:
    """Run a fan-out's reads concurrently, in input order, capped in flight.

    The cap (:data:`_MAX_CONCURRENT_READS`) is what keeps "issue the reads
    together" from meaning "issue all of them at once" — see the constant for
    why the ceiling costs nothing and the absence of one does.
    """
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_READS)

    async def limited(read: Callable[[], Awaitable[_T]]) -> _T:
        async with limiter:
            return await read()

    return await tg_collect([functools.partial(limited, read) for read in reads])


def _get_response_with_retry(
    socket_path: str | Path,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    what: str,
    method: Literal["get", "post", "patch"] = "get",
    raise_on_busy: bool = False,
    attempts: int | None = None,
    pid: int | None = None,
) -> httpx.Response:
    """Sync facade over :func:`_get_response_with_retry_async` — see it for policy."""
    return _run_async(
        functools.partial(
            _get_response_with_retry_async,
            socket_path,
            path,
            params=params,
            what=what,
            method=method,
            raise_on_busy=raise_on_busy,
            attempts=attempts,
            pid=pid,
        )
    )


async def _get_with_retry_async(
    socket_path: str | Path,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    what: str,
    raise_on_busy: bool = False,
    attempts: int | None = None,
    pid: int | None = None,
    narrator: _BusyNarrator | None = None,
) -> Any:
    """GET ``path`` and return its decoded JSON, retrying a busy eval on timeout.

    Wraps :func:`_get_response_with_retry_async` (``raise_on_busy``,
    ``attempts``, ``pid``, and ``narrator`` ride through, including the
    attempts-from-raise_on_busy default); a non-2xx status or undecodable body
    raises :class:`_ServerUnreachable` (a server-side ``500`` or malformed
    response is not retryable). For endpoints with a meaningful 4xx, call
    :func:`_get_response_with_retry_async` directly and inspect the status.
    """
    response = await _get_response_with_retry_async(
        socket_path,
        path,
        params=params,
        what=what,
        raise_on_busy=raise_on_busy,
        attempts=attempts,
        pid=pid,
        narrator=narrator,
    )
    try:
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise _ServerUnreachable() from exc


def _unreachable_detail(exc: _ServerUnreachable) -> str:
    """Human-readable cause of an unreachable-server error."""
    cause = exc.__cause__
    return _error_detail(cause) if isinstance(cause, Exception) else str(exc)


def _request_json(
    socket_path: str,
    path: str,
    *,
    what: str,
    not_found: str,
    not_found_missing_route: str | None = None,
    params: dict[str, Any] | None = None,
    mutate: Literal["post", "patch"] | None = None,
    retry_mutation: bool = False,
    pid: int | None = None,
    echo_failures: bool = True,
) -> dict[str, Any]:
    """GET (retrying a busy process) or mutate ``path``; return its JSON dict.

    The shared transport / error policy for the per-eval and per-task ctl
    commands. A read goes through :func:`_get_response_with_retry`; a mutation
    isn't idempotent across transport failures, so it gets a single attempt
    with the full mutation budget (see :data:`_MUTATION_TIMEOUT` — eg. a
    remote S3 log flush can take a while) — EXCEPT when the caller marks it
    ``retry_mutation`` (an idempotent last-write-wins latch like
    keep/release), which rides the narrated retrying policy instead of one
    silent long wait. A 404 prints ``not_found`` and exits non-zero; a 400
    surfaces the server's ``{"error": ...}`` body; a 503 (the server's
    connection-limit backstop — only reachable here on the single-shot
    mutation path, since reads retry it) exits as ``busy``; transport errors
    exit with ``what`` as context.

    ``not_found_missing_route`` splits the 404 by origin (see
    :func:`_handler_404`): a router 404 — the endpoint doesn't exist, so the
    process is running an older inspect — prints it instead of ``not_found``,
    which then only ever means the endpoint answered "entity not found".
    Without it every 404 prints ``not_found``, which must therefore hedge
    both meanings; new endpoints should pass it rather than hedge.

    ``pid`` scopes the retry-exhaustion escalation pointer to the target
    process (see :func:`_get_response_with_retry`) — pass it when the caller
    has already resolved one.

    ``echo_failures=False`` suppresses the stderr echo that normally precedes
    each raised :class:`_CtlFailure` — for callers that catch the failure and
    render it themselves (the bulk-requeue sweep records per-sample
    rejections in its stdout report; echoing here too would print every
    rejection twice). Such callers take over the raiser-echoes contract: any
    failure they re-raise instead of recording must be echoed first.
    """
    verb = "update" if mutate else "read"

    def fail(
        kind: _ErrorKind,
        message: str,
        *,
        status: int | None = None,
        missing_route: bool = False,
    ) -> NoReturn:
        if echo_failures:
            _echo(message, err=True)
        raise _CtlFailure(kind, message, status=status, missing_route=missing_route)

    try:
        if mutate is not None and retry_mutation:
            response = _get_response_with_retry(
                socket_path,
                path,
                params=params,
                what=f"Updating {what}",
                method=mutate,
                pid=pid,
            )
        elif mutate is not None:
            transport = httpx.HTTPTransport(uds=str(socket_path))
            with httpx.Client(
                transport=transport,
                base_url="http://localhost",
                timeout=httpx.Timeout(_MUTATION_TIMEOUT, connect=_CONNECT_TIMEOUT),
            ) as client:
                if mutate == "post":
                    response = client.post(path, params=params)
                else:
                    response = client.patch(path, params=params)
        else:
            response = _get_response_with_retry(
                socket_path, path, params=params, what=f"Reading {what}", pid=pid
            )
        if response.status_code == 404:
            if not_found_missing_route is not None and not _handler_404(response):
                fail(
                    "not_found",
                    not_found_missing_route,
                    status=404,
                    missing_route=True,
                )
            fail("not_found", not_found, status=404)
        if response.status_code == 400:
            fail(
                "invalid_request",
                f"Invalid request: {_error_detail_from_response(response)}",
                status=400,
            )
        if response.status_code == 503 and _rejection_503(response):
            # only the single-shot mutation path sees this (reads retry it);
            # the rejection precedes the handler, so the mutation was NOT
            # applied and retrying it by hand is safe
            fail(
                "busy",
                f"{_failure_prefix(verb, what)}{_REJECTED_PROBLEM}; try again shortly.",
                status=503,
            )
        response.raise_for_status()
        result = response.json()
    except _ServerUnreachable as exc:
        message = f"{_failure_prefix(verb, what)}{_unreachable_detail(exc)}"
        if echo_failures:
            _echo(message, err=True)
        raise _unreachable_failure(message, exc) from exc
    except (httpx.HTTPError, OSError, ValueError) as exc:
        message = f"{_failure_prefix(verb, what)}{_error_detail(exc)}"
        if echo_failures:
            _echo(message, err=True)
        raise _CtlFailure.from_exception(message, exc) from exc
    return result if isinstance(result, dict) else {}


def _failure_prefix(verb: str, what: str) -> str:
    """The context prefix :func:`_request_json` puts on failure messages.

    The bulk-requeue human rendering strips this prefix from recorded
    per-sample errors (the label it restates is already on the line), so the
    format lives here rather than inline to keep the two sides in lockstep.
    """
    return f"Failed to {verb} {what}: "


def _handler_404(response: httpx.Response) -> bool:
    """Whether a 404 came from an endpoint handler rather than the router.

    Handler 404s ("entity not found") always carry an ``{"error": ...}`` JSON
    body — a control-server convention pinned by a test — while the router's
    404 for a path with no route (a process running an older inspect without
    the endpoint) is FastAPI's stock ``{"detail": "Not Found"}``. Reading the
    distinction off the response beats gating on a version table: it needs no
    per-endpoint bookkeeping and is accurate against servers that predate
    version reporting entirely. Unparseable bodies count as router 404s —
    misreporting a weird handler 404 as version skew still names a true
    remedy (restart on current inspect), whereas the opposite error would
    tell the user their task finished when it didn't.
    """
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and "error" in body


def _rejection_503(response: httpx.Response) -> bool:
    """Whether a 503 is the server's connection-limit rejection.

    uvicorn's ``limit_concurrency`` backstop answers a fixed plain-text 503
    before any handler runs — never a JSON dict. So unlike :func:`_handler_404`
    (where both sides are dicts and only the ``{"error": ...}`` convention
    discriminates), any dict body here — the ``{"error": ...}`` convention or
    e.g. FastAPI's stock ``{"detail": ...}`` from ``HTTPException`` — must be
    a handler 503: pass it through to the caller rather than consuming it as
    a capacity rejection. No control endpoint returns 503 today, so this is
    purely a forward-looking guard.
    """
    try:
        body = response.json()
    except ValueError:
        return True
    return not isinstance(body, dict)


def _error_body(response: httpx.Response) -> str | None:
    """The server's ``{"error": ...}`` body detail, or ``None`` when absent."""
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict) and body.get("error"):
        return str(body["error"])
    return None


def _error_detail_from_response(response: httpx.Response) -> str:
    """Prefer the server's ``{"error": ...}`` body over a bare status message."""
    return _error_body(response) or f"HTTP {response.status_code}"


def _error_detail(exc: Exception) -> str:
    """Prefer the server's ``{"error": ...}`` body over the bare HTTP error."""
    response = getattr(exc, "response", None)
    if isinstance(response, httpx.Response):
        detail = _error_body(response)
        if detail is not None:
            return detail
    return str(exc)
