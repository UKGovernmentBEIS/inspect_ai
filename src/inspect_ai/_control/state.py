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
from typing import TYPE_CHECKING, Any

from inspect_ai._util._async import tg_collect
from inspect_ai._util.error import is_cancellation_message
from inspect_ai._util.file import local_path

if TYPE_CHECKING:
    from inspect_ai._control.eval_state import EvalState
    from inspect_ai.log._samples import ActiveSample


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
        ``{total, completed, errored, in_flight, queued}``, and an
        ``attempts`` count (1 for tasks without retries, >1 when
        retries occurred).
    """
    # Lazy imports to avoid pulling the full log/event/scorer chain at
    # module-import time (control server module is imported during
    # eval bootstrap before those packages finish initialising).
    from inspect_ai._control.eval_state import (
        get_eval_states,
        resolve_deferred_sample_stats,
    )
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
            }
        )

    summaries.sort(key=lambda s: s["started_at"])
    return summaries


async def current_sample_summaries(
    eval_id: str, active_since: float | None = None
) -> list[dict[str, Any]]:
    """Per-sample summaries for one eval (``GET /evals/<eval_id>/samples``).

    Lists *all* of the eval's samples — running, completed, and pending —
    from three sources, since none is complete on its own for a live eval:

    - **running** ← ``active_samples`` (the only place a running sample
      exists; freshest live detail).
    - **completed** ← the recorder's in-memory summaries while the eval
      runs (gap-free, ahead of disk; via ``EvalState.live.sample_summaries``),
      falling back to the finalized on-disk log once the recorder is gone
      (eval finished / torn down).
    - **pending** ← synthesized from the eval's registered planned
      ``(sample_id, epoch)`` pairs (``EvalState.sample_ids`` × ``epochs``)
      that aren't yet running or done — no live source holds these.

    Merged and deduped by ``(sample_id, epoch)``; a terminal record
    (completed / error) supersedes a running one, which supersedes a
    pending one. Sorted running → terminal → pending. Returns an empty
    list when the eval isn't in this process.

    Each entry has: ``sample_id``, ``epoch``, ``status`` (running /
    completed / error / pending), ``started_at``, ``completed_at``,
    ``total_time``, ``total_tokens``, ``message_count``,
    ``last_activity_at`` (unix ts of the sample's most recent event — for a
    running sample, ``now - last_activity_at`` is its idle time, a cheap
    stall signal), ``events`` (live transcript event count; ``None`` for
    terminal / pending samples), ``scores`` (``{scorer: value}``, empty
    until scored), ``error``, ``retries``, ``limit``.

    ``active_since`` (unix ts) restricts the result to samples that started or
    were updated at/after that time — i.e. ``last_activity_at >= active_since``
    — the cheap "what changed since I last looked" delta. Pending samples (no
    activity) are excluded. It's a wall-clock *filter*, not a resume cursor (it
    returns current state of whatever changed, not an exactly-once stream).
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
    for summary in await _completed_sample_summaries(eval_id):
        _merge(summary)

    # Pending: planned samples not yet running or done. No live source
    # holds these, so synthesize them from the registered planned ids.
    _add_pending_samples(eval_id, by_key)

    summaries = list(by_key.values())
    if active_since is not None:
        summaries = [
            s
            for s in summaries
            if s["last_activity_at"] is not None
            and s["last_activity_at"] >= active_since
        ]
    return _sorted_samples(summaries)


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
        "events": None,
        "scores": {},
        "error": None,
        "retries": None,
        "limit": None,
    }


def _sorted_samples(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Running first (the live ones a monitor cares about), then terminal
    # (by start time, longest-running leading), then pending last.
    def _rank(status: str) -> int:
        if status == "running":
            return 0
        if status == "pending":
            return 2
        return 1  # completed / error

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
        return await _sample_summaries_from_log(state.log_location, will_retry)
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
    eval_id: str, sample_id: str, epoch: int
) -> dict[str, Any] | None:
    """Full error detail for one sample (``GET /evals/<id>/sample?sample_id=<sid>&epoch=<n>``).

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

    Returns ``None`` when the eval isn't in this process, or the sample isn't
    running and isn't readable yet — the endpoint turns that into a 404.
    """
    # Running sample first: it isn't in the log yet, and active_samples is the
    # only place its in-flight error history lives.
    running = _running_sample_error_detail(eval_id, sample_id, epoch)
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

    return {
        "sample_id": sample.id,
        "epoch": sample.epoch,
        "status": "error" if sample.error is not None else "completed",
        "retries": len(sample.error_retries) if sample.error_retries else 0,
        "error": _error_dict(sample.error) if sample.error is not None else None,
        "error_retries": [_error_dict(e) for e in (sample.error_retries or [])],
        "scores": {name: score.value for name, score in (sample.scores or {}).items()},
    }


def _running_sample_error_detail(
    eval_id: str, sample_id: str, epoch: int
) -> dict[str, Any] | None:
    """Error detail for a sample currently running in this process, or None.

    A running sample has no current error yet; its ``error_retries`` are the
    prior failed attempts seeded onto the ``ActiveSample``. A terminal sample
    still in ``active_samples`` is left to the on-disk log (which carries the
    final ``error_retries``).
    """
    from inspect_ai.log._samples import active_samples

    for s in active_samples():
        if s.eval_id == eval_id and str(s.sample.id) == sample_id and s.epoch == epoch:
            if s.completed is not None:
                return None
            return {
                "sample_id": s.sample.id,
                "epoch": s.epoch,
                "status": "running",
                "retries": s.retries,
                "error": None,
                "error_retries": [_error_dict(e) for e in s.error_retries],
                "scores": {},
            }
    return None


def _error_dict(error: Any) -> dict[str, Any]:
    """Serialize an EvalError / EvalRetryError (message + traceback) to a dict."""
    return {
        "message": error.message,
        "traceback": error.traceback,
        "traceback_ansi": error.traceback_ansi,
    }


async def _sample_summaries_from_log(
    location: str, will_retry: bool = False
) -> list[dict[str, Any]]:
    """Completed-sample summaries read from the on-disk log.

    Only reached when the live recorder is unavailable (a reused eval, a
    finished eval whose recorder was torn down, or a superseded retry
    attempt whose providers were detached), so the log is finalized. It may
    however no longer *exist*: the retry sweep (``retry_cleanup``) deletes
    superseded attempts' logs while their EvalStates persist through any
    keep-alive park — degrade to an empty listing rather than failing the
    request. Any other read error is unexpected and propagates to the API
    entry point.
    """
    from inspect_ai.log._file import read_eval_log_sample_summaries_async

    try:
        summaries = await read_eval_log_sample_summaries_async(location)
    except FileNotFoundError:
        return []
    return [_summary_from_eval_sample_summary(s, will_retry) for s in summaries]


def _summary_from_eval_sample_summary(
    summary: Any, will_retry: bool = False
) -> dict[str, Any]:
    error = summary.error
    if error is not None and is_cancellation_message(error):
        # A cancellation isn't a genuine error — the sample was torn down
        # because a sibling failed (or the eval was cancelled). It reads as
        # `pending` when a retry will re-run it, else `cancelled`. Either way
        # the cancellation message itself isn't surfaced as an error.
        status = "pending" if will_retry else "cancelled"
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
        # The on-disk summary carries metered usage but not the configured
        # ceiling or metering type, so those are unavailable for terminal rows.
        "token_limit_total": None,
        "token_limit_type": None,
        # A terminal sample's last activity is its completion; `events` is a
        # live-only progress counter (the on-disk summary doesn't carry it).
        "last_activity_at": _iso_to_timestamp(summary.completed_at),
        "events": None,
        "scores": {name: score.value for name, score in (summary.scores or {}).items()},
        "error": error,
        "retries": summary.retries,
        "limit": summary.limit,
    }


def _sample_summaries_from_active(eval_id: str) -> list[dict[str, Any]]:
    """The eval's currently in-flight samples (the running source)."""
    from inspect_ai.log._samples import active_samples

    summaries: list[dict[str, Any]] = []
    for s in active_samples():
        if s.eval_id != eval_id:
            continue
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
        last_event = s.transcript.history.last_event
        last_activity_at = (
            last_event.timestamp.timestamp() if last_event is not None else s.started
        )
        summaries.append(
            {
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
                "events": s.transcript.history.event_count,
                "scores": {},  # running samples aren't scored yet
                "error": None,
                "retries": s.retries or None,
                "limit": None,
            }
        )
    return summaries


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

    # Usage = the accumulated total for terminal samples (survives them
    # leaving active_samples — "usage so far") plus the live usage of the
    # in-flight ones. A sample is in exactly one bucket: it's accumulated at
    # its terminal outcome, which fires after it leaves active_samples.
    total_tokens = latest.total_tokens + sum(s.total_tokens for s in in_flight_samples)
    total_messages = latest.total_messages + sum(
        s.total_messages for s in in_flight_samples
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
        "attempts": attempts,
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
    }
