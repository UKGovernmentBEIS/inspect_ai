r"""Eval-level state extraction for the control channel.

Reads from two sources at request time:

- :func:`inspect_ai._control.eval_state.get_eval_states` for ``total`` /
  ``completed`` / ``errored`` counters that survive a sample exiting
  ``active_samples``.
- :func:`inspect_ai.log._samples.active_samples` for ``in_flight``
  (currently-executing samples), plus the per-eval ``task`` / ``model``
  / ``started_at`` / ``run_id`` metadata.

One process can host multiple evals at once. There are two ways this
happens:

- Inside a single ``eval()`` call with multiple tasks (an eval-set
  passes all tasks in one call). All share the same ``run_id`` but
  carry distinct ``eval_id``\s.
- Across multiple ``eval()`` calls in an eval-set (across retries).
  Each call has its own ``run_id``; the (eval-set-scoped) control
  server stays bound across them.

The endpoint folds task retries into a single entry per ``task_id``:
when a task is retried by ``task_retry_attempts`` (or eval-set-level
retries — including the legacy ``retry_immediate=False`` mode, where
each attempt is its own ``eval()`` call with a fresh ``run_id``), each
attempt mints a fresh ``eval_id`` but ``task_id`` is preserved. Without
folding, a task that failed twice and succeeded on attempt three
would appear as three rows. The aggregated row reports the latest
attempt's state (its counters subsume reused samples from prior
attempts) and an ``attempts`` count so consumers can surface retry
activity.
"""

from __future__ import annotations

from collections import defaultdict
from functools import partial
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

from inspect_ai._util._async import tg_collect
from inspect_ai._util.error import is_cancellation_message
from inspect_ai._util.file import local_path

if TYPE_CHECKING:
    from inspect_ai._control.eval_state import EvalState
    from inspect_ai.log._samples import ActiveSample

# The canonical per-sample status vocabulary of the samples listing — the
# keys of the listing envelope's ``counts`` histogram (always all present,
# zero when empty, so the schema is stable for agents) and the values the
# ``status`` filter accepts.
SAMPLE_STATUSES = ("running", "completed", "error", "cancelled", "pending", "queued")

# Default row cap for the samples listing (`GET /evals/<id>/samples` and
# `inspect ctl sample list`). The listing is otherwise linear in sample
# count — a 10k-sample eval-set would return ~10k rows in one response,
# flooding an LLM agent's context (see "Shape constraints from agent
# consumers" in design/ctl/control-channel.md, constraint 2). Rows sort
# running → terminal → pending, so the cap keeps the most relevant rows;
# the envelope's `counts` histogram keeps the aggregate answer complete
# and `truncated` reports the cap structurally.
DEFAULT_SAMPLE_LIST_LIMIT = 100


class StatusFilterParse(NamedTuple):
    """Result of :func:`parse_status_filter`.

    Exactly one field is non-``None`` when a filter was given: ``statuses``
    is the parsed member set, ``error`` says why the value is invalid.
    Both are ``None`` when no filter was given.
    """

    statuses: frozenset[str] | None
    error: str | None


def parse_status_filter(status: str | None, param: str = "status") -> StatusFilterParse:
    """Parse a comma-separated status filter into its member set.

    The single home for the filter's parse and validation, shared by the
    server endpoint and the CLI's fail-fast check so the vocabulary error
    wording can't drift between the two surfaces. ``param`` names the
    parameter in error messages (``status`` server-side, ``--status`` in
    the CLI).

    Args:
        status: The raw comma-separated value (``None`` = no filter).
        param: Parameter name to use in error messages.

    Returns:
        The member set, or the error message describing why the value
        is invalid (an empty or unknown member).
    """
    if status is None:
        return StatusFilterParse(statuses=None, error=None)
    members = frozenset(t for t in (p.strip() for p in status.split(",")) if t)
    # A closed-vocabulary filter with no members is always a mistake (it
    # would silently drop every row), not "no filter".
    if not members:
        return StatusFilterParse(
            statuses=None,
            error=(
                f"{param} requires at least one status "
                f"(expected {', '.join(SAMPLE_STATUSES)})"
            ),
        )
    unknown = sorted(members - frozenset(SAMPLE_STATUSES))
    if unknown:
        return StatusFilterParse(
            statuses=None,
            error=(
                f"unknown {param} '{unknown[0]}' "
                f"(expected {', '.join(SAMPLE_STATUSES)})"
            ),
        )
    return StatusFilterParse(statuses=members, error=None)


def effective_sample_limit(limit: int | None, all_samples: bool) -> int | None:
    """Resolve a samples listing's row cap from its `limit`/`all` params.

    The single home for the cap semantics (shared by the server endpoint
    and the CLI's older-server fallback): ``all_samples`` means no cap,
    an explicit ``limit`` wins otherwise, and the default is
    :data:`DEFAULT_SAMPLE_LIST_LIMIT`. Callers reject the contradictory
    ``all_samples and limit is not None`` case before resolving.
    """
    if all_samples:
        return None
    return limit if limit is not None else DEFAULT_SAMPLE_LIST_LIMIT


async def current_eval_summaries(started_at: float) -> list[dict[str, Any]]:
    """Build per-task summaries for the ``GET /tasks`` endpoint.

    No ``run_id`` filter — the discovery layer already scopes
    visibility per process (each running inspect process has its own
    AF_UNIX socket / discovery file), so all entries from
    ``active_samples`` are this process's. Within the process, an
    eval-set may span multiple ``run_id``s (legacy batch-retry mode);
    we emit one entry per ``task_id`` group and carry that group's
    ``eval_id`` (latest attempt) along.

    Args:
        started_at: Fallback start time for evals whose samples
            haven't started yet.

    Returns:
        One dict per task_id group, sorted by start time
        (oldest first). Each entry includes ``log_location`` (where this
        attempt's results are written), a nested ``samples`` block:
        ``{total, completed, errored, in_flight, queued}``, an
        ``attempts`` count (1 for tasks without retries, >1 when
        retries occurred), and the running ``refusals`` / ``http_retries``
        tallies for this eval's samples.
    """
    # Lazy imports to avoid pulling the full log/event/scorer chain at
    # module-import time (control server module is imported during
    # eval bootstrap before those packages finish initialising).
    from inspect_ai._control.eval_state import (
        get_eval_states,
        resolve_deferred_sample_stats,
    )
    from inspect_ai._control.pause import process_paused
    from inspect_ai.log._samples import active_samples

    states = get_eval_states()

    # Resolve reused evals' summaries-derived stats (lazy: the first request
    # pays the per-log reads — concurrently — instead of eval-set startup
    # paying them serially whether or not a control client ever connects;
    # subsequent requests are free). Unbounded fan-out matches the bulk
    # header reads in `read_eval_logs_async`: effective concurrency is
    # governed by the filesystem's connection pool.
    deferred = [s for s in states if s.deferred_sample_stats is not None]
    if deferred:
        await tg_collect(
            [partial(resolve_deferred_sample_stats, state) for state in deferred]
        )

    # Group live samples by eval_id (per-attempt, not folded).
    samples_by_eval: dict[str, list[ActiveSample]] = defaultdict(list)
    for sample in active_samples():
        samples_by_eval[sample.eval_id].append(sample)

    # Group EvalStates by task_id so retry attempts of the same task
    # collapse into a single group. Deliberately NOT keyed by run_id:
    # legacy batch-retry mode (eval_set with retry_immediate=False) runs
    # each attempt as its own eval() call with a fresh run_id, and keying
    # on run_id split those attempts into duplicate rows that made the
    # task selector permanently ambiguous. task_id alone is safe within a
    # registry lifetime — the registry clears at every run boundary and
    # only one eval run executes at a time (the `_eval_async_running`
    # guard), so same-task_id states are always attempts of one logical
    # task. Fallback grouping by eval_id keeps pre-task_id states (or any
    # record missing a task_id) on their own row.
    states_by_group: dict[str, list[EvalState]] = defaultdict(list)
    for state in states:
        key = state.task_id if state.task_id else state.eval_id
        states_by_group[key].append(state)

    # eval_ids covered by some grouped state — used to attribute live
    # samples to their group when building the per-group summary.
    eval_id_to_group: dict[str, str] = {}
    for group_key, group_states in states_by_group.items():
        for state in group_states:
            eval_id_to_group[state.eval_id] = group_key

    # Live samples whose eval has no registered EvalState (eg. a brand-
    # new attempt that hasn't yet hit ``register_eval``) still need to
    # show up — give each its own one-off group keyed by eval_id.
    orphan_sample_eval_ids = set(samples_by_eval.keys()) - set(eval_id_to_group.keys())

    summaries: list[dict[str, Any]] = []

    for group_key, group_states in states_by_group.items():
        # Latest attempt = last registered. Retries are sequential (a
        # retry registers only after the prior attempt finishes), and
        # `get_eval_states()` preserves registration order, so the tail
        # is the current attempt. Selecting by `completed_at` would wrongly
        # prefer a finished earlier attempt over a still-running retry
        # (whose `completed_at` is None).
        latest = group_states[-1]
        attempts = len(group_states)

        # Live samples: pull from every attempt in the group (only the
        # latest will normally have any, but be defensive).
        group_samples: list[ActiveSample] = []
        for state in group_states:
            group_samples.extend(samples_by_eval.get(state.eval_id, []))

        summaries.append(
            _build_summary(
                latest=latest,
                # every attempt, for the event counters only (see _build_summary)
                states=group_states,
                samples=group_samples,
                attempts=attempts,
                started_at_fallback=started_at,
            )
        )

    for eval_id in orphan_sample_eval_ids:
        samples = samples_by_eval[eval_id]
        first = samples[0]
        summaries.append(
            {
                "run_id": first.run_id,
                "eval_id": eval_id,
                "task": first.task,
                "task_id": "",
                "model": first.model,
                # ActiveSample doesn't carry the solver name; it arrives with
                # the eval's registration (which hasn't happened yet here)
                "solver": "",
                "log_location": local_path(first.log_location),
                "status": "running",
                "started_at": min(
                    (s.started for s in samples if s.started is not None),
                    default=started_at,
                ),
                "completed_at": None,
                # a pre-registration attempt has no task_id, so only the
                # process latch can hold it (its model latch already gated
                # dispatch upstream); mid-startup is never "safe to kill",
                # hence quiesced stays False
                "paused": ["process"] if process_paused() else None,
                "quiesced": False,
                "attempts": 1,
                "samples": {
                    "total": 0,
                    "completed": 0,
                    "errored": 0,
                    "cancelled": 0,
                    "in_flight": sum(
                        1
                        for s in samples
                        if s.started is not None and s.completed is None
                    ),
                    "queued": 0,
                },
                "total_tokens": sum(s.total_tokens for s in samples),
                "total_messages": sum(s.total_messages for s in samples),
                # No eval total to add: this path is the pre-registration window,
                # where the only samples that exist are the live ones.
                "refusals": sum(s.refusals for s in samples),
                "http_retries": sum(s.http_retries for s in samples),
            }
        )

    summaries.sort(key=lambda s: s["started_at"])
    return summaries


async def current_sample_summaries(
    eval_id: str,
    sample_filter: Literal["errors"] | None = None,
) -> list[dict[str, Any]]:
    """Per-sample summaries for one eval (``GET /evals/<eval_id>/samples``).

    Lists *all* of the eval's samples — running, completed, and pending —
    from three sources, since none is complete on its own for a live eval:

    - **running** ← ``active_samples`` (the only place a running sample
      exists; freshest live detail).
    - **completed** ← the recorder's in-memory summaries while the eval
      runs (gap-free, ahead of disk; via ``EvalState.live.sample_summaries``),
      falling back to the finalized on-disk log once the recorder is gone
      (eval finished / torn down) — read once and memoized on the state
      (see :func:`_sample_summaries_from_log`).
    - **pending** ← synthesized from the eval's registered planned
      ``(sample_id, epoch)`` pairs (``EvalState.sample_ids`` × ``epochs``)
      that aren't yet running or done — no live source holds these.

    Merged and deduped by ``(sample_id, epoch)``; a terminal record
    (completed / error) supersedes a running one, which supersedes a
    pending one. Sorted running → terminal → pending. Returns an empty
    list when the eval isn't in this process.

    Each entry has: ``sample_id``, ``epoch``, ``status`` (a
    :data:`SAMPLE_STATUSES` member), ``started_at``, ``completed_at``,
    ``total_time``, ``total_tokens``, ``message_count``,
    ``last_activity_at`` (unix ts of the sample's most recent event — for a
    running sample, ``now - last_activity_at`` is its idle time, a cheap
    stall signal), ``activity`` (the running sample's in-flight operation —
    see :func:`_sample_activity`; ``None`` on non-running rows and when
    nothing is pending), ``events`` (live transcript event count; ``None``
    for terminal / pending samples), ``scores`` (``{scorer: value}``, empty
    until scored), ``error``, ``retries``, ``limit``.

    ``sample_filter="errors"`` restricts the result to samples that carry an
    error or have been retried (``error`` set, or ``retries`` > 0) — the
    eval-set triage read behind ``inspect ctl sample errors``. Filtering
    server-side also skips pending-row synthesis entirely: a pending sample
    can never carry an error or retries, and for a large dataset × epochs
    grid building (and serializing) those rows on the eval's own event loop
    dominates the response just to be discarded client-side.

    The ``active_since`` recency filter lives in
    :func:`current_sample_listing` (its single home), which wraps this
    full listing.
    """
    by_key: dict[tuple[Any, int], dict[str, Any]] = {}

    def _merge(summary: dict[str, Any]) -> None:
        key = (summary["sample_id"], summary["epoch"])
        existing = by_key.get(key)
        # Keep the first record for a key, except let a terminal record
        # supersede a still-running one (a sample that has since finished).
        if existing is None or (
            existing["status"] == "running" and summary["status"] != "running"
        ):
            by_key[key] = summary

    # Running first (the freshest source for in-flight samples), then the
    # completed records (which supersede any now-finished running entry).
    for summary in _sample_summaries_from_active(eval_id):
        _merge(summary)
    completed = await _completed_sample_summaries(eval_id)
    # A terminal record whose (id, epoch) has a requeue pending is
    # superseded-in-waiting: the re-run is scheduled but may have no
    # ActiveSample yet (parked behind the sample semaphore) — render it
    # `queued` so it surfaces in the head sort tiers instead of hiding as
    # a terminal row, and never let it supersede the re-run's live row.
    # Snapshot the pending keys *after* the summaries await (matching
    # sample_error_detail): a re-run going terminal during that await clears
    # its key on the same loop and its fresh record is in `completed` — a
    # pre-await snapshot would render that finished sample as a phantom
    # `queued` row for one response.
    requeue_pending = _pending_requeue_keys(eval_id)
    for summary in completed:
        key = (summary["sample_id"], summary["epoch"])
        if (str(summary["sample_id"]), summary["epoch"]) in requeue_pending:
            if key not in by_key:
                by_key[key] = _requeued_summary(summary)
            continue
        _merge(summary)

    # Pending: planned samples not yet running or done. No live source
    # holds these, so synthesize them from the registered planned ids.
    # Skipped for an errors-filtered read (see the docstring).
    if sample_filter != "errors":
        _add_pending_samples(eval_id, by_key)

    summaries = list(by_key.values())
    if sample_filter == "errors":
        summaries = [
            s for s in summaries if s["error"] is not None or (s["retries"] or 0) > 0
        ]
    return _sorted_samples(summaries)


class SampleListing(NamedTuple):
    """The samples listing behind ``GET /evals/<eval_id>/samples``.

    ``counts`` is the status histogram over *all* of the eval's samples —
    computed before the ``active_since`` / status filters and the row cap,
    so the aggregate answer stays complete even when ``samples`` is
    filtered or capped. It always carries every :data:`SAMPLE_STATUSES`
    key (zero when empty). ``truncated`` reports whether the row cap
    dropped rows that passed the filters — the structural "this response
    is incomplete" signal (no silent truncation).
    """

    counts: dict[str, int]
    samples: list[dict[str, Any]]
    truncated: bool


async def current_sample_listing(
    eval_id: str,
    active_since: float | None = None,
    statuses: frozenset[str] | None = None,
    limit: int | None = DEFAULT_SAMPLE_LIST_LIMIT,
    sample_filter: Literal["errors"] | None = None,
    content: bool = False,
) -> SampleListing:
    """The capped samples listing for one eval (histogram + rows).

    Builds the full per-sample summaries via
    :func:`current_sample_summaries`, then:

    - computes the ``counts`` status histogram over the full set (so the
      aggregate stays complete regardless of the filters and cap below);
    - applies the ``active_since`` recency filter and the ``statuses``
      filter (a set of :data:`SAMPLE_STATUSES` members) to the rows;
    - caps the rows at ``limit`` (``None`` = unlimited), keeping the head
      of the existing running → terminal → pending sort order — the most
      relevant rows — and flags ``truncated`` when the cap dropped any.

    ``active_since`` (unix ts) keeps samples that started or were updated
    at/after that time — i.e. ``last_activity_at >= active_since`` — the
    cheap "what changed since I last looked" delta. Pending samples (no
    activity) are excluded. It's a wall-clock *filter*, not a resume
    cursor (it returns current state of whatever changed, not an
    exactly-once stream).

    ``sample_filter="errors"`` is applied upstream in
    :func:`current_sample_summaries` (restricting to errored/retried
    samples and skipping pending-row synthesis — see its docstring), so
    under it the ``counts`` histogram covers only the filtered samples:
    the whole-eval listing is exactly what the filter exists to avoid
    building.

    ``content`` gates each row's ``error`` message — free text the evaluated
    agent can influence (tool-raised exceptions embed agent output). The
    default withholds it, leaving ``status`` / ``retries`` as the metadata
    signal, so the listing stays readable by a monitor that must never
    ingest agent-controlled text (see "Trust boundary for readers" in
    design/ctl/control-channel.md).
    """
    summaries = await current_sample_summaries(eval_id, sample_filter)

    counts = dict.fromkeys(SAMPLE_STATUSES, 0)
    for summary in summaries:
        status = summary["status"]
        counts[status] = counts.get(status, 0) + 1

    rows = summaries
    if active_since is not None:
        rows = _filter_active_since(rows, active_since)
    if statuses is not None:
        rows = [s for s in rows if s["status"] in statuses]
    if not content:
        # withhold the error message (row copies — the summaries may be the
        # memoized log read); `status` still reads "error"
        rows = [{**s, "error": None} if s.get("error") is not None else s for s in rows]

    truncated = limit is not None and len(rows) > limit
    if truncated:
        rows = rows[:limit]
    return SampleListing(counts=counts, samples=rows, truncated=truncated)


def _filter_active_since(
    summaries: list[dict[str, Any]], active_since: float
) -> list[dict[str, Any]]:
    """Samples that started or were updated at/after ``active_since``."""
    return [
        s
        for s in summaries
        if s["last_activity_at"] is not None and s["last_activity_at"] >= active_since
    ]


def _add_pending_samples(
    eval_id: str, by_key: dict[tuple[Any, int], dict[str, Any]]
) -> None:
    """Fill in not-yet-started samples from the eval's planned identities."""
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(eval_id)
    if state is None or not state.sample_ids:
        return
    for sample_id in state.sample_ids:
        for epoch in range(1, max(1, state.epochs) + 1):
            key = (sample_id, epoch)
            if key not in by_key:
                by_key[key] = _pending_summary(sample_id, epoch)


def _pending_requeue_keys(eval_id: str) -> frozenset[tuple[str, int]]:
    """The eval's requeue-pending ``(sample_id, epoch)`` keys (str-keyed).

    Non-empty only while a requeue directive has been accepted and its
    re-run hasn't reached a terminal outcome (see ``design/ctl/sample-requeue.md``).
    """
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(eval_id)
    if state is None or state.sample_requeue is None:
        return frozenset()
    return state.sample_requeue.pending_keys()


def _requeued_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """A requeue-pending terminal record, rendered as the scheduled re-run.

    Keeps the row's identity but clears the terminal fields: the prior
    outcome has been re-opened, and the fresh run hasn't started.
    ``retries`` counts what the re-run will seed — the prior retries plus
    the terminal error when genuine (a ``status == "error"`` row; a
    cancellation isn't seeded) — so the count doesn't dip when the re-run's
    ``ActiveSample`` takes over the row. ``last_activity_at`` keeps the
    prior completion time so an ``active_since`` delta still surfaces the
    row.
    """
    return {
        **summary,
        "status": "queued",
        "retries": (summary["retries"] or 0)
        + (1 if summary["status"] == "error" else 0),
        "started_at": None,
        "completed_at": None,
        "total_time": None,
        "total_tokens": 0,
        "message_count": None,
        "turn_count": None,
        "token_limit_usage": None,
        "events": None,
        "scores": {},
        "error": None,
        "limit": None,
    }


def _pending_summary(sample_id: Any, epoch: int) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "epoch": epoch,
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "total_time": None,
        "total_tokens": 0,
        "message_count": None,
        "turn_count": None,
        "token_limit_usage": None,
        "token_limit_total": None,
        "token_limit_type": None,
        "last_activity_at": None,
        "activity": None,
        "events": None,
        "scores": {},
        "error": None,
        "retries": None,
        "limit": None,
    }


def _sorted_samples(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Running first (the live ones a monitor cares about), then queued,
    # then terminal (by start time, longest-running leading), then pending
    # last. The listing cap keeps the head of this order, so each status's
    # position is an explicit, documented rank — not a tiebreak accident.
    def _rank(status: str) -> int:
        if status == "running":
            return 0
        if status == "queued":
            return 1
        if status == "pending":
            return 3
        return 2  # completed / error / cancelled

    summaries.sort(key=lambda r: (_rank(r["status"]), r["started_at"] or 0.0))
    return summaries


async def _completed_sample_summaries(eval_id: str) -> list[dict[str, Any]]:
    """The eval's completed-sample summaries (recorder, else on-disk log)."""
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(eval_id)

    # Whether a failure of this attempt will be retried — controls whether a
    # cancelled sample reads as `pending` (re-run coming) or `cancelled`.
    will_retry = state.will_retry if state is not None else False

    # Prefer the live recorder: gap-free and independent of realtime
    # logging. It returns None once torn down (eval finished) — a clean
    # signal to fall back to the log. Any other failure is unexpected and
    # propagates to the API entry point.
    if state is not None and state.live is not None:
        summaries = await state.live.sample_summaries()
        if summaries is not None:
            return [_summary_from_eval_sample_summary(s, will_retry) for s in summaries]

    # Fallback: the on-disk log. The log_location is always set on the
    # state by the time we get here (register_eval / register_completed_eval
    # set it before any sample runs), so there's no need to also consult
    # active_samples.
    if state is not None and state.log_location:
        return await _sample_summaries_from_log(state)
    return []


async def _full_sample(
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    exclude_fields: set[str] | None = None,
) -> Any | None:
    """One sample's full ``EvalSample``, gap-free — the shared terminal source.

    The single place the per-sample control reads (error detail, event pages)
    source a sample that is no longer running, so they can't disagree: prefer
    the live recorder's not-yet-flushed in-memory sample
    (``EvalState.live.read_sample`` — the same gap-free source
    :func:`current_sample_summaries` lists from), falling back to the finalized
    on-disk log when there's no live source (a reused/synthetic eval) or the
    recorder no longer holds it. ``None`` when the eval isn't in this process or
    the sample is in neither source.

    ``sample_id`` arrives as a path string. It is matched verbatim first: a
    digit-looking id such as ``"001"`` is stored (and keyed on disk) as the
    string ``"001"``, so coercing it to ``1`` would address the wrong sample.
    Only if the verbatim match misses do we retry with the integer form, which
    a genuinely-int id needs (the recorder's in-memory lookup is type-strict).
    """
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(eval_id)
    if state is None:
        return None

    sample = await _read_full_sample(state, sample_id, epoch, exclude_fields)
    if sample is None and sample_id.lstrip("-").isdigit():
        sample = await _read_full_sample(state, int(sample_id), epoch, exclude_fields)
    return sample


async def _read_full_sample(
    state: "EvalState",
    sample_id: str | int,
    epoch: int,
    exclude_fields: set[str] | None,
) -> Any | None:
    """Read one concrete ``(sample_id, epoch)`` — recorder, else on-disk log."""
    # The live logger already does recorder-then-disk; only when there's no
    # live source (reused/synthetic eval, or a superseded retry attempt whose
    # logger was detached) do we read the on-disk log directly.
    if state.live is not None:
        return await state.live.read_sample(
            sample_id, epoch, exclude_fields=exclude_fields
        )

    if not state.log_location:
        return None

    from inspect_ai.log._file import read_eval_log_sample_async

    try:
        return await read_eval_log_sample_async(
            state.log_location, sample_id, epoch, exclude_fields=exclude_fields
        )
    except (IndexError, FileNotFoundError):
        # FileNotFoundError: a superseded attempt's log removed by the
        # retry sweep while its EvalState persists (through any keep-alive
        # park) — the sample is simply no longer readable here
        return None


async def sample_error_detail(
    eval_id: str, sample_id: str, epoch: int, content: bool = False
) -> dict[str, Any] | None:
    """Summary + error detail for one sample (``GET /evals/<id>/sample?sample_id=<sid>&epoch=<n>``).

    Two sources, mirroring :func:`current_sample_summaries`:

    - **running** ← ``active_samples``: a still-running sample isn't in the
      log yet, but its prior-attempt errors (task-level seed + sample-level
      retries so far) are carried on the ``ActiveSample``. There is no current
      error while it runs.
    - **completed / finished** ← :func:`_full_sample` (recorder, then on-disk
      log): the full ``EvalSample`` is the only place the prior-attempt errors
      live in detail (``error_retries``); per-sample summaries carry just a
      retry *count*. Heavy fields (messages, events, store, attachments, output)
      are excluded — only error data is needed.

    Alongside the error history, the response carries the sample's summary
    fields (timing / tokens / messages — the same values its
    :func:`current_sample_summaries` row reports): the running path reads them
    off the same ``ActiveSample``, and the terminal path folds in the sample's
    summary row from the recorder / on-disk log. Returning them here makes
    ``inspect ctl sample show`` a single atomic read — without this it would
    have to fetch the eval's *entire* listing (O(dataset) transfer) just to
    pick one row, and a sample retrying between the two reads would tear the
    view (fresh timing merged with a prior attempt's error history).
    ``status``/``error`` follow the listing's classification: a cancellation
    is never ``error`` — it reads as ``pending``/``cancelled`` with the
    cancellation repr suppressed (:func:`_cancellation_status`).

    ``content`` gates the error free text (message / tracebacks) — strings
    the evaluated agent can influence. The default withholds them: each
    error renders as an empty dict, so presence (and the ``retries`` count)
    stays readable by a monitor that must never ingest agent-controlled
    text (see "Trust boundary for readers" in design/ctl/control-channel.md).

    Returns ``None`` when the eval isn't in this process, or the sample isn't
    running and isn't readable yet — the endpoint turns that into a 404.
    """
    # Running sample first: it isn't in the log yet, and active_samples is the
    # only place its in-flight error history lives.
    running = _running_sample_error_detail(eval_id, sample_id, epoch, content)
    if running is not None:
        return running

    sample = await _full_sample(
        eval_id,
        sample_id,
        epoch,
        exclude_fields={"messages", "events", "store", "attachments", "output"},
    )
    if sample is None:
        return None

    # The sample's summary row supplies the summary fields (timing / tokens /
    # messages) the heavy-field-excluded EvalSample can't fully provide
    # (message_count needs the excluded messages). Same source as the listing,
    # so the two views agree on them; the detail fields below override on
    # overlap. A missing row (unexpected — the full sample was just readable)
    # degrades to the detail fields alone.
    row = next(
        (
            r
            for r in await _completed_sample_summaries(eval_id)
            if str(r["sample_id"]) == str(sample.id) and r["epoch"] == sample.epoch
        ),
        None,
    )

    # A pending requeue re-opens the terminal outcome: mirror the listing's
    # rendering (the scheduled re-run — `queued`, terminal fields cleared)
    # and echo the requeue in the error history the way the re-run will seed
    # it: prior retries plus the terminal error when genuine (a cancellation
    # isn't seeded — see `_seed_error_retries`). Same rule as the listing,
    # so the two views can't drift during the pending window.
    if (str(sample.id), sample.epoch) in _pending_requeue_keys(eval_id):
        seeded = list(sample.error_retries or [])
        if sample.error is not None and not is_cancellation_message(
            sample.error.message
        ):
            seeded.append(sample.error)
        return {
            **(_requeued_summary(row) if row is not None else {}),
            "sample_id": sample.id,
            "epoch": sample.epoch,
            "status": "queued",
            "retries": len(seeded),
            "error": None,
            "error_retries": [_error_dict(e, content) for e in seeded],
            "scores": {},
        }

    # status/error apply the listing's classification
    # (_summary_from_eval_sample_summary reads the same error message), so the
    # detail's override of the row can't contradict it: a cancellation is
    # never an error — it reads as pending/cancelled with the repr suppressed.
    status: str
    error: dict[str, Any] | None
    if sample.error is None:
        status, error = "completed", None
    elif is_cancellation_message(sample.error.message):
        status, error = _cancellation_status(_eval_will_retry(eval_id)), None
    else:
        status, error = "error", _error_dict(sample.error, content)

    return {
        **(row or {}),
        "sample_id": sample.id,
        "epoch": sample.epoch,
        "status": status,
        "retries": len(sample.error_retries) if sample.error_retries else 0,
        "error": error,
        "error_retries": [
            _error_dict(e, content) for e in (sample.error_retries or [])
        ],
        "scores": {name: score.value for name, score in (sample.scores or {}).items()},
    }


def find_active_sample(
    eval_id: str, sample_id: str, epoch: int
) -> "ActiveSample | None":
    """The process's live sample matching ``(eval_id, sample_id, epoch)``, or ``None``.

    The single definition of the control channel's active-sample identity
    rule, shared by the error-detail, transcript-events, and cancel surfaces:
    ``sample_id`` arrives as a query-param string, so integer ids match on
    ``str(sample.id)``.
    """
    from inspect_ai.log._samples import active_samples

    for sample in active_samples():
        if (
            sample.eval_id == eval_id
            and str(sample.sample.id) == sample_id
            and sample.epoch == epoch
        ):
            return sample
    return None


def _running_sample_error_detail(
    eval_id: str, sample_id: str, epoch: int, content: bool = False
) -> dict[str, Any] | None:
    """Summary + error detail for a sample currently running in this process, or None.

    A running sample has no current error yet; its ``error_retries`` are the
    prior failed attempts seeded onto the ``ActiveSample``. A terminal sample
    still in ``active_samples`` is left to the on-disk log (which carries the
    final ``error_retries``). The summary fields come from the same
    ``ActiveSample`` row the listing reports (:func:`_active_sample_summary`),
    read in the same pass as the error history — one atomic view. That
    includes ``status``: a matched sample that hasn't started yet reads
    ``queued``, as in the listing, rather than a hardcoded ``running``.
    """
    s = find_active_sample(eval_id, sample_id, epoch)
    if s is None or s.completed is not None:
        return None
    return {
        **_active_sample_summary(s),
        "retries": s.retries,
        "error_retries": [_error_dict(e, content) for e in s.error_retries],
    }


def _error_dict(error: Any, content: bool) -> dict[str, Any]:
    """Serialize an EvalError / EvalRetryError (message + traceback) to a dict.

    Without ``content`` the free-text fields are withheld — the dict is empty
    but non-``None``, so consumers still see that an error occurred (its
    text is agent-influenced; see :func:`sample_error_detail`).
    """
    if not content:
        return {}
    return {
        "message": error.message,
        "traceback": error.traceback,
        "traceback_ansi": error.traceback_ansi,
    }


async def _sample_summaries_from_log(state: "EvalState") -> list[dict[str, Any]]:
    """Completed-sample summaries read from the on-disk log, memoized.

    Only reached when the live recorder is unavailable (a reused eval, a
    finished eval whose recorder was torn down, or a superseded retry
    attempt whose providers were detached), so the log is finalized and
    immutable — the first request's read (possibly against S3, with
    ``EvalSampleSummary`` validation per sample) is cached on the state
    (``EvalState.log_sample_summaries``) and later requests are served from
    memory; a keep-alive-parked process polled every 30s must not re-pay it
    per poll. Concurrent first requests may each read (benign: identical
    immutable data, no await between the read completing and the memo
    write). The memo write needs no registry lock for the same reason
    ``_build_summary``'s ``observe_started`` fold doesn't: all writers run
    on the eval's loop.

    The log may however no longer *exist*: the retry sweep
    (``retry_cleanup``) deletes superseded attempts' logs while their
    EvalStates persist through any keep-alive park (clearing the memo as it
    does — see ``invalidate_log_sample_summaries``) — degrade to an empty
    listing, without memoizing it, rather than failing the request. Any
    other read error is unexpected and propagates to the API entry point.
    """
    summaries = state.log_sample_summaries
    if summaries is None:
        from inspect_ai.log._file import read_eval_log_sample_summaries_async

        try:
            summaries = await read_eval_log_sample_summaries_async(state.log_location)
        except FileNotFoundError:
            return []
        state.log_sample_summaries = summaries
    return [_summary_from_eval_sample_summary(s, state.will_retry) for s in summaries]


def _cancellation_status(will_retry: bool) -> str:
    """How a cancelled sample's status reads — never ``error``.

    A cancellation isn't a genuine error: the sample was torn down because a
    sibling failed (or the eval was cancelled). It reads as ``pending`` when a
    retry will re-run it, else ``cancelled``. Shared by the listing
    (:func:`_summary_from_eval_sample_summary`) and the per-sample detail
    (:func:`sample_error_detail`) so the two views can't drift.
    """
    return "pending" if will_retry else "cancelled"


def _eval_will_retry(eval_id: str) -> bool:
    """Whether a failure of the eval's current attempt will be retried."""
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(eval_id)
    return state is not None and state.will_retry


def _summary_from_eval_sample_summary(
    summary: Any, will_retry: bool = False
) -> dict[str, Any]:
    error = summary.error
    if error is not None and is_cancellation_message(error):
        # the cancellation message itself isn't surfaced as an error
        status = _cancellation_status(will_retry)
        error = None
    elif error is not None:
        status = "error"
    elif summary.completed:
        status = "completed"
    else:
        status = "running"

    return {
        "sample_id": summary.id,
        "epoch": summary.epoch,
        "status": status,
        "started_at": _iso_to_timestamp(summary.started_at),
        "completed_at": _iso_to_timestamp(summary.completed_at),
        "total_time": summary.total_time,
        "total_tokens": sum(u.total_tokens for u in summary.model_usage.values()),
        "message_count": summary.message_count,
        "turn_count": summary.turn_count,
        "token_limit_usage": summary.token_limit_usage,
        "token_limit_total": summary.token_limit,
        "token_limit_type": summary.token_limit_type,
        # A terminal sample's last activity is its completion; `events` is a
        # live-only progress counter (the on-disk summary doesn't carry it)
        # and `activity` a live-only in-flight indicator.
        "last_activity_at": _iso_to_timestamp(summary.completed_at),
        "activity": None,
        "events": None,
        "scores": {name: score.value for name, score in (summary.scores or {}).items()},
        "error": error,
        "retries": summary.retries,
        "limit": summary.limit,
    }


def _sample_summaries_from_active(eval_id: str) -> list[dict[str, Any]]:
    """The eval's currently in-flight samples (the running source)."""
    from inspect_ai.log._samples import active_samples

    return [_active_sample_summary(s) for s in active_samples() if s.eval_id == eval_id]


def _active_sample_summary(s: "ActiveSample") -> dict[str, Any]:
    """One in-flight sample's summary row, read off its ``ActiveSample``.

    The single source of a live sample's summary fields — shared by the
    listing (:func:`_sample_summaries_from_active`) and the per-sample detail
    (:func:`_running_sample_error_detail`) so the two views can't drift.
    """
    if s.completed is not None:
        status = "completed"
    elif s.started is not None:
        status = "running"
    else:
        status = "queued"
    # Liveness signals (the only freshest source is the in-memory
    # transcript). `last_activity_at` is when the sample last produced an
    # event; `events` is a monotonic count. Together they let a consumer
    # tell "stalled" from "working" without diffing successive polls — the
    # per-turn token/message counters don't move *within* an in-flight
    # model call, but these advance on every model / tool / store event.
    # Neither moves *during* one long model call (the pending ModelEvent is
    # appended at call start and updated in place on return), which is what
    # `activity` exists to disambiguate: it names the in-flight operation so
    # a sample mid-generate doesn't read as silently idle
    # (design/ctl/generate-progress.md).
    last_event = s.transcript.history.last_event
    last_activity_at = (
        last_event.timestamp.timestamp() if last_event is not None else s.started
    )
    return {
        "sample_id": s.sample.id,
        "epoch": s.epoch,
        "status": status,
        "started_at": s.started,
        "completed_at": s.completed,
        "total_time": s.running_time,
        "total_tokens": s.total_tokens,
        "message_count": s.total_messages,
        "turn_count": s.total_turns,
        "token_limit_usage": s.token_limit_usage,
        "token_limit_total": s.token_limit,
        "token_limit_type": s.token_limit_type,
        "last_activity_at": last_activity_at,
        "activity": _sample_activity(s) if status == "running" else None,
        "events": s.transcript.history.event_count,
        "scores": {},  # running samples aren't scored yet
        "error": None,
        "retries": s.retries or None,
        "limit": None,
    }


def _sample_activity(s: "ActiveSample") -> dict[str, Any] | None:
    """The running sample's in-flight operation, or ``None`` when nothing is.

    Reads the transcript's ``pending_events`` sidecar — O(in-flight ops),
    never an event scan (the samples handler shares the eval's event loop;
    see the cost-audit note in design/ctl/generate-progress.md) — and
    classifies as the TUI does (``SampleToolbar.sync_sample``): any pending
    ``ToolEvent`` → tool activity (the earliest one leads, even when a
    nested model call is also pending); else a pending ``ModelEvent`` →
    model activity; else a generate retry backoff recorded on the sample
    (no pending event exists during the wait) → ``retry_wait``.

    The shape is stable across types so ``jq`` consumers see every key:
    ``type`` / ``count`` / ``started_at`` / ``detail`` always carry values
    (``count`` is the concurrent pending ops of the type — for
    ``retry_wait``, the failed attempt number; ``detail`` the model name or
    tool function); ``retries`` is the pending model call's in-call
    (provider-SDK) retries; ``deadline`` is when a ``retry_wait`` elapses;
    ``tokens`` / ``last_progress_at`` are reserved for the layer-2 progress
    channel and ``None`` until it ships.
    """
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.event._tool import ToolEvent

    first_model: ModelEvent | None = None
    model_count = 0
    first_tool: ToolEvent | None = None
    tool_count = 0
    for ev in s.transcript.pending_events:
        if isinstance(ev, ModelEvent):
            if first_model is None:
                first_model = ev
            model_count += 1
        elif isinstance(ev, ToolEvent):
            if first_tool is None:
                first_tool = ev
            tool_count += 1

    if first_tool is not None:
        return _activity(
            "tool", tool_count, first_tool.timestamp.timestamp(), first_tool.function
        )
    if first_model is not None:
        return _activity(
            "model",
            model_count,
            first_model.timestamp.timestamp(),
            first_model.model,
            retries=first_model.retries or None,
        )
    retry_wait = s.retry_wait
    if retry_wait is not None:
        return _activity(
            "retry_wait",
            retry_wait.attempt,
            retry_wait.started_at,
            retry_wait.model,
            deadline=retry_wait.deadline,
        )
    return None


def _activity(
    type: str,
    count: int,
    started_at: float,
    detail: str,
    *,
    retries: int | None = None,
    deadline: float | None = None,
) -> dict[str, Any]:
    return {
        "type": type,
        "count": count,
        "started_at": started_at,
        "detail": detail,
        "retries": retries,
        "deadline": deadline,
        "tokens": None,
        "last_progress_at": None,
    }


def _iso_to_timestamp(value: str | None) -> float | None:
    if not value:
        return None
    from inspect_ai._util.dateutil import datetime_from_iso_format_safe

    try:
        return datetime_from_iso_format_safe(value).timestamp()
    except (ValueError, TypeError):
        return None


def _build_summary(
    *,
    latest: "EvalState",
    states: list["EvalState"],
    samples: list["ActiveSample"],
    attempts: int,
    started_at_fallback: float,
) -> dict[str, Any]:
    """Build one summary entry from the latest attempt + its live samples.

    The latest attempt's counters are authoritative — under
    ``retry_immediate=True`` each retry's ``completed`` includes the
    reused successes from prior attempts, so summing across attempts
    would double-count. ``errored`` likewise reflects the latest
    attempt only (a sample that errored on attempt 1 and succeeded on
    attempt 2 shouldn't read as "errored" in the surface).

    ``refusals`` / ``http_retries`` are the exception and are summed over
    ``states`` (every attempt of this task). They count things that HAPPENED
    rather than describing current state, so a retry must not discard the prior
    attempt's tally — and it is the failed attempt whose retries you most want to
    see, since a provider problem bad enough to fail a task is what triggered the
    retry. Summing is safe where it isn't for ``completed`` because the attempts
    are disjoint: a reused sample is never re-run, so it emits no new events, and
    nothing seeds these from a reused log (they are not recorded in one).
    """
    first_sample = samples[0] if samples else None
    task_name = first_sample.task if first_sample else latest.task
    model = first_sample.model if first_sample else latest.model
    run_id = first_sample.run_id if first_sample else latest.run_id

    # Pin the eval's start to its earliest sample start, tracked as a running
    # minimum on the EvalState. ``samples`` only holds *currently active*
    # samples, so a plain min over it creeps forward as early samples finish
    # and leave ``active_samples`` (#4305); fold the live minimum into
    # ``latest.started_at`` to keep it fixed. The terminal records
    # (``record_sample_*``) feed the same running minimum, so a sample that
    # finished before this first poll is already accounted for. Both this fold
    # and those records run on the eval's loop, so the writes are serialised.
    sample_starts = [s.started for s in samples if s.started is not None]
    if sample_starts:
        latest.observe_started(min(sample_starts))
    eval_started_at = (
        latest.started_at if latest.started_at is not None else started_at_fallback
    )

    from inspect_ai._control.pause import task_dispatched_count, task_pause_sources

    in_flight_samples = [
        s for s in samples if s.started is not None and s.completed is None
    ]
    in_flight = len(in_flight_samples)
    total = latest.total
    completed = latest.completed
    errored = latest.errored
    cancelled = latest.cancelled
    queued = max(0, total - completed - errored - cancelled - in_flight)
    completed_at = latest.completed_at
    status = "completed" if completed_at is not None else "running"

    # which pause latches hold the task (None when dispatchable — else the
    # non-empty source list), and whether it has quiesced — paused with
    # nothing dispatched, the "safe to kill" signal for the durable-pause
    # workflow (design/ctl/pause-resume.md). A finished task reports
    # neither (there is nothing left to hold) — but a task *between
    # attempts* (completed_at set, retry pending) is still holdable (the
    # gate parks its queued retry, the same guard pause_task uses), so it
    # keeps reporting its pause sources. quiesced uses the gate-boundary
    # dispatched count rather than in_flight: a sample past the gate but
    # still initializing (started=None, or not yet registered in
    # active_samples at all) will run once its sandbox is up, and "safe to
    # kill" must not flip true→false in that window (see
    # task_dispatched_count in pause.py).
    paused = (
        task_pause_sources(latest.task_id, latest.model or None) or None
        if completed_at is None or latest.retry_pending
        else None
    )
    quiesced = paused is not None and task_dispatched_count(latest.task_id) == 0

    # Usage = the accumulated total for terminal samples (survives them
    # leaving active_samples — "usage so far") plus the live usage of the
    # in-flight ones. A sample is in exactly one bucket: it's accumulated at
    # its terminal outcome, which fires after it leaves active_samples.
    total_tokens = latest.total_tokens + sum(s.total_tokens for s in in_flight_samples)
    total_messages = latest.total_messages + sum(
        s.total_messages for s in in_flight_samples
    )
    # Same two-term shape, and for the same reason: the eval totals cover samples
    # that have left `active_samples`, the live sum covers the ones still in it.
    # Reading these live matters more than it does for usage — a refusal or a
    # retry storm is worth knowing about while the run can still be steered, and
    # on a long-episode benchmark no sample may finish for hours. Note the totals
    # are summed over EVERY attempt, not read off `latest` (see the docstring).
    refusals = sum(s.refusals for s in states) + sum(
        s.refusals for s in in_flight_samples
    )
    http_retries = sum(s.http_retries for s in states) + sum(
        s.http_retries for s in in_flight_samples
    )

    return {
        "run_id": run_id,
        "eval_id": latest.eval_id,
        "task": task_name,
        "task_id": latest.task_id,
        "model": model,
        "solver": latest.solver,
        # Where this attempt's results are written — lets an agent monitoring a
        # run it didn't launch find the log without knowing the launch args.
        # `local_path` drops the `file://` prefix for local logs (leaving
        # `s3://` and plain paths as-is) so the value is directly usable.
        "log_location": local_path(latest.log_location),
        "status": status,
        "started_at": eval_started_at,
        "completed_at": completed_at,
        "paused": paused,
        "quiesced": quiesced,
        "attempts": attempts,
        # Planned epoch count. `ctl sample cancel` uses it to require an
        # explicit EPOCH when the task runs more than one (a defaulted epoch
        # would silently target a different sample — see the selector
        # conventions in design/ctl/control-channel.md).
        "epochs": latest.epochs,
        "samples": {
            "total": total,
            "completed": completed,
            "errored": errored,
            "cancelled": cancelled,
            "in_flight": in_flight,
            "queued": queued,
        },
        "total_tokens": total_tokens,
        "total_messages": total_messages,
        "refusals": refusals,
        "http_retries": http_retries,
    }
