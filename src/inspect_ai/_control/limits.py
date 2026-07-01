"""Modify-limits directive for the control channel.

Reads (and optionally retunes) a running eval's concurrency limits mid-flight —
``max_samples`` (per-eval sample concurrency) and ``max_sandboxes`` (per-provider
sandbox concurrency, process-global). The first of the phase-3 ``PATCH
/evals/<id>`` directives (see ``design/control-channel.md``).

Both knobs are backed by a :class:`~inspect_ai.util._concurrency.ResizableLimiter`
whose limit is settable at runtime: lowering it below the current in-use count
blocks new acquires until in-flight holders drain — it never preempts. Raising it
lets more work start immediately. ``max_samples`` is reached through
``EvalState.sample_limiter`` (attached by the runner); ``max_sandboxes`` through
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

:func:`eval_limits` returns ``None`` when the eval isn't in this process — the
endpoint turns that into a 404. When a requested knob has no adjustable limiter
(the adaptive sample-concurrency path, or an eval with no sandbox limit in
effect), the value is applied to nothing and a warning is included rather than
failing the whole request — so a caller adjusting several knobs still gets the
ones that apply.

Since ``max_sandboxes`` and ``max_connections`` are process-global (shared across
the process's evals), :func:`process_limits` exposes them without an eval — the
process-level ``GET``/``PATCH /limits`` endpoint — for the common case of viewing
or throttling a whole process without naming one of its tasks.
"""

from __future__ import annotations

from typing import Any

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

    Covers the knobs that are shared across every eval in the process:
    ``max_sandboxes`` (per-provider sandbox concurrency) and ``max_connections``
    (the adaptive controllers' scaling ceiling). It carries no ``max_samples`` —
    that is per-eval; use :func:`eval_limits` when a specific eval is in view.

    A process always exists, so unlike :func:`eval_limits` this never returns
    ``None``. With both knobs ``None`` it's a pure read. ``model`` restricts the
    adaptive controllers considered (matched at name start or after a ``/``).
    """
    warnings: list[str] = []
    requested: dict[str, int] = {}
    sandboxes_view, adaptive_view = _apply_process_knobs(
        max_sandboxes=max_sandboxes,
        max_connections=max_connections,
        model=model,
        dry_run=dry_run,
        requested=requested,
        warnings=warnings,
    )
    return {
        "dry_run": dry_run,
        "max_sandboxes": sandboxes_view,
        "adaptive": adaptive_view,
        "requested": requested or None,
        "warnings": warnings,
    }


async def eval_limits(
    eval_id: str,
    *,
    max_samples: int | None = None,
    max_sandboxes: int | None = None,
    max_connections: int | None = None,
    model: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Read (and optionally retune) one eval's concurrency limits.

    A superset of :func:`process_limits`: it adds the per-eval ``max_samples``
    knob (reached through ``EvalState.sample_limiter``) to the process-global
    ``max_sandboxes`` / ``max_connections`` view. With all three ``None`` this is
    a pure read. Returns ``None`` when the eval isn't tracked in this process
    (the endpoint turns that into a 404).

    On the adaptive path ``max_samples`` isn't a user setpoint (sample
    concurrency tracks the controller), so it's reported as not adjustable;
    ``max_connections`` retunes the controllers' scaling ceiling instead —
    lowering it clamps live concurrency down immediately, raising it lets the
    controller climb higher on subsequent clean rounds.

    Args:
        eval_id: The target eval.
        max_samples: New sample-concurrency limit, or ``None`` to leave it.
        max_sandboxes: New per-provider sandbox-concurrency limit, or ``None``.
        max_connections: New adaptive-controller scaling ceiling (applied to
            every adaptive controller in the process), or ``None`` to leave it.
        model: Restrict the adaptive controllers ``max_connections`` targets (and
            the reported adaptive view) to those matching, or ``None`` for all.
        dry_run: When set, validate and report the intended change without
            applying it.
    """
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(eval_id)
    if state is None:
        return None

    warnings: list[str] = []
    requested: dict[str, int] = {}

    # max_samples — the per-eval sample limiter (None on the adaptive path).
    # Applied before the process-global knobs so `requested` reads max_samples
    # first.
    sample_limiter = state.sample_limiter
    if max_samples is not None:
        requested["max_samples"] = max_samples
        if sample_limiter is None:
            warnings.append(
                "max_samples is not adjustable for this eval (it uses adaptive "
                "connection concurrency, or ran no samples in this process)."
            )
        elif not dry_run:
            sample_limiter.limit = max_samples

    sandboxes_view, adaptive_view = _apply_process_knobs(
        max_sandboxes=max_sandboxes,
        max_connections=max_connections,
        model=model,
        dry_run=dry_run,
        requested=requested,
        warnings=warnings,
    )

    max_samples_view: dict[str, Any]
    if sample_limiter is not None:
        max_samples_view = {
            "limit": sample_limiter.limit,
            "in_use": sample_limiter.in_use,
            "adjustable": True,
        }
    else:
        max_samples_view = {"adjustable": False}

    return {
        "dry_run": dry_run,
        "max_samples": max_samples_view,
        "max_sandboxes": sandboxes_view,
        "adaptive": adaptive_view,
        "requested": requested or None,
        "warnings": warnings,
    }


def _match_model(name: str, query: str) -> bool:
    """True if ``name`` matches ``query`` at its start or after a ``/``.

    Mirrors the CLI's task-name matching: ``gpt-4`` matches ``openai/gpt-4``
    (leaf prefix) and ``openai`` matches it too (name prefix).
    """
    leaf = name.rsplit("/", 1)[-1]
    return name.startswith(query) or leaf.startswith(query)


def _match_controllers(
    controllers: list[Any],
    model: str,
) -> list[Any]:
    """Filter controllers to those matching ``model``, exact match winning.

    An exact name/leaf match (e.g. ``gpt-4`` when both ``openai/gpt-4`` and
    ``openai/gpt-4-turbo`` are active) narrows to just the exact ones; otherwise
    all prefix matches are returned. Same precedence as CLI task-name matching.
    """
    prefix = [c for c in controllers if _match_model(c.name, model)]
    exact = [c for c in prefix if c.name == model or c.name.rsplit("/", 1)[-1] == model]
    return exact or prefix


def _apply_process_knobs(
    *,
    max_sandboxes: int | None,
    max_connections: int | None,
    model: str | None,
    dry_run: bool,
    requested: dict[str, int],
    warnings: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply the process-global knobs and build their views.

    Mutates ``requested`` / ``warnings`` in place (so callers can prepend a
    per-eval knob) and returns ``(max_sandboxes_view, adaptive_view)``. The views
    are re-read after applying, so a real set reflects the new values. ``model``
    restricts the adaptive controllers considered (for both ``max_connections``
    and the reported view) to those matching it.
    """
    from inspect_ai.util._concurrency import adaptive_controllers, sandbox_limiters

    # max_sandboxes — the process-global sandbox limiters, one per sandbox type.
    sandboxes = sandbox_limiters()
    if max_sandboxes is not None:
        requested["max_sandboxes"] = max_sandboxes
        if not sandboxes:
            warnings.append(
                "max_sandboxes is not adjustable for this eval (no sandbox "
                "concurrency limit is in effect)."
            )
        elif not dry_run:
            for sem in sandboxes.values():
                sem.set_concurrency(max_sandboxes)

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

    return max_sandboxes_view, adaptive_view
