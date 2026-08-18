"""Live mid-flight overrides for the per-sample limits (time / token / message).

A task-scoped override layer for ``time_limit`` / ``token_limit`` /
``message_limit`` — the ``inspect ctl config`` retune surface for reining in
runaway samples (or unblocking over-constrained ones) without killing the run.

The overrides are consulted at the *point of use* rather than merged into any
config or ``TaskState``: each sample's root limit nodes resolve their
effective limit through this store (via the override source attached by
:func:`sample_limit_override_scope`) on every limit check, so a retune
reaches samples already in flight — a token/message ceiling applies at the
sample's next check — and samples not yet started pick it up the same way.
Time limits are the exception to pure point-of-use: a cancel-scope deadline
is slept on, not polled, so a ``time_limit`` retune also re-derives the
deadline of every registered live scope directly
(:meth:`~inspect_ai.util._limit._TimeLimit._refresh_deadline`). The value
semantics match the retry-loop overrides
(:mod:`inspect_ai.model._generate_overrides`): every integer is a real
value, and clearing an override (``None`` here; the wire keyword ``clear``)
restores whatever each sample's launch config specifies. Only the sample
*root* nodes resolve through the store — nested ``token_limit()`` /
``message_limit()`` / ``time_limit()`` scopes opened by agents or solvers
keep their own values.

The store is keyed by task_id — the identity that is stable across retry
attempts, matching the other task-scoped knobs — and reset at the outermost
run boundary alongside the other control-channel registries, so a later
``eval()`` in the same process starts from its launch configuration.

No lock: everything here runs on the eval's single event loop thread — the
writer (the control-server handler) runs as a task on the same loop as the
readers (the limit checks) and the scope registration in the sample runner —
and each accessor is a plain dict/list operation with no invariant spanning
them.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator, Literal, get_args

if TYPE_CHECKING:
    from inspect_ai.util._limit import _MessageLimit, _TimeLimit, _TokenLimit

SampleLimitOverrideField = Literal["time_limit", "token_limit", "message_limit"]
"""The per-sample limits that support live mid-flight overrides."""

SAMPLE_LIMIT_OVERRIDE_FIELDS: tuple[SampleLimitOverrideField, ...] = get_args(
    SampleLimitOverrideField
)
"""All override fields, in the order views report them (the Literal's order)."""

MAX_SAMPLE_LIMIT_OVERRIDE: int = 1_000_000_000
"""Upper bound for an override value (~31.7 years as a time limit).

Far beyond any meaningful limit, yet small enough that the downstream float
conversions stay exact: a ``time_limit`` override feeds anyio cancel-scope
deadlines, where an unbounded integer would overflow the float conversion.
The wire layers (the control-server route and the CLI param type) reject an
out-of-range value before it gets here.
"""

_overrides: dict[str, dict[str, int]] = {}
"""Active overrides, keyed by task_id then field."""

_time_limits: dict[str, list["_TimeLimit"]] = {}
"""Live sample-root time-limit nodes by task_id (deadline re-derivation
targets for a ``time_limit`` retune)."""


def set_sample_limit_override(
    task_id: str, field: SampleLimitOverrideField, value: int | None
) -> None:
    """Set (or clear, with ``None``) the live override for ``field``.

    An override applies to every sample of ``task_id`` from its next limit
    check; clearing it restores whatever each sample's launch config
    specifies. A ``time_limit`` change additionally re-derives the deadlines
    of the task's live cancel scopes (a deadline is slept on, so the next
    check would never come). An out-of-range value raises — the control-server
    route rejects one before reaching here, so this guards programmatic
    callers (a sign or magnitude bug must not become a live override that
    poisons every sample at its point of use).
    """
    if value is None:
        task_overrides = _overrides.get(task_id)
        if task_overrides is not None:
            task_overrides.pop(field, None)
            if not task_overrides:
                del _overrides[task_id]
    elif value < 0 or value > MAX_SAMPLE_LIMIT_OVERRIDE:
        raise ValueError(
            f"{field} override must be between 0 and "
            f"{MAX_SAMPLE_LIMIT_OVERRIDE} (got {value})"
        )
    else:
        _overrides.setdefault(task_id, {})[field] = value
    if field == "time_limit":
        for node in _time_limits.get(task_id, []):
            node._refresh_deadline()


def sample_limit_override(
    task_id: str, field: SampleLimitOverrideField, base: int | None = None
) -> int | None:
    """The effective value for ``field``: the live override, else ``base``.

    With the default ``base=None`` this is a pure override read (``None``
    means "no override in effect").
    """
    task_overrides = _overrides.get(task_id)
    if task_overrides is None:
        return base
    return task_overrides.get(field, base)


def sample_limit_overrides(task_id: str) -> dict[str, int | None]:
    """Snapshot of every override field (``None`` = no override in effect).

    The shape the control-channel config view's ``limits`` key reports.
    """
    task_overrides = _overrides.get(task_id, {})
    return {field: task_overrides.get(field) for field in SAMPLE_LIMIT_OVERRIDE_FIELDS}


def reset_sample_limit_overrides() -> None:
    """Clear all overrides (called at the outermost run boundary)."""
    _overrides.clear()
    _time_limits.clear()


@contextmanager
def sample_limit_override_scope(
    task_id: str,
    *,
    time: "_TimeLimit",
    token: "_TokenLimit",
    message: "_MessageLimit",
) -> Iterator[None]:
    """Mark a sample's root limit nodes as override targets for ``task_id``.

    Entered by the sample runner around the sample's limit scopes: attaches
    each node's override source (read by the node's ``limit`` property at
    every point of use, including the time node's ``__enter__``) and
    registers the time node for live deadline re-derivation while the scope
    is open. Enters first in the runner's with-tuple — the whole tuple
    enters without awaiting, so a retune can never observe a
    partially-attached sample.
    """
    token._limit_override = lambda: sample_limit_override(task_id, "token_limit")
    message._limit_override = lambda: sample_limit_override(task_id, "message_limit")
    time._limit_override = lambda: sample_limit_override(task_id, "time_limit")
    registered = _time_limits.setdefault(task_id, [])
    registered.append(time)
    try:
        yield
    finally:
        registered.remove(time)
        if not registered:
            _time_limits.pop(task_id, None)
