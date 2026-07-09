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
initialization are not affected.

The store is process-scoped (like ``max_sandboxes`` / ``max_connections``)
and reset at the outermost run boundary alongside the other control-channel
registries, so a later ``eval()`` in the same process starts from its launch
configuration.
"""

from __future__ import annotations

from threading import Lock
from typing import Literal

GenerateConfigOverrideField = Literal["timeout", "attempt_timeout", "max_retries"]
"""The ``GenerateConfig`` fields that support live mid-flight overrides."""

GENERATE_CONFIG_OVERRIDE_FIELDS: tuple[GenerateConfigOverrideField, ...] = (
    "timeout",
    "attempt_timeout",
    "max_retries",
)
"""All override fields, in the order views report them."""

_overrides: dict[str, int] = {}
_lock = Lock()


def set_generate_config_override(
    field: GenerateConfigOverrideField, value: int | None
) -> None:
    """Set (or clear, with ``None``) the live override for ``field``.

    An override applies process-wide from the next point of use (the next
    retry-stop check or attempt); clearing it restores whatever each
    generate call's own config specifies.
    """
    with _lock:
        if value is None:
            _overrides.pop(field, None)
        else:
            _overrides[field] = value


def generate_config_override(
    field: GenerateConfigOverrideField, base: int | None = None
) -> int | None:
    """The effective value for ``field``: the live override, else ``base``.

    With the default ``base=None`` this is a pure override read (``None``
    means "no override in effect").
    """
    with _lock:
        return _overrides.get(field, base)


def generate_config_overrides() -> dict[str, int | None]:
    """Snapshot of every override field (``None`` = no override in effect).

    The shape the control-channel config view reports.
    """
    with _lock:
        return {
            field: _overrides.get(field) for field in GENERATE_CONFIG_OVERRIDE_FIELDS
        }


def init_generate_config_overrides() -> None:
    """Clear all overrides (called at the outermost run boundary)."""
    with _lock:
        _overrides.clear()
