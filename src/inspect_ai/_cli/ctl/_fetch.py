"""Per-resource reads/writes over the HTTP transport.

Summaries, samples/events/messages/store fetches, log-flush POST, and
target-eval resolution.
"""

from __future__ import annotations

import functools
import time
from typing import Any, Literal, NamedTuple, NoReturn

import httpx

from inspect_ai._control.discovery import DiscoveredControlServer
from inspect_ai._util.name_match import match_name_prefix

# Patch seam: tests monkeypatch functions on their defining module
# (e.g. `inspect_ai._cli.ctl._http._request_json`), so cross-module
# calls must resolve through the module object at call time — do not
# "simplify" to `from ._http import _request_json` (see
# design/ctl/cli-refactor.md).
from . import _http
from ._failure import _CtlFailure, _fail
from ._group import _anomalies_pointer, _busy_note, _busy_pids_label, _exit_all_busy
from ._http import (
    _DEGRADED_READ_ATTEMPTS,
    _REQUEST_ATTEMPTS,
    _BusyNarrator,
    _collect_reads,
    _exit_busy,
    _run_async,
    _ServerBusy,
    _ServerUnreachable,
    _unreachable_detail,
    _unreachable_failure,
)
from ._render import _SHORT_ID_LEN, _echo, _render_table, _short_id


class _FetchedSummaries(NamedTuple):
    """Result of :func:`_fetch_summaries`.

    ``busy_pids`` names the processes warned-and-skipped as busy (only
    populated under ``raise_on_busy``) so callers can report them instead of
    claiming nothing is running — an alive-but-busy eval must never be
    indistinguishable from no eval at all.
    """

    summaries: list[dict[str, Any]]
    busy_pids: list[int]


def _fetch_summaries(
    servers: list[DiscoveredControlServer],
    *,
    raise_on_busy: bool = False,
    stop_on_task_id: str | None = None,
) -> _FetchedSummaries:
    """Query each discovered control server for its eval summary.

    Each read retries on timeout; a server that stays busy through the retries
    fails the command by default (``task list`` is the discovery surface — an
    alive eval silently absent from its ``--json`` output has no in-band
    caveat channel), but with ``raise_on_busy`` it is warned-and-skipped like
    an unreachable one, on the smaller degraded budget, and recorded in
    ``busy_pids`` — for the sample commands, where the other processes' rows
    are still worth showing and the skip must surface in any terminal error.
    A sole discovered server rides the full budget even then: the degraded
    budget protects a fan-out from an unrelated wedged process, and a single
    server is no fan-out.
    A server that can't be reached for a non-timeout reason raises
    :class:`_ServerUnreachable`; we warn and skip it (rather than fail the
    whole listing) but the warning is surfaced rather than swallowed: the most
    common cause is a process that just exited between discovery and connect,
    but the same path also catches a server-side ``500`` or a malformed
    response, which the user should see.

    ``stop_on_task_id`` short-circuits the fan-out: once a server's rows
    contain that exact task id, the remaining servers are not contacted.
    Safe only for an exact *full* id — it wins resolution outright (see
    :func:`_resolve_target_eval`), so the skipped servers could neither add
    candidates nor create ambiguity; a prefix or name query never equals a
    full id, so it still sees every server. A ``--model`` narrowing that
    contradicts the exact id's row errors not-found over the short-circuited
    (partial) summary set, which stays sound: task ids are stable across
    retries of the same task × model row, so a duplicate-id row on a skipped
    server carries the same model and could not have matched either. Discovery is newest-first, so
    only siblings started before the target are skipped, and the
    duplicate-id corner (an old kept-alive attempt a newer process is
    retrying) resolves to the newest attempt.

    Without ``stop_on_task_id`` the reads run concurrently (see
    :func:`_read_all_task_rows`); rows, and the skip warnings below, still
    follow discovery order.
    """
    # Every read takes the raise_on_busy path so none of them narrates its own
    # terminal error; when the caller wanted exit-on-busy, the first busy
    # server in discovery order raises for the whole invocation below.
    attempts = (
        _REQUEST_ATTEMPTS
        # a sole server is no fan-out — there's no wedged sibling to protect
        # against, so ride out a stall on the full budget
        if not raise_on_busy or len(servers) == 1
        else _DEGRADED_READ_ATTEMPTS
    )
    reads = _run_async(
        functools.partial(
            _read_all_task_rows,
            servers,
            attempts=attempts,
            stop_on_task_id=stop_on_task_id,
        )
    )
    summaries: list[dict[str, Any]] = []
    busy_pids: list[int] = []
    for server, rows in reads:
        if isinstance(rows, _ServerUnreachable):
            # a 404 means the process is serving a control API without this
            # route — version skew between the CLI and the eval process —
            # where transport errors mean the process is gone
            cause = rows.__cause__
            if isinstance(rows, _ServerBusy):
                if not raise_on_busy:
                    _exit_busy(
                        f"Reading tasks from pid {server.pid}",
                        attempts,
                        last_timeout=rows.last_timeout,
                        pid=server.pid,
                        busy_cause=rows.busy_cause,
                    )
                busy_pids.append(server.pid)
                hint = f"try again shortly, or {_anomalies_pointer(server.pid)}"
            elif (
                isinstance(cause, httpx.HTTPStatusError)
                and cause.response.status_code == 404
            ):
                hint = "it may be running a different inspect version than this CLI"
            else:
                hint = "it may have just exited"
            _echo(
                f"Skipping pid {server.pid}: its control endpoint could not be "
                f"read ({_unreachable_detail(rows)}) — {hint}.",
                err=True,
            )
            continue
        # Decorate each row with discovery-side info the server doesn't see
        # (pid, socket_path).
        for row in rows:
            row["pid"] = server.pid
            row["socket_path"] = str(server.socket_path)
        summaries.extend(rows)
    return _FetchedSummaries(summaries=summaries, busy_pids=busy_pids)


class _ServerRead(NamedTuple):
    """One server's ``/tasks`` read outcome (see :func:`_read_task_rows`).

    ``rows`` is the decoded payload, or the :class:`_ServerUnreachable` that
    replaced it — captured rather than raised because the reads run
    concurrently, and an exception escaping into the task group would cancel
    its siblings where the policy is per-server warn-and-skip. A payload that
    isn't a list (a malformed server) is normalized to no rows, which is how
    it was already treated.
    """

    server: DiscoveredControlServer
    rows: list[dict[str, Any]] | _ServerUnreachable


async def _read_task_rows(
    server: DiscoveredControlServer,
    *,
    attempts: int,
    narrator: _BusyNarrator | None,
) -> _ServerRead:
    """Read one server's ``/tasks`` rows, capturing an unreachable/busy failure."""
    try:
        rows = await _http._get_with_retry_async(
            server.socket_path,
            "/tasks",
            what=f"Reading tasks from pid {server.pid}",
            raise_on_busy=True,
            attempts=attempts,
            pid=server.pid,
            narrator=narrator,
        )
    except _ServerUnreachable as exc:
        return _ServerRead(server, exc)
    return _ServerRead(server, rows if isinstance(rows, list) else [])


async def _read_all_task_rows(
    servers: list[DiscoveredControlServer],
    *,
    attempts: int,
    stop_on_task_id: str | None,
) -> list[_ServerRead]:
    """Read every discovered server's ``/tasks`` rows, in discovery order.

    Concurrently by default: the per-read cost is dominated by round-trip and
    connection setup rather than server work, so a serial loop cost that
    round-trip once per process and made an unscoped listing over a large
    eval set look wedged.
    """
    read = functools.partial(
        _read_task_rows,
        attempts=attempts,
        # concurrent reads stall in lockstep, so they share one narrator; the
        # serial branch below narrates per server, as a lone read does
        narrator=_BusyNarrator(f"Reading tasks from {len(servers)} processes")
        if stop_on_task_id is None and len(servers) > 1
        else None,
    )
    if stop_on_task_id is None:
        return await _collect_reads(
            [functools.partial(read, server) for server in servers]
        )
    # The short-circuit decides whether to contact the next server from the
    # last one's rows, so it stays serial. It runs for any scoped (single-task)
    # selector — whether a query is the exact id that can actually stop early
    # is only knowable from the rows — so a name or prefix selector pays the
    # serial cost for a stop that never comes. Kept because contacting the
    # servers an exact id skips could make that read *slower*, by waiting out
    # an unrelated wedged process's retry budget.
    reads: list[_ServerRead] = []
    for server in servers:
        result = await read(server)
        reads.append(result)
        if not isinstance(result.rows, _ServerUnreachable) and any(
            row.get("task_id") == stop_on_task_id for row in result.rows
        ):
            break
    return reads


def _fetch_sample_summaries(task_query: str | None = None) -> _FetchedSummaries:
    """Fetch the discovered summaries for a sample command.

    Busy processes are warned-and-skipped (``raise_on_busy``) so one wedged
    sibling can't kill the read — but if that leaves *nothing* (every
    process alive yet busy), exit non-zero via :func:`_exit_all_busy`: an
    alive-but-busy eval must never be indistinguishable from no eval at all.
    ``busy_pids`` rides the return for scoped resolution's caveats.

    ``task_query`` is the command's TASK selector; an exact full task id
    stops the fan-out at the server holding it (see ``stop_on_task_id`` on
    :func:`_fetch_summaries`).
    """
    fetched = _fetch_summaries(
        _http.list_discovered_servers(),
        raise_on_busy=True,
        stop_on_task_id=task_query,
    )
    if not fetched.summaries and fetched.busy_pids:
        _exit_all_busy(fetched.busy_pids)
    return fetched


def _resolve_target_eval(
    summaries: list[dict[str, Any]],
    query: str,
    *,
    busy_pids: list[int] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Pick the task a per-eval command targets, or exit with an error.

    ``query`` matches a task id first (full, then unique prefix — ``task
    list`` shows truncated ids; ids are stable across retries), then falls
    back to the task name (see :func:`_match_by_task_name`). ``model`` — the
    disambiguator for one task run against several models, where the name
    alone matches every row — filters *within* the rows ``query`` matches
    (see :func:`_match_by_model`), never before resolution: it can't change
    which rows the selector denotes, so an unrelated task running the
    exact-named model can neither veto a prefix match on the selected task
    (exact-wins competes only within the candidates) nor re-route the
    selector to a different task. An exact-id ``query`` whose row runs a
    non-matching model errors by naming the contradiction rather than with
    a global "no task with that model" claim: an exact id short-circuits
    the summaries fan-out at its server, so a skipped process could be
    running a matching model and the global claim would be false about it
    (the refusal itself is sound — duplicate-id rows share the model, so a
    skipped row could not resolve the id either). ``busy_pids``
    (from the summaries fetch) qualifies the resolution against partial
    discovery: a not-found error and the ambiguity table note that the busy
    process may hold further candidates, and a successful match carries a
    stderr caveat that it was matched among responsive processes only —
    unless it is an exact id or a prefix of at least the truncated display
    length (:data:`_SHORT_ID_LEN`), which cannot name a different task.
    Name matches always caveat: same-named tasks across processes are the
    norm (one task, several models), and a shorter hand-typed id prefix
    could collide with a task on the busy process.
    """
    qualifier = _model_qualifier(model)
    exact = [s for s in summaries if s.get("task_id") == query]
    id_matches = exact or [
        s for s in summaries if str(s.get("task_id", "")).startswith(query)
    ]
    matches = id_matches or _match_by_task_name(summaries, query)
    if matches and model is not None:
        narrowed = _match_by_model(matches, model)
        if not narrowed and exact:
            _fail(
                "not_found",
                f"Task '{query}' is running model "
                f"'{exact[0].get('model')}', which does not match "
                f"'{model}'.",
            )
        matches = narrowed
    if not matches:
        busy = (
            f" among responsive processes; {_busy_note(busy_pids)}" if busy_pids else ""
        )
        _fail("not_found", f"No running task matching '{query}'{qualifier}{busy}.")
    if len(matches) > 1:
        if busy_pids:
            _echo(
                f"note: {_busy_pids_label(busy_pids)} busy-skipped — candidates "
                "drawn from responsive processes only.",
                err=True,
            )
        _exit_ambiguous(matches, f"'{query}' matches multiple tasks{qualifier}")
    match = matches[0]
    # exact ids are unique; a >= _SHORT_ID_LEN prefix is the truncated
    # task-list paste (see the docstring for the caveat rationale)
    provably_unique = bool(exact) or (bool(id_matches) and len(query) >= _SHORT_ID_LEN)
    if busy_pids and not provably_unique:
        _echo(
            f"note: {_busy_pids_label(busy_pids)} busy-skipped — matched "
            f"'{query}' among responsive processes only.",
            err=True,
        )
    return match


def _match_by_task_name(
    summaries: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """Match summaries by task name, anchored at the name start or after a ``/``.

    So ``gpqa`` matches ``inspect_evals/gpqa_diamond`` (leaf prefix) but
    not ``failing_gpqa_diamond`` (mid-name). An exact name/leaf match wins
    over prefix matches, so ``gpqa`` resolves cleanly even when both
    ``gpqa`` and ``gpqa_diamond`` are running. (The same selector rule
    resolves model names in ``ctl config --model`` — see `match_name_prefix`.)
    """
    return match_name_prefix(summaries, query, lambda s: str(s.get("task", "")))


def _match_by_model(
    summaries: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """Match summaries by model name — the ``--model`` disambiguator's rule.

    The same anchored-prefix, exact-wins rule as task names and ``ctl config
    --model`` (see `match_name_prefix`): ``gpt-5`` matches ``openai/gpt-5``,
    and resolves cleanly even when ``openai/gpt-5-mini`` is also running.
    """
    return match_name_prefix(summaries, query, lambda s: str(s.get("model", "")))


def _narrow_by_model(
    summaries: list[dict[str, Any]],
    model: str,
    *,
    busy_pids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Narrow summaries to tasks running a matching model, or exit not-found.

    The ``TASK``-less half of the ``--model`` option, where the model is the
    only selector: the no-``TASK`` defaults and the sample fan-out resolve
    over the narrowed rows. With a ``TASK``, model filtering instead happens
    within the selector's matches (see :func:`_resolve_target_eval`), so the
    global not-found claim here is made only when the whole summary set was
    consulted.
    """
    matches = _match_by_model(summaries, model)
    if not matches:
        busy = (
            f" among responsive processes; {_busy_note(busy_pids)}" if busy_pids else ""
        )
        _fail("not_found", f"No running task with a model matching '{model}'{busy}.")
    return matches


def _model_qualifier(model: str | None) -> str:
    """The `` with model matching '...'`` clause the ``--model`` errors carry."""
    return f" with model matching '{model}'" if model is not None else ""


def _exit_ambiguous(matches: list[dict[str, Any]], prefix: str) -> NoReturn:
    """Echo an ambiguity error with a candidate table and exit.

    The same columns `ctl task list` leads with, so same-named tasks (one
    task against several models, or one model across solvers) are still
    tellable apart — an inline `id (name)` listing can't disambiguate those.
    The solver column appears only when a candidate carries one (mirroring
    the task list), and a pid column only when the candidates span more than
    one process (the common case is one). The envelope failure folds the
    candidate ids into its message instead — the table is stderr-only.
    """
    _echo(f"{prefix} — pass a task id to choose one:\n", err=True)
    multi_process = len({s.get("pid") for s in matches}) > 1
    any_solver = any(s.get("solver") for s in matches)
    headers = (
        ("task id", "task", "model")
        + (("solver",) if any_solver else ())
        + ("status",)
        + (("pid",) if multi_process else ())
    )
    rows = [
        (
            _short_id(str(s.get("task_id") or "")),
            str(s.get("task") or "?"),
            str(s.get("model") or ""),
        )
        + ((str(s.get("solver") or ""),) if any_solver else ())
        + (str(s.get("status") or ""),)
        + ((str(s.get("pid") or ""),) if multi_process else ())
        for s in matches
    ]
    _render_table(headers, rows, err=True)
    ids = ", ".join(_short_id(str(s.get("task_id") or "")) for s in matches)
    raise _CtlFailure(
        "ambiguous",
        f"{prefix} — pass a task id to choose one (candidates: {ids}).",
    )


def _exit_samples_unreachable(
    eval_id: str, exc: _ServerUnreachable, *, pid: int | None = None
) -> NoReturn:
    """Echo a samples-read failure for ``eval_id`` and exit non-zero.

    A busy failure adds the :func:`_anomalies_pointer` escalation (``pid``
    names the busy process) on stderr only — the envelope message stays
    hint-free.
    """
    # the period rides the hint: a non-busy detail is a raw transport error
    # string (multi-line, may end in a URL) that punctuation would corrupt
    hint = "; try again shortly." if isinstance(exc, _ServerBusy) else ""
    message = (
        f"Failed to read samples for eval {eval_id}: {_unreachable_detail(exc)}{hint}"
    )
    _echo(message, err=True)
    if isinstance(exc, _ServerBusy):
        _echo(f"{_anomalies_pointer(pid)}.", err=True)
    raise _unreachable_failure(message, exc) from exc


class _SamplesPage(NamedTuple):
    """One eval's samples read (see :func:`_fetch_samples`).

    ``counts`` is the eval's status histogram (complete even when the rows
    are filtered or capped); ``None`` from an older server whose envelope
    doesn't carry it. ``truncated`` reports whether the server's row cap
    dropped rows.
    """

    as_of: float
    samples: list[dict[str, Any]]
    counts: dict[str, int] | None = None
    truncated: bool = False


async def _fetch_samples_async(
    socket_path: str,
    eval_id: str,
    active_since: float | None = None,
    *,
    sample_filter: Literal["errors"] | None = None,
    status: str | None = None,
    limit: int | None = None,
    all_samples: bool = False,
    content: bool = False,
    attempts: int | None = None,
    narrator: _BusyNarrator | None = None,
) -> _SamplesPage:
    """Query one control server for an eval's samples.

    Returns the server's ``{as_of, counts, samples, truncated}`` envelope —
    ``as_of`` is stamped server-side before the listing is built, so feeding
    it back as the next ``active_since`` can't miss changes that landed
    during the read; ``counts`` is the whole eval's status histogram and
    ``truncated`` reports a hit row cap. With ``active_since`` (unix ts),
    restricts to samples started or updated since then — the recency delta.
    ``status`` (comma-separated) filters by status; the rows are capped
    server-side (at ``limit`` when given, the server default otherwise)
    unless ``all_samples`` asks for the full listing. Tolerates an older
    server's bare array or histogram-less envelope (stamping ``as_of``
    client-side, pre-request, and leaving ``counts`` to the caller).

    ``sample_filter="errors"`` (sent as ``filter=errors`` on the wire) asks
    the server to return only errored/retried samples (skipping its
    pending-row synthesis — the whole dataset × epochs grid on a large
    eval). The result is trusted as-filtered — no client-side fallback.
    Skew with a server from an older install is not defended (the server
    runs locally from the same install as the CLI in all but
    upgraded-mid-eval cases).

    Raises :class:`_ServerUnreachable` on a non-retryable read failure and
    :class:`_ServerBusy` when the eval stays busy through ``attempts``
    retries (defaulting to the degraded budget — see
    :func:`_get_response_with_retry_async`); the caller owns the outcome:
    warn-and-skip (an unscoped fan-out over many evals), fail the command
    (a single targeted read, which passes the full budget), or degrade in
    place (``sample show``'s old-server fallback listing read, which keeps
    the default budget and drops only the summary fields).
    """
    fallback_as_of = time.time()
    params: dict[str, Any] = {}
    if active_since is not None:
        params["active_since"] = active_since
    if sample_filter is not None:
        params["filter"] = sample_filter
    if status is not None:
        params["status"] = status
    if all_samples:
        params["all"] = True
    elif limit is not None:
        params["limit"] = limit
    if content:
        params["content"] = True
    page = await _http._get_with_retry_async(
        socket_path,
        f"/evals/{eval_id}/samples",
        params=params,
        what=f"Reading samples for eval {eval_id}",
        raise_on_busy=True,
        attempts=attempts,
        narrator=narrator,
    )
    if isinstance(page, dict):
        samples = page.get("samples")
        as_of = page.get("as_of")
        counts = page.get("counts")
        return _SamplesPage(
            as_of=float(as_of) if isinstance(as_of, (int, float)) else fallback_as_of,
            samples=samples if isinstance(samples, list) else [],
            counts=counts if isinstance(counts, dict) else None,
            truncated=bool(page.get("truncated", False)),
        )
    return _SamplesPage(
        as_of=fallback_as_of, samples=page if isinstance(page, list) else []
    )


def _fetch_samples(
    socket_path: str,
    eval_id: str,
    active_since: float | None = None,
    *,
    sample_filter: Literal["errors"] | None = None,
    status: str | None = None,
    limit: int | None = None,
    all_samples: bool = False,
    content: bool = False,
    attempts: int | None = None,
) -> _SamplesPage:
    """Sync facade over :func:`_fetch_samples_async` — see it for policy."""
    return _run_async(
        functools.partial(
            _fetch_samples_async,
            socket_path,
            eval_id,
            active_since,
            sample_filter=sample_filter,
            status=status,
            limit=limit,
            all_samples=all_samples,
            content=content,
            attempts=attempts,
        )
    )


def _fetch_sample_detail(
    socket_path: str,
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    content: bool = False,
    pid: int | None = None,
) -> dict[str, Any]:
    """Query one control server for a single sample's summary + error detail.

    The one read behind ``sample show`` — the response carries the summary
    fields (timing / tokens / messages) alongside the error history, so no
    supplemental listing fetch is needed. ``content`` opts into the error
    free text (withheld by default). It rides the full narrated
    busy-retry policy rather than failing on a momentary event-loop stall;
    ``pid`` scopes that policy's exhaustion pointer to the hosting process.
    """
    # sample_id goes in the query string (httpx URL-encodes it) so ids
    # containing `/`, `?`, `#`, etc. address correctly — they can't be
    # carried as a path segment.
    return _http._request_json(
        socket_path,
        f"/evals/{eval_id}/sample",
        params={"sample_id": sample_id, "epoch": epoch, "content": content},
        what=f"sample {sample_id}",
        not_found=(
            f"Sample '{sample_id}' (epoch {epoch}) not found — it may "
            "still be running or not yet written to the log."
        ),
        pid=pid,
    )


def _fetch_sample_events(
    socket_path: str,
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    cursor: str | None,
    tail: int | None,
    limit: int | None,
    types: str | None,
    content: bool,
    full: bool,
    since_time: float | None,
    until: float | None,
    pid: int | None = None,
) -> dict[str, Any]:
    """Query one control server for a page of a sample's transcript events.

    The authoritative read behind ``sample events``: like the sample detail
    read, it rides the full narrated busy-retry policy rather than failing on
    a momentary event-loop stall; ``pid`` scopes that policy's exhaustion
    pointer to the hosting process.
    """
    # sample_id (and all params) go in the query string so reserved-char ids
    # address correctly; drop unset options so server defaults apply. The
    # wire parameter for the cursor is `since` (the CLI flag is --cursor).
    params: dict[str, Any] = {
        "sample_id": sample_id,
        "epoch": epoch,
        "content": content,
        "full": full,
    }
    if cursor is not None:
        params["since"] = cursor
    if tail is not None:
        params["tail"] = tail
    if limit is not None:
        params["limit"] = limit
    if types is not None:
        params["type"] = types
    if since_time is not None:
        params["since_time"] = since_time
    if until is not None:
        params["until"] = until
    return _http._request_json(
        socket_path,
        f"/evals/{eval_id}/sample/events",
        params=params,
        what=f"events for sample {sample_id}",
        not_found=(
            f"Sample '{sample_id}' (epoch {epoch}) not found — it may "
            "not have started or not yet been written to the log."
        ),
        pid=pid,
    )


_MESSAGES_ROUTE_MISSING = (
    "This process is running an older inspect without the sample "
    "messages endpoint; restart the eval to pick up the current version."
)


def _fetch_sample_messages(
    socket_path: str,
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    tail: int | None,
    content: bool,
    full: bool,
    pid: int | None = None,
) -> dict[str, Any]:
    """Query one control server for a snapshot of a sample's conversation.

    The authoritative read behind ``sample messages``: like the sample detail
    and events reads, it rides the full narrated busy-retry policy rather than
    failing on a momentary event-loop stall; ``pid`` scopes that policy's
    exhaustion pointer to the hosting process.
    """
    # sample_id (and all params) go in the query string so reserved-char ids
    # address correctly; drop unset options so server defaults apply.
    params: dict[str, Any] = {
        "sample_id": sample_id,
        "epoch": epoch,
        "content": content,
        "full": full,
    }
    if tail is not None:
        params["tail"] = tail
    return _http._request_json(
        socket_path,
        f"/evals/{eval_id}/sample/messages",
        params=params,
        what=f"messages for sample {sample_id}",
        not_found=(
            f"Sample '{sample_id}' (epoch {epoch}) not found — it may "
            "not have started or not yet been written to the log."
        ),
        not_found_missing_route=_MESSAGES_ROUTE_MISSING,
        pid=pid,
    )


_STORE_ROUTE_MISSING = (
    "This process is running an older inspect without the sample "
    "store endpoint; restart the eval to pick up the current version."
)


def _fetch_sample_store(
    socket_path: str,
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    keys: tuple[str, ...],
    content: bool,
    full: bool,
    pid: int | None = None,
) -> dict[str, Any]:
    """Query one control server for a snapshot of a sample's store.

    The authoritative read behind ``sample store``: like the sibling
    per-sample reads, it rides the full narrated busy-retry policy rather
    than failing on a momentary event-loop stall; ``pid`` scopes that
    policy's exhaustion pointer to the hosting process.
    """
    # sample_id (and all params) go in the query string so reserved-char ids
    # address correctly; `key` repeats on the wire (httpx encodes a list as
    # repeated params); drop it when unset so the server serves every key.
    params: dict[str, Any] = {
        "sample_id": sample_id,
        "epoch": epoch,
        "content": content,
        "full": full,
    }
    if keys:
        params["key"] = list(keys)
    return _http._request_json(
        socket_path,
        f"/evals/{eval_id}/sample/store",
        params=params,
        what=f"store for sample {sample_id}",
        not_found=(
            f"Sample '{sample_id}' (epoch {epoch}) not found — it may "
            "not have started or not yet been written to the log."
        ),
        not_found_missing_route=_STORE_ROUTE_MISSING,
        pid=pid,
    )


def _post_flush(
    socket_path: str, task_id: str, *, pid: int | None = None
) -> dict[str, Any]:
    """Ask one control server to flush a task's buffered samples to the log."""
    return _http._request_json(
        socket_path,
        f"/tasks/{task_id}/log-flush",
        what=f"log-flush of task {task_id}",
        not_found=(
            f"Task '{task_id}' is not flushable — it has no live sample "
            "buffer in this process (e.g. a reused log, or a retry "
            "attempt that's been superseded)."
        ),
        mutate="post",
        pid=pid,
    )
