"""Live mid-flight overrides for the retry-loop ``GenerateConfig`` fields.

A process-wide override layer for ``timeout`` (the total retry budget per
generate call), ``attempt_timeout`` (the per-attempt timeout) and
``max_retries`` — the ``inspect ctl config`` retune surface for riding out
(or failing fast through) a provider incident without killing the run.

These fields are safe to retune by construction: they are excluded from
``task_identifier`` (see ``_GENERATE_CONFIG_FIELDS_TO_EXCLUDE`` in
``inspect_ai._eval.evalset``) precisely because they don't affect model
outputs, so a mid-flight change can't corrupt eval-set pairing or
reproducibility.

The overrides are consulted at the *point of use* rather than merged into
any ``GenerateConfig`` instance: the tenacity ``stop`` condition built by
:func:`inspect_ai.model._retry.model_retry_config` reads them on every
post-attempt check, and ``Model._generate`` reads ``attempt_timeout`` when
opening each attempt's cancel scope. That makes a change effective for
generate calls already stuck in a retry loop — the incident case — while
never preempting an in-flight HTTP request (drain-don't-preempt, matching
the concurrency knobs). Values a provider bakes into its SDK client at
initialization are not affected, and batcher admin-operation retry loops
(batch create/poll) deliberately opt out via ``live_overrides=False`` —
an exhausted admin-op retry fails every request riding the batch, a blast
radius no fail-fast retune should trigger. For the same reason a *batched*
generate call keeps its launch ``attempt_timeout``: its attempt awaits an
entire provider batch, and an override cancelling that wait would resubmit
the request into a new batch (duplicated provider work, potentially forever)
— the ``timeout`` / ``max_retries`` levers still reach batched calls' retry
loops.

The store is process-scoped (like ``max_sandboxes`` / ``max_connections``)
and reset at the outermost run boundary alongside the other control-channel
registries, so a later ``eval()`` in the same process starts from its launch
configuration.

No lock: the store is single-threaded by construction — the writer (the
control server handler) runs as a task on the same event loop as the readers
(the retry stop-condition and ``Model._generate``) — and each accessor is a
single atomic dict operation on independent keys, with no invariant spanning
them.
"""

from __future__ import annotations

from typing import Literal, get_args

GenerateConfigOverrideField = Literal["timeout", "attempt_timeout", "max_retries"]
"""The ``GenerateConfig`` fields that support live mid-flight overrides."""

GENERATE_CONFIG_OVERRIDE_FIELDS: tuple[GenerateConfigOverrideField, ...] = get_args(
    GenerateConfigOverrideField
)
"""All override fields, in the order views report them (the Literal's order)."""

MAX_GENERATE_CONFIG_OVERRIDE: int = 1_000_000_000
"""Upper bound for an override value (~31.7 years in seconds).

Far beyond any meaningful timeout or retry count, yet small enough that the
downstream float conversions stay exact: an unbounded integer would reach
``anyio.move_on_after``'s float conversion and raise ``OverflowError``
inside every subsequent generate call until the override was cleared. The
wire layers (the control-server routes and the CLI param type) reject an
out-of-range value before it gets here.
"""

_overrides: dict[str, int] = {}


def set_generate_config_override(
    field: GenerateConfigOverrideField, value: int | None
) -> None:
    """Set (or clear, with ``None``) the live override for ``field``.

    An override applies process-wide from the next point of use (the next
    retry-stop check or attempt); clearing it restores whatever each
    generate call's own config specifies. An out-of-range value raises —
    the control-server routes reject one before reaching here, so this
    guards programmatic callers (a sign or magnitude bug must not become a
    live override that poisons every generate call at its point of use).
    """
    if value is None:
        _overrides.pop(field, None)
    elif value < 0 or value > MAX_GENERATE_CONFIG_OVERRIDE:
        raise ValueError(
            f"{field} override must be between 0 and "
            f"{MAX_GENERATE_CONFIG_OVERRIDE} (got {value})"
        )
    else:
        _overrides[field] = value


def generate_config_override(
    field: GenerateConfigOverrideField, base: int | None = None
) -> int | None:
    """The effective value for ``field``: the live override, else ``base``.

    With the default ``base=None`` this is a pure override read (``None``
    means "no override in effect").
    """
    return _overrides.get(field, base)


def generate_config_overrides() -> dict[str, int | None]:
    """Snapshot of every override field (``None`` = no override in effect).

    The shape the control-channel config view reports.
    """
    return {field: _overrides.get(field) for field in GENERATE_CONFIG_OVERRIDE_FIELDS}


def reset_generate_config_overrides() -> None:
    """Clear all overrides (called at the outermost run boundary)."""
    _overrides.clear()
