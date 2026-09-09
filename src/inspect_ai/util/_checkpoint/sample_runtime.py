"""Dump and restore sample-root limit usage and related in-memory runtime.

Persisted as ``sample_runtime.json`` in the checkpoint host context.
"""

from __future__ import annotations

from typing import Any

from pydantic import JsonValue


def dump_sample_runtime() -> dict[str, Any]:
    """Snapshot sample-root runtime for the host context.

    Always returns a payload (zeros included) so fire writes the file.
    Presence on disk means this checkpoint has runtime state.
    ``token_interval_reference`` is filled in by the checkpointer at write
    time — the trigger lives there, not on the limit trees.
    """
    from inspect_ai.model._model import (
        sample_model_fallbacks_context_var,
        sample_model_usage,
        sample_role_usage,
    )
    from inspect_ai.model._model_output import ModelUsage
    from inspect_ai.util._limit import (
        _CostLimit,
        _TimeLimit,
        _TokenLimit,
        _tree_root,
        _TurnLimit,
        _WorkingLimit,
        cost_limit_tree,
        time_limit_tree,
        token_limit_tree,
        turn_limit_tree,
        working_limit_tree,
    )

    token_usage = ModelUsage()
    token_root = _tree_root(token_limit_tree)
    if isinstance(token_root, _TokenLimit):
        token_usage = token_root._usage

    cost = 0.0
    cost_root = _tree_root(cost_limit_tree)
    if isinstance(cost_root, _CostLimit):
        cost = cost_root._cost

    turns = 0
    turn_root = _tree_root(turn_limit_tree)
    if isinstance(turn_root, _TurnLimit):
        turns = turn_root._turns

    time_elapsed = 0.0
    time_root = _tree_root(time_limit_tree)
    if isinstance(time_root, _TimeLimit):
        time_elapsed = time_root.usage

    working_elapsed = 0.0
    working_waiting = 0.0
    working_root = _tree_root(working_limit_tree)
    if isinstance(working_root, _WorkingLimit):
        working_elapsed = working_root.usage
        working_waiting = working_root._waiting_time

    return {
        "token_usage": token_usage.model_dump(mode="json"),
        "cost": cost,
        "turns": turns,
        "time_elapsed": time_elapsed,
        "working_elapsed": working_elapsed,
        "working_waiting": working_waiting,
        "model_usage": {
            name: usage.model_dump(mode="json")
            for name, usage in sample_model_usage().items()
        },
        "role_usage": {
            name: usage.model_dump(mode="json")
            for name, usage in sample_role_usage().items()
        },
        "model_fallbacks": [
            {"model": model, "fallback_model": fallback_model, "count": count}
            for (model, fallback_model), count in (
                sample_model_fallbacks_context_var.get().items()
            )
        ],
    }


def restore_sample_runtime(value: JsonValue | None, *, check: bool) -> None:
    """Reseed sample-root runtime from a prior :func:`dump_sample_runtime`.

    ``None`` (absent file / pre-this-feature checkpoint) is a no-op.
    Mutates live objects in place — no ``ContextVar.set()``.

    ``check`` separates reported usage from enforcement. Reported usage
    (counters, elapsed time, the working-time origin behind every event's
    ``working_start``) is always restored. Enforcement — the working limit's
    anchors, the ``check()`` calls, and the time limit's cancel-scope
    deadline — is restored only when ``check`` is True, i.e. for a normal
    ``"resume"``. A ``"resume_for_scoring"`` attempt must be able to score a
    sample whose budget was already spent when the checkpoint fired, so it
    arms nothing — and the restored elapsed is kept out of the deadline
    origin, so a later ``_refresh_deadline()`` (a live ``time_limit``
    retune) cannot re-arm the spent budget either.

    Enforcement order matters: the counted checks run before the deadline is
    armed, so a resume over both a counted budget and the time limit reports
    the counted limit rather than a time cancellation delivered at the next
    ``await``.
    """
    if not isinstance(value, dict):
        return

    import time

    import anyio

    from inspect_ai._util.working import _sample_timing
    from inspect_ai.model._model import (
        sample_model_fallbacks_context_var,
        sample_model_usage_context_var,
        sample_role_usage_context_var,
    )
    from inspect_ai.model._model_output import ModelUsage
    from inspect_ai.util._limit import (
        _CostLimit,
        _TimeLimit,
        _TokenLimit,
        _tree_root,
        _TurnLimit,
        _WorkingLimit,
        check_cost_limit,
        check_token_limit,
        check_turn_limit,
        check_working_limit,
        cost_limit_tree,
        time_limit_tree,
        token_limit_tree,
        turn_limit_tree,
        working_limit_tree,
    )

    payload: dict[str, Any] = value

    token_root = _tree_root(token_limit_tree)
    if isinstance(token_root, _TokenLimit) and payload.get("token_usage") is not None:
        token_root._usage = ModelUsage.model_validate(payload["token_usage"])

    cost_root = _tree_root(cost_limit_tree)
    if isinstance(cost_root, _CostLimit) and payload.get("cost") is not None:
        cost_root._cost = float(payload["cost"])

    turn_root = _tree_root(turn_limit_tree)
    if isinstance(turn_root, _TurnLimit) and payload.get("turns") is not None:
        turn_root._turns = int(payload["turns"])

    # Restore the prior attempt's elapsed time so `usage` / `remaining`
    # report the sample's total. A normal resume backdates the origin, so the
    # deadline (armed further down, under `check`) charges the prior attempt
    # too. A scoring resume must never enforce the prior elapsed — not even
    # through a later `_refresh_deadline()` (a live `time_limit` retune) — so
    # it keeps the origin fresh and carries the elapsed in the
    # reporting-only field.
    time_elapsed = float(payload.get("time_elapsed") or 0.0)
    time_node = _tree_root(time_limit_tree)
    time_root = time_node if isinstance(time_node, _TimeLimit) else None
    if time_root is not None and time_root._start_time is not None:
        if check:
            time_root._start_time = anyio.current_time() - time_elapsed
        else:
            time_root._start_time = anyio.current_time()
            time_root._prior_elapsed = time_elapsed
    else:
        time_root = None

    working_elapsed = float(payload.get("working_elapsed") or 0.0)
    working_waiting = float(payload.get("working_waiting") or 0.0)
    if check:
        # `monitor_working_limit` polls these anchors once a second with no
        # attempt awareness, so seeding a spent working budget would cancel a
        # scoring resume's plan task group before it scores.
        working_root = _tree_root(working_limit_tree)
        if (
            isinstance(working_root, _WorkingLimit)
            and working_root._start_time is not None
        ):
            working_root._waiting_time = working_waiting
            working_root._start_time = (
                anyio.current_time() - working_elapsed - working_waiting
            )

    timing = _sample_timing.get()
    if timing.start_datetime is not None:
        # Shift this attempt's origin back by the prior working time so
        # `sample_working_time()` — and every event's `working_start` — keeps
        # climbing across attempts. `waiting_time` stays attempt-local: the
        # logged `working_time` subtracts it from this attempt's wall clock,
        # which a restored cumulative value would drive negative.
        timing.start_time = time.monotonic() - working_elapsed

    model_usage = sample_model_usage_context_var.get(None)
    if model_usage is not None:
        _restore_usage_dict(model_usage, payload.get("model_usage"))
    role_usage = sample_role_usage_context_var.get(None)
    if role_usage is not None:
        _restore_usage_dict(role_usage, payload.get("role_usage"))
    fallbacks = sample_model_fallbacks_context_var.get(None)
    dumped_fallbacks = payload.get("model_fallbacks")
    if fallbacks is not None:
        fallbacks.clear()
        if isinstance(dumped_fallbacks, list):
            for item in dumped_fallbacks:
                if isinstance(item, dict):
                    fallbacks[(str(item["model"]), str(item["fallback_model"]))] = int(
                        item["count"]
                    )

    if check:
        check_token_limit()
        check_cost_limit()
        check_turn_limit()
        check_working_limit()
        # Last: arming an already-spent deadline does not raise, it schedules a
        # cancellation for the next `await`.
        if time_root is not None:
            time_root._refresh_deadline()


def _restore_usage_dict(current: dict[str, Any], dumped: object) -> None:
    from inspect_ai.model._model_output import ModelUsage

    current.clear()
    if not isinstance(dumped, dict):
        return
    for name, usage in dumped.items():
        current[str(name)] = ModelUsage.model_validate(usage)
