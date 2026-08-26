"""Sample read runners: list/errors/show/events/messages/store.

Also the option validators these runners apply and the idle/truncation
footers of the listing outputs.
"""

from __future__ import annotations

import functools
import json as json_lib
import time
from datetime import datetime, timezone
from typing import Any, Literal, NamedTuple, NoReturn, Protocol

import click

from inspect_ai._control.state import (
    SAMPLE_STATUSES,
    effective_sample_limit,
    parse_status_filter,
)

# Patch seam: tests monkeypatch functions on their defining module
# (e.g. `inspect_ai._cli.ctl._http._request_json`), so cross-module
# calls must resolve through the module object at call time — do not
# "simplify" to `from ._http import _request_json` (see
# design/ctl/cli-refactor.md).
from . import _fetch
from ._failure import _envelope_failures, _fail
from ._fetch import (
    _exit_samples_unreachable,
    _fetch_sample_summaries,
    _narrow_by_model,
    _resolve_target_eval,
    _SamplesPage,
)
from ._group import _anomalies_pointer, _echo_no_running_evals
from ._http import (
    _REQUEST_ATTEMPTS,
    _BusyNarrator,
    _collect_reads,
    _run_async,
    _ServerBusy,
    _ServerUnreachable,
    _unreachable_detail,
)
from ._render import (
    _echo,
    _echo_raw,
    _format_duration,
    _print_errors_table,
    _print_events,
    _print_messages,
    _print_sample_detail,
    _print_samples_table,
    _print_store,
    _task_header,
)

# Events shown on an unseeded `sample events` read (no --cursor / --tail /
# --since-time / --until / --from-start): a recent tail rather than the full
# backlog — the first call must never be empty or a context-flooding dump
# (see the agent output contract in design/ctl/control-channel.md). The
# server counts the tail in *matched* events (post --type filter), so this
# is 20 high-signal events by default, not 20 raw transcript entries.
_DEFAULT_EVENTS_TAIL = 20

# Messages shown on an unseeded `sample messages` read (no --tail / --all): a
# recent tail rather than the whole conversation, which for a long agentic run
# can exceed a watching agent's context. Same "never empty, never a flood"
# rationale as the events tail.
_DEFAULT_MESSAGES_TAIL = 20

# Idle seconds on a running sample before the human `sample list` rendering
# appends the `process anomalies` escalation pointer below the table. "Tens
# of minutes" per "Trace-log anomalies for stall diagnosis" in
# design/ctl/control-channel.md: long enough that an ordinarily slow model
# call rarely trips it, short enough to teach the escalation while the stall
# still matters.
_IDLE_POINTER_MIN_SECONDS = 10 * 60


class _SampleRows(NamedTuple):
    """Result of :func:`_list_sample_rows`.

    ``as_of`` is the envelope timestamp (the earliest of the per-server
    ``as_of`` values, so nothing between them is missed). ``targets`` are the
    resolved target summaries; ``read`` the subset whose samples read actually
    succeeded (an unscoped fan-out warn-and-skips unreachable evals, and the
    human output must not make positive claims about samples it never saw).
    Every row carries ``task_id`` / ``task`` unconditionally (outputs feed
    inputs: the row's identifiers are the selectors other commands take).
    ``counts`` is the status histogram summed over the evals actually read —
    complete over each eval's samples even when its rows were filtered or
    capped, except against an older (histogram-less) server on an
    ``active_since`` delta poll, where only the delta's rows exist to count;
    ``truncated`` whether any eval's rows hit the cap.
    """

    as_of: float
    targets: list[dict[str, Any]]
    read: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    counts: dict[str, int]
    truncated: bool


def _list_sample_rows(
    task: str | None,
    active_since: float | None,
    *,
    sample_filter: Literal["errors"] | None = None,
    statuses: frozenset[str] | None = None,
    limit: int | None = None,
    all_samples: bool = False,
    content: bool = False,
    model: str | None = None,
) -> _SampleRows:
    """Fetch sample rows for one task (``task`` given) or all running tasks.

    ``statuses`` is the already-parsed ``--status`` member set (``None`` =
    no filter) — parsing lives with the caller so one parse serves the
    request, the fallback filter, and the truncation footer. ``model``
    narrows the candidate tasks to those running a matching model — with
    ``task`` it disambiguates the selector; without, it scopes the fan-out.
    """
    fallback_as_of = time.time()
    # Loop-invariant across targets: the filter's wire form and the
    # older-server fallback's row cap.
    status_param = ",".join(sorted(statuses)) if statuses is not None else None
    cap = effective_sample_limit(limit, all_samples)
    counts = dict.fromkeys(SAMPLE_STATUSES, 0)
    truncated = False
    fetched = _fetch_sample_summaries(task)
    summaries = fetched.summaries
    if not summaries:
        return _SampleRows(
            as_of=fallback_as_of,
            targets=[],
            read=[],
            rows=[],
            counts=counts,
            truncated=False,
        )

    if task is not None:
        targets = [
            _resolve_target_eval(
                summaries, task, busy_pids=fetched.busy_pids, model=model
            )
        ]
    elif model is not None:
        targets = _narrow_by_model(summaries, model, busy_pids=fetched.busy_pids)
    else:
        targets = summaries

    reads = _run_async(
        functools.partial(
            _read_all_eval_samples,
            targets,
            active_since,
            sample_filter=sample_filter,
            status=status_param,
            limit=limit,
            all_samples=all_samples,
            content=content,
            # a scoped read fails the command on busy, so it keeps the
            # full budget; the unscoped fan-out skips on the default
            attempts=_REQUEST_ATTEMPTS if task is not None else None,
        )
    )

    as_of_values: list[float] = []
    read: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for target, page in reads:
        if isinstance(page, _ServerUnreachable):
            if task is not None:
                _exit_samples_unreachable(
                    target["eval_id"], page, pid=target.get("pid")
                )
            # An unscoped read spans whatever evals happen to be running; one
            # process exiting — or staying busy through the retries — between
            # discovery and this read shouldn't fail the invocation (even if
            # it was the only eval).
            hint = (
                f"try again shortly, or {_anomalies_pointer(target.get('pid'))}"
                if isinstance(page, _ServerBusy)
                else "it may have just exited"
            )
            _echo(
                f"Skipping eval {target['eval_id']}: its samples could not be "
                f"read ({_unreachable_detail(page)}) — {hint}.",
                err=True,
            )
            continue
        as_of_values.append(page.as_of)
        read.append(target)
        truncated = truncated or page.truncated
        # An older server's envelope carries no histogram — and such a server
        # ignored the `status`/`limit` params (though it did honor
        # `active_since`): derive counts from its rows, then apply the filter
        # and cap client-side so the flags' contract holds across version
        # skew. On an `active_since` delta poll only the delta's rows exist
        # to count, so the derived counts cover the delta, not the whole
        # eval — a whole-eval histogram is unobtainable from an old server
        # in a single delta read.
        page_counts = page.counts
        samples = page.samples
        if page_counts is None:
            page_counts = {}
            for sample in samples:
                page_status = str(sample.get("status") or "")
                page_counts[page_status] = page_counts.get(page_status, 0) + 1
            if statuses is not None:
                samples = [s for s in samples if s.get("status") in statuses]
            if cap is not None and len(samples) > cap:
                samples = samples[:cap]
                truncated = True
        for key, value in page_counts.items():
            counts[key] = counts.get(key, 0) + int(value)
        for sample in samples:
            rows.append(
                {
                    "task_id": target.get("task_id"),
                    "task": target.get("task"),
                    **sample,
                }
            )
    return _SampleRows(
        as_of=min(as_of_values, default=fallback_as_of),
        targets=targets,
        read=read,
        rows=rows,
        counts=counts,
        truncated=truncated,
    )


class _EvalSamplesRead(NamedTuple):
    """One target eval's samples read (see :func:`_read_all_eval_samples`).

    ``page`` is the eval's samples, or the :class:`_ServerUnreachable` that
    replaced it — captured rather than raised because the reads run
    concurrently, and an exception escaping into the task group would cancel
    its siblings where the policy is per-eval warn-and-skip.
    """

    target: dict[str, Any]
    page: _SamplesPage | _ServerUnreachable


async def _read_all_eval_samples(
    targets: list[dict[str, Any]],
    active_since: float | None,
    *,
    sample_filter: Literal["errors"] | None,
    status: str | None,
    limit: int | None,
    all_samples: bool,
    content: bool,
    attempts: int | None,
) -> list[_EvalSamplesRead]:
    """Read each target eval's samples concurrently, in target order.

    The reads go out together because their cost is round-trip and connection
    setup, not server work: one at a time, an unscoped listing over an eval
    set with many running tasks paid that round-trip per eval and looked
    hung, while each server answered in about a millisecond.
    """
    # concurrent reads stall in lockstep, so they share one narrator rather
    # than each reporting the same wedged process's every attempt
    narrator = (
        _BusyNarrator(f"Reading samples from {len(targets)} evals")
        if len(targets) > 1
        else None
    )

    async def read(target: dict[str, Any]) -> _EvalSamplesRead:
        # Query by the task's current eval id (resolved fresh each invocation,
        # so this still works after a retry minted a new one).
        try:
            page = await _fetch._fetch_samples_async(
                target["socket_path"],
                target["eval_id"],
                active_since,
                sample_filter=sample_filter,
                status=status,
                limit=limit,
                all_samples=all_samples,
                content=content,
                attempts=attempts,
                narrator=narrator,
            )
        except _ServerUnreachable as exc:
            return _EvalSamplesRead(target, exc)
        return _EvalSamplesRead(target, page)

    return await _collect_reads([functools.partial(read, target) for target in targets])


class _RowsPrinter(Protocol):
    """Prints a sample-rows table (``show_task`` adds the task column)."""

    def __call__(
        self, samples: list[dict[str, Any]], show_task: bool = False
    ) -> None: ...


def _run_sample_list(
    task: str | None,
    active_since: float | None,
    as_json: bool,
    *,
    status: str | None = None,
    limit: int | None = None,
    all_samples: bool = False,
    content: bool = False,
    model: str | None = None,
) -> None:
    if all_samples and limit is not None:
        raise click.UsageError("--all and --limit are mutually exclusive.")
    _run_sample_listing(
        task,
        active_since,
        as_json,
        empty_read="(no samples started yet)",
        printer=_print_samples_table,
        statuses=_parse_statuses(status),
        limit=limit,
        all_samples=all_samples,
        content=content,
        idle_pointer=True,
        model=model,
    )


def _parse_statuses(status: str | None) -> frozenset[str] | None:
    """Parse ``--status``, rejecting an empty or unknown value up front.

    The server 400s on these too, but an unscoped listing fans out over
    several evals — failing fast keeps a typo from producing a per-eval
    warn-and-skip cascade instead of one clear usage error.
    """
    statuses, error = parse_status_filter(status, param="--status")
    if error is not None:
        raise click.UsageError(f"{error}.")
    return statuses


def _run_sample_errors(
    task: str | None, as_json: bool, *, content: bool = False, model: str | None = None
) -> None:
    _run_sample_listing(
        task,
        None,
        as_json,
        model=model,
        sample_filter="errors",
        empty_read="(no errors or retries)",
        printer=_print_errors_table,
        # The triage view must see every errored/retried row — the default
        # cap would silently hide errors beyond it (the server's errors
        # filter narrows the rows, but capped-filtered is still capped).
        all_samples=True,
        content=content,
        # this is the error-focused view, so an empty error column needs
        # the pointer to the opt-in
        content_footer=None
        if content
        else "error messages withheld — pass --content to include them",
    )


@_envelope_failures
def _run_sample_listing(
    task: str | None,
    active_since: float | None,
    as_json: bool,
    *,
    sample_filter: Literal["errors"] | None = None,
    empty_read: str,
    printer: "_RowsPrinter",
    statuses: frozenset[str] | None = None,
    limit: int | None = None,
    all_samples: bool = False,
    content: bool = False,
    content_footer: str | None = None,
    idle_pointer: bool = False,
    model: str | None = None,
) -> None:
    """The shared body of `sample list` / `sample errors`.

    One home for the listing contract: the ``{as_of, counts, samples,
    truncated}`` envelope, the no-targets message, the single-vs-multi-target
    header/table shape, the truncation footer (a capped listing must say so —
    no silent truncation), and the honesty rule that ``empty_read`` (a
    positive "(none)" claim) is made only for targets whose samples were
    actually read — a target warn-and-skipped as unreachable gets "(samples
    unavailable)" instead, and an empty ``--status``-filtered or
    ``--active-since`` delta listing gets a filter-scoped message (samples
    may exist that simply didn't match). ``statuses`` is the already-parsed
    ``--status`` member set (``None`` = no filter). ``content`` asks the
    server to include each row's error message (withheld by default —
    agent-influenced free text); ``content_footer`` is a human-rendering
    footer noting the withholding (echoed after a non-empty table, and
    suppressed when a row carries an error message anyway — a pre-v6 server
    ignores the ``content`` param, and the footer must not caption text
    printed right above it as withheld).
    ``idle_pointer`` opts the human rendering into the long-idle escalation
    footer (`sample list` — the listing whose idle column shows a stall; see
    :func:`_echo_idle_pointer`).
    """
    listing = _list_sample_rows(
        task,
        active_since,
        sample_filter=sample_filter,
        statuses=statuses,
        limit=limit,
        all_samples=all_samples,
        content=content,
        model=model,
    )
    rows = listing.rows

    if as_json:
        _echo_raw(
            json_lib.dumps(
                {
                    "as_of": listing.as_of,
                    "counts": listing.counts,
                    "samples": rows,
                    "truncated": listing.truncated,
                },
                indent=2,
            )
        )
        return

    if not listing.targets:
        _echo_no_running_evals()
        return

    if not listing.read:
        empty = "(samples unavailable)"
    elif statuses is not None:
        empty = f"(no matching samples: 0 of {sum(listing.counts.values())})"
    elif active_since is not None:
        empty = "(no samples active since the given timestamp)"
    else:
        empty = empty_read
    if len(listing.targets) == 1:
        _echo(_task_header(listing.targets[0]))
        if not rows:
            _echo(empty)
            return
        _echo()
        printer(rows)
    else:
        if not rows:
            _echo(empty)
            return
        printer(rows, show_task=True)
    if content_footer is not None and not any(
        row.get("error") is not None for row in rows
    ):
        _echo()
        _echo(content_footer)
    if listing.truncated:
        _echo_truncation_footer(
            len(rows),
            listing.counts,
            statuses=statuses,
            delta=active_since is not None,
        )
    if idle_pointer:
        _echo_idle_pointer(rows, listing.read)


def _echo_idle_pointer(rows: list[dict[str, Any]], read: list[dict[str, Any]]) -> None:
    """Print the stall-escalation footer below a long-idle sample listing.

    The idle column says a running sample has been silent, not why: a single
    in-flight operation (model call, sandbox exec) emits no transcript event
    until it returns, so a long idle reads identically whether the call is
    slow-but-healthy or hung. The trace file is the layer below, and where
    the table already shows the stall the surface teaches the escalation
    (see :func:`_anomalies_pointer`) rather than relying on the user knowing
    the trace subsystem exists. ``read`` (the targets whose samples were
    fetched) supplies the pid, keyed by ``task_id`` — the only target
    identity a row carries. A ``task_id`` is not unique across ``read`` (an
    old kept-alive attempt a newer process is retrying shares it — see
    ``stop_on_task_id`` on :func:`_fetch_summaries` — and pre-task-id
    servers report none), so a task read from several processes counts them
    all: naming one would risk pointing at the wrong process. Whenever the
    stalled rows resolve to anything but exactly one pid the bare verb is
    suggested, which reads every process. Human rendering only — the
    ``--json`` path returns before any table is printed.
    """
    now = datetime.now(timezone.utc).timestamp()
    pids_by_task: dict[Any, set[Any]] = {}
    for target in read:
        pids_by_task.setdefault(target.get("task_id"), set()).add(target.get("pid"))
    idles: list[float] = []
    pids: set[Any] = set()
    for sample in rows:
        last = sample.get("last_activity_at")
        if sample.get("status") != "running" or last is None:
            continue
        idle = now - float(last)
        if idle >= _IDLE_POINTER_MIN_SECONDS:
            idles.append(idle)
            pids.update(pids_by_task.get(sample.get("task_id")) or {None})
    if not idles:
        return
    only = next(iter(pids)) if len(pids) == 1 else None
    pid = int(only) if only is not None else None
    _echo()
    _echo(f"idle {_format_duration(max(idles))} — {_anomalies_pointer(pid)}")


def _echo_truncation_footer(
    shown: int,
    counts: dict[str, int],
    *,
    statuses: frozenset[str] | None = None,
    delta: bool = False,
) -> None:
    """Say a capped listing was capped (the no-silent-truncation rule).

    ``counts`` is the whole-task histogram, so when ``--status`` or an
    ``--active-since`` delta narrowed the listing, "of {sum(counts)}" would
    overstate how many rows ``--all`` returns. A status filter's matching
    total is recoverable from the histogram; a delta's is not knowable
    client-side, so the footer claims only the totals it has.
    """
    total = sum(counts.values())
    histogram = " · ".join(
        f"{counts[status]} {status}" for status in SAMPLE_STATUSES if counts[status]
    )
    if delta:
        showing = (
            f"showing first {shown} matching sample{'' if shown == 1 else 's'} "
            f"({total} total: {histogram})"
        )
    elif statuses is not None:
        matching = sum(counts.get(status, 0) for status in statuses)
        showing = (
            f"showing {shown} of {matching} matching samples "
            f"({total} total: {histogram})"
        )
    else:
        showing = f"showing {shown} of {total} samples ({histogram})"
    hint = "pass --all (or --limit N) for more"
    if statuses is None:
        hint += ", --status to filter"
    _echo()
    _echo(f"listing capped: {showing} — {hint}")


@_envelope_failures
def _run_sample_show(
    task: str,
    sample_id: str,
    epoch: int,
    content: bool,
    show_traceback: bool,
    as_json: bool,
    *,
    model: str | None = None,
) -> None:
    fetched = _fetch_sample_summaries(task)
    summaries = fetched.summaries
    if not summaries:
        if as_json:
            _echo_raw("null")
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(
        summaries, task, busy_pids=fetched.busy_pids, model=model
    )
    # One atomic read: the detail carries the summary fields (timing / tokens
    # / messages) alongside the error history, so there is no supplemental
    # listing fetch (and no torn view if the sample retries between reads).
    detail = _fetch._fetch_sample_detail(
        target["socket_path"],
        target["eval_id"],
        sample_id,
        epoch,
        content=content,
        pid=target.get("pid"),
    )
    row = (
        _fetch_sample_row_from_listing(target, detail)
        if "message_count" not in detail
        else None
    )
    merged: dict[str, Any] = {
        "task_id": target.get("task_id"),
        "task": target.get("task"),
        **(row or {}),
        **detail,
    }

    if as_json:
        _echo_raw(json_lib.dumps(merged, indent=2))
        return

    _print_sample_detail(merged, show_traceback)


def _fetch_sample_row_from_listing(
    target: dict[str, Any], detail: dict[str, Any]
) -> dict[str, Any] | None:
    """The sample's listing row — `sample show`'s old-server fallback.

    A current control server's detail response carries the summary fields
    (timing / tokens / messages), so their *absence* — keyed on
    ``message_count``, present even when null — marks a server from before
    they were added (``ctl`` attaches to already-running processes, so the
    CLI can be newer than the server). Only then is the eval's listing
    fetched to fold in the sample's row, restoring the fields the old
    two-read flow reported; a failed fallback read degrades to the detail
    alone with a stderr caveat rather than discarding the answer in hand.
    Not a strict version test: a current server also omits the keys on its
    terminal path's degrade case (its own summary-row lookup missed), where
    this fallback fires harmlessly as a second chance at the row.
    """
    try:
        # all_samples: this lookup needs the target sample's row, which the
        # default cap could drop.
        samples = _fetch._fetch_samples(
            target["socket_path"],
            target["eval_id"],
            all_samples=True,
        ).samples
    except _ServerUnreachable as exc:
        hint = (
            f" — try again shortly, or {_anomalies_pointer(target.get('pid'))}"
            if isinstance(exc, _ServerBusy)
            else ""
        )
        _echo(
            f"Could not read the samples listing for eval {target['eval_id']} "
            f"({_unreachable_detail(exc)}); showing the sample without its "
            f"summary fields (timing / tokens / messages){hint}.",
            err=True,
        )
        return None
    return next(
        (
            s
            for s in samples
            if str(s.get("sample_id")) == str(detail.get("sample_id"))
            and s.get("epoch") == detail.get("epoch")
        ),
        None,
    )


@_envelope_failures
def _run_sample_events(
    task: str,
    sample_id: str,
    epoch: int,
    *,
    model: str | None = None,
    cursor: str | None,
    tail: int | None,
    from_start: bool,
    limit: int | None,
    types: str | None,
    content: bool,
    full: bool,
    since_time: float | None,
    until: float | None,
    as_json: bool,
) -> None:
    _validate_from_start(from_start, cursor=cursor, tail=tail, since_time=since_time)
    _validate_cursor(cursor)
    if limit is not None and limit < 1:
        _fail("invalid_request", "--limit must be at least 1.")
    types = _normalized_types(types)

    # The unseeded default is a recent tail — never an empty page, never the
    # full backlog. A cursor, an explicit window, or --from-start disables it
    # (an unseeded, tail-less read starts at event 0 — exactly "from start").
    if (
        not from_start
        and cursor is None
        and tail is None
        and since_time is None
        and until is None
    ):
        tail = _DEFAULT_EVENTS_TAIL

    # the all-busy exit inside the fetch matters doubly here: the done:true
    # empty page below would falsely end a polling loop for an eval whose
    # events may live on the busy pid
    fetched = _fetch_sample_summaries(task)
    summaries = fetched.summaries
    if not summaries:
        if as_json:
            # Carry the identifier echo even on the empty page so every
            # --json page has a uniform shape (task_id is unresolvable
            # with no running evals).
            empty_page: dict[str, Any] = {
                "task_id": None,
                "sample_id": sample_id,
                "epoch": epoch,
                "events": [],
                "next": None,
                "done": True,
            }
            _echo_raw(json_lib.dumps(empty_page, indent=2))
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(
        summaries, task, busy_pids=fetched.busy_pids, model=model
    )
    page = _fetch._fetch_sample_events(
        target["socket_path"],
        target["eval_id"],
        sample_id,
        epoch,
        cursor=cursor,
        tail=tail,
        limit=limit,
        types=types,
        content=content,
        full=full,
        since_time=since_time,
        until=until,
        pid=target.get("pid"),
    )
    # Echo the resolved identifiers so a defaulted epoch is visible and the
    # row round-trips into other commands' selectors.
    page = {
        "task_id": target.get("task_id"),
        "sample_id": sample_id,
        "epoch": epoch,
        **page,
    }

    if as_json:
        _echo_raw(json_lib.dumps(page, indent=2))
        return

    _print_events(page, content=content, full=full)


@_envelope_failures
def _run_sample_messages(
    task: str,
    sample_id: str,
    epoch: int,
    *,
    model: str | None = None,
    tail: int | None,
    show_all: bool,
    content: bool,
    full: bool,
    as_json: bool,
) -> None:
    # `--all` and `--tail` are mutually exclusive ways to size the window;
    # an explicit --tail with --all is contradictory, so reject it rather
    # than silently letting one win.
    if show_all and tail is not None:
        _fail(
            "invalid_request",
            "--all and --tail are mutually exclusive (--all shows every "
            "message; --tail sizes a recent window).",
        )
    # The unseeded default is a recent tail — never an overwhelming first
    # page. --all disables it; an explicit --tail overrides it.
    if not show_all and tail is None:
        tail = _DEFAULT_MESSAGES_TAIL

    fetched = _fetch_sample_summaries()
    summaries = fetched.summaries
    if not summaries:
        if as_json:
            # Uniform --json shape even on the empty page (task_id is
            # unresolvable with no running evals; as_of is None because no
            # server stamped a read time).
            empty_page: dict[str, Any] = {
                "task_id": None,
                "sample_id": sample_id,
                "epoch": epoch,
                "as_of": None,
                "status": None,
                "count": 0,
                "messages": [],
            }
            _echo_raw(json_lib.dumps(empty_page, indent=2))
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(
        summaries, task, busy_pids=fetched.busy_pids, model=model
    )
    page = _fetch._fetch_sample_messages(
        target["socket_path"],
        target["eval_id"],
        sample_id,
        epoch,
        tail=tail,
        content=content,
        full=full,
        pid=target.get("pid"),
    )
    # Echo the resolved identifiers so a defaulted epoch is visible and the
    # row round-trips into other commands' selectors.
    page = {
        "task_id": target.get("task_id"),
        "sample_id": sample_id,
        "epoch": epoch,
        **page,
    }

    if as_json:
        _echo_raw(json_lib.dumps(page, indent=2))
        return

    _echo(_task_header(target))
    _echo()
    _print_messages(page, content=content, full=full)


@_envelope_failures
def _run_sample_store(
    task: str,
    sample_id: str,
    epoch: int,
    *,
    keys: tuple[str, ...],
    content: bool,
    full: bool,
    as_json: bool,
) -> None:
    fetched = _fetch_sample_summaries()
    summaries = fetched.summaries
    if not summaries:
        if as_json:
            # Uniform --json shape even on the empty page (task_id is
            # unresolvable with no running evals; as_of is None because no
            # server stamped a read time). `missing` appears only when keys
            # were requested, as on a served page — empty, since no store
            # was read to be missing from.
            empty_page: dict[str, Any] = {
                "task_id": None,
                "sample_id": sample_id,
                "epoch": epoch,
                "as_of": None,
                "status": None,
                "count": 0,
                "store": {},
            }
            if keys:
                empty_page["missing"] = []
            _echo_raw(json_lib.dumps(empty_page, indent=2))
            return
        _echo_no_running_evals()
        return

    target = _resolve_target_eval(summaries, task, busy_pids=fetched.busy_pids)
    page = _fetch._fetch_sample_store(
        target["socket_path"],
        target["eval_id"],
        sample_id,
        epoch,
        keys=keys,
        content=content,
        full=full,
        pid=target.get("pid"),
    )
    # Echo the resolved identifiers so a defaulted epoch is visible and the
    # row round-trips into other commands' selectors.
    page = {
        "task_id": target.get("task_id"),
        "sample_id": sample_id,
        "epoch": epoch,
        **page,
    }

    if as_json:
        _echo_raw(json_lib.dumps(page, indent=2))
        return

    _echo(_task_header(target))
    _echo()
    _print_store(page, content=content, full=full)


def _looks_like_timestamp(value: str) -> bool:
    """Whether a would-be cursor value reads as a unix timestamp.

    Real cursors are opaque base64 tokens and never parse as a number, so a
    numeric value is almost certainly a timestamp meant for ``--since-time``.
    The one classification behind both cursor-mistake errors
    (:func:`_exit_removed_since`, :func:`_validate_cursor`).
    """
    try:
        float(value)
        return True
    except ValueError:
        return False


def _exit_removed_since(value: str) -> NoReturn:
    """Teach the `--since` split instead of click's stock no-such-option error.

    The old flag was the cursor; click's own suggestion ("did you mean
    --since-time?") points cursor-holders the wrong way, so the command keeps
    a hidden `--since` whose only job is this error — routed by the same
    timestamp heuristic `--cursor` validation uses.
    """
    hint = (
        "this value looks like a timestamp — use --since-time"
        if _looks_like_timestamp(value)
        else "pass it to --cursor (the `next` value from a prior page)"
    )
    _fail(
        "invalid_request",
        f"--since was split into --cursor (opaque resume cursor) and "
        f"--since-time (wall-clock window): {hint}.",
    )


def _validate_from_start(
    from_start: bool,
    *,
    cursor: str | None,
    tail: int | None,
    since_time: float | None,
) -> None:
    """Reject ``--from-start`` combined with another window seed.

    A resume cursor contradicts "from the beginning", and ``--tail`` /
    ``--since-time`` each seed a different window start. ``--until`` is
    deliberately allowed — bounding a from-the-start read by wall clock is
    coherent.
    """
    if not from_start:
        return
    conflicting = [
        flag
        for flag, value in (
            ("--cursor", cursor),
            ("--tail", tail),
            ("--since-time", since_time),
        )
        if value is not None
    ]
    if conflicting:
        _fail(
            "invalid_request",
            f"--from-start reads from the first event and cannot be combined "
            f"with {' / '.join(conflicting)}.",
        )


def _normalized_types(types: str | None) -> str | None:
    """Map the blessed ``all`` spelling onto the wire's ``*``.

    ``--type '*'`` must be quoted (bare ``*`` glob-expands in bash and errors
    in zsh), so ``all`` is the documented spelling — safe as a magic value
    since no event type is named ``all``. Translated client-side so it also
    works against a running server that predates the synonym.
    """
    if types is None:
        return None
    return ",".join(
        "*" if member == "all" else member
        for member in (part.strip() for part in types.split(","))
    )


def _validate_cursor(cursor: str | None) -> None:
    """Reject a ``--cursor`` value that isn't an opaque cursor token.

    The server treats a non-decodable cursor as "restart from the beginning";
    for an agent that passed a timestamp that silent restart hides the
    mistake, so the CLI errors instead — teaching ``--since-time`` when the
    value looks like a timestamp.
    """
    if cursor is None:
        return
    from inspect_ai._control.events import decode_cursor

    nonce, _offset = decode_cursor(cursor)
    if nonce is not None:
        return
    hint = (
        " — this looks like a timestamp; did you mean --since-time?"
        if _looks_like_timestamp(cursor)
        else " — pass the `next` value from a prior page."
    )
    _fail("invalid_request", f"Invalid --cursor value '{cursor}'{hint}")
