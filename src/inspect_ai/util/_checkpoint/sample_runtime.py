"""Dump and restore sample-root limit usage and related in-memory runtime.

Persisted as ``sample_runtime.json`` in the checkpoint host context.
Callers do not learn limit trees, ``SampleTiming``, or usage dicts.
"""

from __future__ import annotations

from typing import Any

from pydantic import JsonValue


def dump_sample_runtime() -> JsonValue | None:
    """Snapshot sample-root runtime for the host context.

    Always returns a payload (zeros included) so fire writes the file.
    Presence on disk means this checkpoint has runtime state.
    """
    from inspect_ai._util.working import sample_waiting_time
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
        "sample_waiting_time": sample_waiting_time(),
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
        "token_interval_reference": _dump_token_interval_reference(),
    }


def restore_sample_runtime(value: JsonValue | None, *, check: bool) -> None:
    """Reseed sample-root runtime from a prior :func:`dump_sample_runtime`.

    ``None`` (absent file / pre-this-feature checkpoint) is a no-op: usage
    stays at whatever the new attempt started with (today's reset-to-0).
    Restore mutates live objects in place — no ``ContextVar.set()``.
    ``check`` runs token/cost/turn ``check()`` after seeding; pass True
    only for a normal ``"resume"`` attempt.
    """
    if value is None:
        return
    _restore(value, check=check)


def _dump_token_interval_reference() -> int | None:
    from inspect_ai.util._checkpoint.checkpointer import current_checkpointer

    cp = current_checkpointer()
    if cp is None:
        return None
    trigger = getattr(cp, "_trigger", None)
    ref = getattr(trigger, "_reference", None)
    return int(ref) if isinstance(ref, int) else None


def _restore(value: JsonValue, *, check: bool) -> None:
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
        cost_limit_tree,
        time_limit_tree,
        token_limit_tree,
        turn_limit_tree,
        working_limit_tree,
    )

    if not isinstance(value, dict):
        return
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

    time_elapsed = float(payload.get("time_elapsed") or 0.0)
    time_root = _tree_root(time_limit_tree)
    if isinstance(time_root, _TimeLimit) and time_root._start_time is not None:
        time_root._start_time = anyio.current_time() - time_elapsed
        time_root._refresh_deadline()

    working_elapsed = float(payload.get("working_elapsed") or 0.0)
    working_waiting = float(payload.get("working_waiting") or 0.0)
    working_root = _tree_root(working_limit_tree)
    if isinstance(working_root, _WorkingLimit) and working_root._start_time is not None:
        working_root._waiting_time = working_waiting
        working_root._start_time = (
            anyio.current_time() - working_elapsed - working_waiting
        )

    sample_waiting = float(payload.get("sample_waiting_time") or 0.0)
    timing = _sample_timing.get()
    if timing.start_datetime is not None:
        timing.waiting_time = sample_waiting
        timing.start_time = time.monotonic() - working_elapsed - sample_waiting

    model_usage = sample_model_usage_context_var.get(None)
    if model_usage is not None:
        _restore_usage_dict(model_usage, payload.get("model_usage"))
    role_usage = sample_role_usage_context_var.get(None)
    if role_usage is not None:
        _restore_usage_dict(role_usage, payload.get("role_usage"))
    fallbacks = sample_model_fallbacks_context_var.get(None)
    if fallbacks is not None:
        _restore_fallbacks(fallbacks, payload.get("model_fallbacks"))

    if check:
        check_token_limit()
        check_cost_limit()
        check_turn_limit()


def _restore_usage_dict(current: dict[str, Any], dumped: object) -> None:
    from inspect_ai.model._model_output import ModelUsage

    current.clear()
    if not isinstance(dumped, dict):
        return
    for name, usage in dumped.items():
        current[str(name)] = ModelUsage.model_validate(usage)


def _restore_fallbacks(current: dict[tuple[str, str], int], dumped: object) -> None:
    current.clear()
    if not isinstance(dumped, list):
        return
    for item in dumped:
        if not isinstance(item, dict):
            continue
        current[(str(item["model"]), str(item["fallback_model"]))] = int(item["count"])
