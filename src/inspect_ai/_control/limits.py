"""Modify-limits directive for the control channel.

Reads (and optionally retunes) a running task's concurrency limits mid-flight —
``max_samples`` (per-task sample concurrency), ``max_sandboxes`` (per-provider
sandbox concurrency, process-global) and ``max_subprocesses`` (subprocess
concurrency, process-global). The first of the phase-3 modify directives
(see ``design/control-channel.md``). Keyed by task_id — the identity that is
stable across retry attempts — via ``GET``/``PATCH /tasks/<task-id>/config``.

These knobs are backed by a :class:`~inspect_ai.util._concurrency.ResizableLimiter`
whose limit is settable at runtime: lowering it below the current in-use count
blocks new acquires until in-flight holders drain — it never preempts. Raising it
lets more work start immediately. ``max_samples`` is reached through
the task_id-keyed sample-semaphore registry (populated by the runner, shared
across a task's retry attempts); ``max_sandboxes`` through
the process-global sandbox-limiter registry, since sandbox concurrency is shared
across the process's evals rather than owned by one; ``max_subprocesses`` through
the process-global subprocess limiter (created lazily by the first
concurrency-managed ``subprocess()`` call).

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

Since ``max_sandboxes``, ``max_subprocesses`` and ``max_connections`` are
process-global (shared across the process's tasks), :func:`process_limits`
exposes them without a task — the process-level ``GET``/``PATCH /config``
endpoint — for the common case of viewing or throttling a whole process without
naming one of its tasks.

Beyond the named knobs, any ``concurrency()`` registry entry — the public API
tools and user code register named limits through (web-search providers, model
compaction, sandbox-tools injection, arbitrary solver code) — can be retuned by
its exact name via ``key`` / ``key_limit``. The view carries a ``concurrency``
list enumerating every registry entry with its ``(limit, in_use, adjustable)``,
and the default registry backs every static entry with a resizable semaphore,
so third-party limits are adjustable without their creator opting in. Named
limits are created lazily on first use, so a key that names no entry raises
:class:`UnknownConcurrencyKeyError` (listing the keys that do exist) *before*
any other knob applies — unlike the shipped knobs' not-adjustable warnings, a
mistyped name silently matching nothing would read as applied. The registry is
process-global, so the key knob rides both endpoints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from inspect_ai._util.name_match import match_name_prefix

if TYPE_CHECKING:
    from inspect_ai.util._concurrency import (
        AdaptiveConcurrencyController,
        ConcurrencySemaphore,
    )

# How many of an adaptive controller's most-recent scale changes to surface in
# the read view — enough to see whether it's actively being throttled without
# dumping the controller's full bounded history.
_RECENT_CHANGES = 5


class UnknownConcurrencyKeyError(ValueError):
    """A concurrency-key retune named a registry entry that does not exist.

    Named ``concurrency()`` limits are created lazily on first use, so an
    unknown key may simply not have been exercised yet — the message lists the
    keys that do exist. Raised by the directive functions before any knob is
    applied (the routes turn it into a 400), so a combined ``PATCH`` fails
    whole rather than applying its other knobs first.
    """


def check_concurrency_key(key: str | None) -> None:
    """Raise :class:`UnknownConcurrencyKeyError` when ``key`` names no entry.

    ``None`` (no key requested) passes. Matching is by exact registered name —
    a mutation should not fan out on a prefix the caller never spelled.
    """
    if key is None:
        return
    from inspect_ai.util._concurrency import concurrency_semaphores

    names = sorted({sem.name for sem in concurrency_semaphores()})
    if key in names:
        return
    available = (
        f"available: {', '.join(names)}"
        if names
        else "no concurrency keys are registered yet"
    )
    raise UnknownConcurrencyKeyError(
        f"no concurrency key named '{key}' ({available}). Named limits are "
        "created lazily on first use, so a key does not exist until the code "
        "that registers it has run."
    )


async def process_limits(
    *,
    max_sandboxes: int | None = None,
    max_subprocesses: int | None = None,
    max_connections: int | None = None,
    model: str | None = None,
    key: str | None = None,
    key_limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Read (and optionally retune) the process-global concurrency limits.

    Covers the knobs that are shared across every task in the process:
    ``max_sandboxes`` (per-provider sandbox concurrency), ``max_subprocesses``
    (subprocess concurrency), ``max_connections`` (the adaptive controllers'
    scaling ceiling), and ``key`` / ``key_limit`` (a named ``concurrency()``
    registry entry — the registry is process-global). It carries no
    ``max_samples`` — that is per-task; use :func:`task_limits` when a
    specific task is in view.

    A process always exists, so unlike :func:`task_limits` this never returns
    ``None``. With every knob ``None`` it's a pure read. ``model`` restricts the
    adaptive controllers considered (matched at name start or after a ``/``).

    Raises:
        UnknownConcurrencyKeyError: When ``key`` names no registry entry —
            before any other knob is applied.
    """
    check_concurrency_key(key)
    views = _apply_process_knobs(
        max_sandboxes=max_sandboxes,
        max_subprocesses=max_subprocesses,
        max_connections=max_connections,
        model=model,
        key=key,
        key_limit=key_limit,
        dry_run=dry_run,
    )
    return {
        "dry_run": dry_run,
        "max_sandboxes": views.max_sandboxes,
        "max_subprocesses": views.max_subprocesses,
        "adaptive": views.adaptive,
        "concurrency": views.concurrency,
        "requested": views.requested or None,
        "warnings": views.warnings,
    }


async def task_limits(
    task_id: str,
    *,
    max_samples: int | None = None,
    max_sandboxes: int | None = None,
    max_subprocesses: int | None = None,
    max_connections: int | None = None,
    model: str | None = None,
    key: str | None = None,
    key_limit: int | None = None,
    log_buffer: int | None = None,
    log_shared: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Read (and optionally retune) a task's retunable config.

    A superset of :func:`process_limits`: it adds the per-task knobs — the
    ``max_samples`` sample concurrency plus the ``log_buffer`` / ``log_shared``
    sample-buffer params — to the process-global ``max_sandboxes`` /
    ``max_subprocesses`` / ``max_connections`` view. Task-scoped state lives in task_id-keyed
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
        max_subprocesses: New subprocess-concurrency limit, or ``None``.
        max_connections: New adaptive-controller scaling ceiling (applied to
            every adaptive controller in the process), or ``None`` to leave it.
        model: Restrict the adaptive controllers ``max_connections`` targets (and
            the reported adaptive view) to those matching, or ``None`` for all.
        key: Name of a ``concurrency()`` registry entry to retune (exact
            match; the registry is process-global), or ``None``. An unknown
            name raises :class:`UnknownConcurrencyKeyError` before any other
            knob is applied.
        key_limit: The new limit for ``key``, or ``None``.
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

    # an unknown key fails the whole request, so it must be rejected before
    # the per-task knobs below (not just before the process knobs) apply
    check_concurrency_key(key)

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
            "log_shared is not adjustable for this task (no shared-log sync "
            "is active for its log — shared sync is enabled at launch with "
            "--log-shared and requires realtime logging)."
        )

    views = _apply_process_knobs(
        max_sandboxes=max_sandboxes,
        max_subprocesses=max_subprocesses,
        max_connections=max_connections,
        model=model,
        key=key,
        key_limit=key_limit,
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
        "max_subprocesses": views.max_subprocesses,
        "adaptive": views.adaptive,
        "concurrency": views.concurrency,
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
    max_subprocesses: dict[str, Any] | None
    adaptive: list[dict[str, Any]]
    concurrency: list[dict[str, Any]]
    requested: dict[str, int]
    warnings: list[str]


def _static_semaphores() -> "list[ConcurrencySemaphore]":
    """The non-adaptive concurrency-registry entries (the key knob's targets).

    Adaptive controllers are excluded: they are surfaced through the
    ``adaptive`` view and retuned via ``max_connections`` (their limit is a
    scaling ceiling, not a fixed setpoint a key retune could set directly).
    """
    from inspect_ai.util._concurrency import (
        AdaptiveConcurrencyController,
        concurrency_semaphores,
    )

    return [
        sem
        for sem in concurrency_semaphores()
        if not isinstance(sem, AdaptiveConcurrencyController)
    ]


def _apply_process_knobs(
    *,
    max_sandboxes: int | None,
    max_subprocesses: int | None,
    max_connections: int | None,
    model: str | None,
    key: str | None = None,
    key_limit: int | None = None,
    dry_run: bool,
) -> _ProcessKnobViews:
    """Apply the process-global knobs and build their views.

    Returns the resulting views along with what was requested and any
    warnings (callers merge their own per-task entries in front). The views
    are re-read after applying, so a real set reflects the new values.
    ``model`` restricts the adaptive controllers considered (for both
    ``max_connections`` and the reported view) to those matching it. ``key``
    must already have passed :func:`check_concurrency_key` (the caller
    rejects unknown keys before any knob applies).
    """
    from inspect_ai.util._concurrency import (
        ResizableSemaphore,
        adaptive_controllers,
        sandbox_limiters,
        subprocess_limiter,
    )

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

    # max_subprocesses — the process-global subprocess limiter (registry key
    # "subprocesses", created lazily by the first concurrency-managed
    # subprocess() call).
    subprocesses = subprocess_limiter()
    if max_subprocesses is not None:
        requested["max_subprocesses"] = max_subprocesses
        if subprocesses is None:
            warnings.append(
                "max_subprocesses is not adjustable (no adjustable subprocess "
                "limiter is active — most likely no concurrency-managed "
                "subprocess has run yet; the limiter is created on first use)."
            )
        elif not dry_run:
            subprocesses.concurrency = max_subprocesses

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

    # key — a named concurrency() registry entry, matched by exact name (a
    # name can back several entries — e.g. one model on two accounts — and the
    # retune reaches them all, like max_connections' name matching). The
    # caller already rejected unknown names, so a no-match here means the name
    # belongs only to an adaptive controller.
    if key is not None and key_limit is not None:
        requested[f"concurrency:{key}"] = key_limit
        matches = [sem for sem in _static_semaphores() if sem.name == key]
        resizable_matches = [
            sem for sem in matches if isinstance(sem, ResizableSemaphore)
        ]
        if not matches:
            warnings.append(
                f"'{key}' is managed by adaptive connections — retune its "
                "ceiling with max_connections (scoped with model if needed)."
            )
        elif not resizable_matches:
            warnings.append(
                f"'{key}' is not adjustable (its semaphore does not support "
                "live resizing)."
            )
        elif not dry_run:
            for sem in resizable_matches:
                sem.concurrency = key_limit

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

    # `None` distinguishes "no limiter yet" (no subprocess has run) from a
    # live limiter view — the CLI renders the former as inactive.
    max_subprocesses_view = (
        {"limit": subprocesses.concurrency, "in_use": subprocesses.in_use}
        if subprocesses is not None
        else None
    )

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

    # The concurrency-key view: every static registry entry by its exact
    # registered name (the addressable identity for the key knob — no prefix
    # shortening, `visible=False` entries included). Re-read after applying,
    # like the other views. A `name` can appear twice when two entries (with
    # distinct storage keys) share a display name.
    concurrency_view = [
        {
            "name": sem.name,
            "limit": sem.concurrency,
            "in_use": sem.in_use,
            "adjustable": isinstance(sem, ResizableSemaphore),
        }
        for sem in sorted(_static_semaphores(), key=lambda s: s.name)
    ]

    return _ProcessKnobViews(
        max_sandboxes=max_sandboxes_view,
        max_subprocesses=max_subprocesses_view,
        adaptive=adaptive_view,
        concurrency=concurrency_view,
        requested=requested,
        warnings=warnings,
    )
