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

Returns ``None`` when the eval isn't in this process — the endpoint turns that
into a 404. When a requested knob has no adjustable limiter in this eval (the
adaptive sample-concurrency path, or an eval with no sandbox limit in effect),
the value is applied to nothing and a warning is included rather than failing the
whole request — so a caller adjusting both knobs still gets the one that applies.
"""

from __future__ import annotations

from typing import Any


async def eval_limits(
    eval_id: str,
    *,
    max_samples: int | None = None,
    max_sandboxes: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Read (and optionally retune) a running eval's concurrency limits.

    With both ``max_samples`` and ``max_sandboxes`` ``None`` this is a pure read.
    Otherwise the supplied values are applied to the corresponding live limiters
    (unless ``dry_run`` is set, in which case nothing is mutated and the report
    shows what *would* change). Returns the resulting limits view, or ``None``
    when the eval isn't tracked in this process.

    Args:
        eval_id: The target eval.
        max_samples: New sample-concurrency limit, or ``None`` to leave it.
        max_sandboxes: New per-provider sandbox-concurrency limit, or ``None``.
        dry_run: When set, validate and report the intended change without
            applying it.
    """
    from inspect_ai._control.eval_state import get_eval_state
    from inspect_ai.util._concurrency import sandbox_limiters

    state = get_eval_state(eval_id)
    if state is None:
        return None

    warnings: list[str] = []
    requested: dict[str, int] = {}

    # max_samples — the per-eval sample limiter (None on the adaptive path).
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

    # Build the resulting view (reflects the applied change for a real set, or
    # the pre-change state for a dry-run / read). Re-read the sandbox limiters so
    # a real set shows the new values.
    max_samples_view: dict[str, Any]
    if sample_limiter is not None:
        max_samples_view = {
            "limit": sample_limiter.limit,
            "in_use": sample_limiter.in_use,
            "adjustable": True,
        }
    else:
        max_samples_view = {"adjustable": False}

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

    return {
        "dry_run": dry_run,
        "max_samples": max_samples_view,
        "max_sandboxes": max_sandboxes_view,
        "requested": requested or None,
        "warnings": warnings,
    }
