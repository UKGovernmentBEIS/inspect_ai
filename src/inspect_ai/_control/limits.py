"""Modify-limits directive for the control channel.

Reads (and optionally retunes) a running task's concurrency limits mid-flight —
``max_samples`` (per-task sample concurrency) and ``max_sandboxes`` (per-provider
sandbox concurrency, process-global). The first of the phase-3 modify directives
(see ``design/control-channel.md``). Keyed by task_id — the identity that is
stable across retry attempts — via ``GET``/``PATCH /tasks/<task-id>/config``.

Both knobs are backed by a :class:`~inspect_ai.util._concurrency.ResizableLimiter`
whose limit is settable at runtime: lowering it below the current in-use count
blocks new acquires until in-flight holders drain — it never preempts. Raising it
lets more work start immediately. ``max_samples`` is reached through
the task_id-keyed sample-semaphore registry (populated by the runner, shared
across a task's retry attempts); ``max_sandboxes`` through
the process-global sandbox-limiter registry, since sandbox concurrency is shared
across the process's evals rather than owned by one.

On the adaptive-connections path ``max_samples`` isn't a user setpoint (sample
concurrency tracks the model-API controller), so it's reported as not adjustable;
``max_connections`` retunes the controllers' scaling ceiling (``max``) instead —
lowering it clamps live concurrency down at once (blocking new acquires until
in-flight drains, never preempting), raising it lets the controllers climb higher
on subsequent clean rounds. The view carries an ``adaptive`` section reporting
each controller's live limit, in-flight count, scaling bounds, and recent scale
changes, so the path is observable rather than opaque.

:func:`task_limits` returns ``None`` when the task isn't in this process — the
endpoint turns that into a 404. When a requested knob has no adjustable limiter
(the adaptive sample-concurrency path, or a run with no sandbox limit in
effect), the value is applied to nothing and a warning is included rather than
failing the whole request — so a caller adjusting several knobs still gets the
ones that apply.

Since ``max_sandboxes`` and ``max_connections`` are process-global (shared across
the process's tasks), :func:`process_limits` exposes them without a task — the
process-level ``GET``/``PATCH /config`` endpoint — for the common case of viewing
or throttling a whole process without naming one of its tasks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from inspect_ai._util.name_match import match_name_prefix

if TYPE_CHECKING:
    from inspect_ai.util._concurrency import AdaptiveConcurrencyController

# How many of an adaptive controller's most-recent scale changes to surface in
# the read view — enough to see whether it's actively being throttled without
# dumping the controller's full bounded history.
_RECENT_CHANGES = 5


async def process_limits(
    *,
    max_sandboxes: int | None = None,
    max_connections: int | None = None,
    model: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Read (and optionally retune) the process-global concurrency limits.

    Covers the knobs that are shared across every task in the process:
    ``max_sandboxes`` (per-provider sandbox concurrency) and ``max_connections``
    (the adaptive controllers' scaling ceiling). It carries no ``max_samples`` —
    that is per-task; use :func:`task_limits` when a specific task is in view.

    A process always exists, so unlike :func:`task_limits` this never returns
    ``None``. With both knobs ``None`` it's a pure read. ``model`` restricts the
    adaptive controllers considered (matched at name start or after a ``/``).
    """
    views = _apply_process_knobs(
        max_sandboxes=max_sandboxes,
        max_connections=max_connections,
        model=model,
        dry_run=dry_run,
    )
    return {
        "dry_run": dry_run,
        "max_sandboxes": views.max_sandboxes,
        "adaptive": views.adaptive,
        "requested": views.requested or None,
        "warnings": views.warnings,
    }


async def task_limits(
    task_id: str,
    *,
    max_samples: int | None = None,
    max_sandboxes: int | None = None,
    max_connections: int | None = None,
    model: str | None = None,
    log_buffer: int | None = None,
    log_shared: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Read (and optionally retune) a task's retunable config.

    A superset of :func:`process_limits`: it adds the per-task knobs — the
    ``max_samples`` sample concurrency plus the ``log_buffer`` / ``log_shared``
    sample-buffer params — to the process-global ``max_sandboxes`` /
    ``max_connections`` view. Task-scoped state lives in task_id-keyed
    registries: the sample limiter is read straight from the task-semaphore
    registry (shared across the task's retry attempts — see
    ``_task_sample_semaphores``), the buffer params through the latest
    attempt's live logger (see :mod:`inspect_ai._control.buffer`) — resolved
    once here, which doubles as the existence check. With all knobs ``None``
    this is a pure read. Returns ``None`` when the task isn't tracked in this
    process (the endpoint turns that into a 404); reused-log tasks are
    tracked (registered from their headers) and report their knobs as not
    adjustable rather than 404ing. Keyed by task_id — stable across retries —
    rather than a per-attempt eval id, so a caller's handle never goes stale
    mid-run.

    On the adaptive path the task's semaphore is a ``DynamicSampleLimiter``
    (sample concurrency tracks the controller, not a user setpoint), so
    ``max_samples`` is reported as not adjustable; ``max_connections`` retunes
    the controllers' scaling ceiling instead — lowering it clamps live
    concurrency down immediately, raising it lets the controller climb higher
    on subsequent clean rounds.

    Args:
        task_id: The target task (stable across retry attempts).
        max_samples: New sample-concurrency limit, or ``None`` to leave it.
        max_sandboxes: New per-provider sandbox-concurrency limit, or ``None``.
        max_connections: New adaptive-controller scaling ceiling (applied to
            every adaptive controller in the process), or ``None`` to leave it.
        model: Restrict the adaptive controllers ``max_connections`` targets (and
            the reported adaptive view) to those matching, or ``None`` for all.
        log_buffer: New completed-samples-per-log-write buffer threshold, or
            ``None`` to leave it.
        log_shared: New shared-log event sync interval (seconds), or ``None``.
        dry_run: When set, validate and report the intended change without
            applying it.
    """
    from inspect_ai._control.buffer import state_buffer_config
    from inspect_ai._control.eval_state import latest_eval_for_task
    from inspect_ai.util._concurrency import (
        DynamicSampleLimiter,
        ResizableLimiter,
        task_sample_semaphore,
    )

    latest = latest_eval_for_task(task_id)
    if latest is None:
        return None

    # max_samples — the task's sample semaphore. Only a ResizableLimiter is a
    # user setpoint; a DynamicSampleLimiter (adaptive path) or a missing entry
    # (reused-log task, or one that ran no samples here) isn't adjustable.
    sample_requested: dict[str, int] = {}
    sample_warnings: list[str] = []
    semaphore = task_sample_semaphore(task_id)
    sample_limiter = semaphore if isinstance(semaphore, ResizableLimiter) else None
    if max_samples is not None:
        sample_requested["max_samples"] = max_samples
        if sample_limiter is None:
            sample_warnings.append(
                "max_samples is not adjustable for this task (it uses adaptive "
                "connection concurrency, or ran no samples in this process)."
            )
        elif not dry_run:
            sample_limiter.limit = max_samples

    # a DynamicSampleLimiter that never found its model's controller means
    # sample concurrency is stuck at its starting value — generates may be
    # flowing through a different model (roles / agent bridge), or the model's
    # connection key changed after creation. Surface it; nothing else does.
    if isinstance(semaphore, DynamicSampleLimiter) and semaphore.controller is None:
        sample_warnings.append(
            "sample concurrency is adaptive but no matching connection "
            "controller exists — if generates flow through a different model "
            "(e.g. model roles or an agent bridge), sample concurrency stays "
            "at its starting value."
        )

    # log_buffer / log_shared — the sample-buffer params, task-scoped like
    # max_samples but reached through the latest attempt's live logger. A
    # task with no live buffer (a reused log, or a superseded attempt) has a
    # None view; an explicit set then warns like the other unadjustable
    # knobs, so the wire contract is consistent for raw-API consumers (the
    # CLI additionally escalates that set to a hard error client-side).
    if log_buffer is not None:
        sample_requested["log_buffer"] = log_buffer
    if log_shared is not None:
        sample_requested["log_shared"] = log_shared
    buffer_view = state_buffer_config(
        latest,
        log_buffer=log_buffer if not dry_run else None,
        log_shared=log_shared if not dry_run else None,
    )
    if buffer_view is None and (log_buffer is not None or log_shared is not None):
        sample_warnings.append(
            "log_buffer/log_shared are not adjustable for this task (no live "
            "sample buffer — e.g. a reused log, or a superseded retry attempt)."
        )
    # a buffer with no shared-log sync running silently ignores a log_shared
    # set (`set_sync_interval` reports the rejection but `buffer_config`
    # keeps only the resulting view) — the view echoing `log_shared: None`
    # after a request is that rejection, so warn like the other unadjustable
    # knobs. Holds under dry_run too: a syncless buffer always reports None.
    if (
        log_shared is not None
        and buffer_view is not None
        and buffer_view.get("log_shared") is None
    ):
        sample_warnings.append(
            "log_shared is not adjustable for this task (its log has no "
            "shared-log sync running — launch with --log-shared to enable it)."
        )

    views = _apply_process_knobs(
        max_sandboxes=max_sandboxes,
        max_connections=max_connections,
        model=model,
        dry_run=dry_run,
    )
    # per-task entries lead, then the process-global ones
    requested = {**sample_requested, **views.requested}
    warnings = sample_warnings + views.warnings

    # `tracks_adaptive` distinguishes the adaptive path (sample concurrency
    # follows this task's controller) from a task with no live limiter at all
    # (reused log / ran no samples here) — the renderer must not claim the
    # latter tracks anything.
    max_samples_view: dict[str, Any]
    if sample_limiter is not None:
        max_samples_view = {
            "limit": sample_limiter.limit,
            "in_use": sample_limiter.in_use,
            "adjustable": True,
        }
    else:
        max_samples_view = {
            "adjustable": False,
            "tracks_adaptive": isinstance(semaphore, DynamicSampleLimiter),
        }

    return {
        "dry_run": dry_run,
        "max_samples": max_samples_view,
        "max_sandboxes": views.max_sandboxes,
        "adaptive": views.adaptive,
        "buffer": buffer_view,
        "requested": requested or None,
        "warnings": warnings,
    }


def _match_controllers(
    controllers: "list[AdaptiveConcurrencyController]",
    model: str,
) -> "list[AdaptiveConcurrencyController]":
    """Filter controllers to those matching ``model`` by display name.

    Uses the shared name-selector rule (prefix at the name start or after a
    ``/``, exact match winning) — the same rule the CLI uses for task names,
    so ``ctl config --model gpt-4`` resolves like any other name selector.
    """
    return match_name_prefix(controllers, model, lambda c: c.name)


class _ProcessKnobViews(NamedTuple):
    """The process-global limit views built by :func:`_apply_process_knobs`."""

    max_sandboxes: list[dict[str, Any]]
    adaptive: list[dict[str, Any]]
    requested: dict[str, int]
    warnings: list[str]


def _apply_process_knobs(
    *,
    max_sandboxes: int | None,
    max_connections: int | None,
    model: str | None,
    dry_run: bool,
) -> _ProcessKnobViews:
    """Apply the process-global knobs and build their views.

    Returns the resulting views along with what was requested and any
    warnings (callers merge their own per-task entries in front). The views
    are re-read after applying, so a real set reflects the new values.
    ``model`` restricts the adaptive controllers considered (for both
    ``max_connections`` and the reported view) to those matching it.
    """
    from inspect_ai.util._concurrency import adaptive_controllers, sandbox_limiters

    requested: dict[str, int] = {}
    warnings: list[str] = []

    # max_sandboxes — the process-global sandbox limiters, one per sandbox type.
    sandboxes = sandbox_limiters()
    if max_sandboxes is not None:
        requested["max_sandboxes"] = max_sandboxes
        if not sandboxes:
            warnings.append(
                "max_sandboxes is not adjustable (no sandbox concurrency "
                "limiter is active — most likely the run has no sandbox limit "
                "in effect)."
            )
        elif not dry_run:
            for sem in sandboxes.values():
                sem.concurrency = max_sandboxes

    # max_connections — the adaptive controllers' scaling ceiling (process-global,
    # one per model). Lowering clamps live concurrency down immediately; raising
    # lifts the ceiling so the controllers can climb again. `model` narrows which
    # controllers are targeted (and shown).
    all_controllers = adaptive_controllers()
    controllers = (
        _match_controllers(all_controllers, model)
        if model is not None
        else all_controllers
    )
    if model is not None and all_controllers and not controllers:
        warnings.append(
            f"no adaptive connection controller matches model '{model}' "
            f"(active: {', '.join(sorted(c.name for c in all_controllers))})."
        )
    if max_connections is not None:
        requested["max_connections"] = max_connections
        if not all_controllers:
            warnings.append(
                "max_connections is not adjustable (this process isn't using "
                "adaptive connections)."
            )
        elif controllers and not dry_run:
            for ctrl in controllers:
                ctrl.set_max(max_connections)

    # Read `in_use` from the limiter directly (exact borrowed count) rather than
    # deriving it as `concurrency - value`: once a limit is lowered below the
    # in-flight count, `value` clamps to 0 and that derivation would report
    # `concurrency` instead of the true (higher) borrowed count.
    max_sandboxes_view = [
        {
            "type": sandbox_type,
            "limit": sem.concurrency,
            "in_use": sem.in_use,
        }
        for sandbox_type, sem in sorted(sandbox_limiters().items())
    ]

    # The adaptive-connections view: each controller's live limit, in-flight
    # count, scaling bounds (max reflects any max_connections change applied
    # above), and recent scale changes. Controllers are process-global (one per
    # model, keyed by name); with `model` set this shows only the matching ones.
    adaptive_view = [
        {
            "name": ctrl.name,
            "limit": ctrl.concurrency,
            "in_use": ctrl.in_use,
            "min": ctrl.min,
            "max": ctrl.max,
            "recent_changes": [
                {"at": at, "from": old, "to": new, "reason": reason}
                for (at, _name, old, new, reason) in ctrl.history[-_RECENT_CHANGES:]
            ],
        }
        for ctrl in sorted(controllers, key=lambda c: c.name)
    ]

    return _ProcessKnobViews(
        max_sandboxes=max_sandboxes_view,
        adaptive=adaptive_view,
        requested=requested,
        warnings=warnings,
    )
