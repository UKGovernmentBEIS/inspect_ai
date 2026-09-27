"""Checkpoint trigger configuration types.

User-facing trigger specs — frozen dataclasses, pure data with no
runtime state. The per-session mutable state (turn counters,
time-of-last-fire, etc.) lives on the concrete :class:`Trigger`
implementations (see :mod:`.engine`), one instance of which is built
per sample-checkpointed session from the user's spec via
:func:`create_trigger`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from numbers import Number
from typing import Annotated, Any, Literal, Protocol, cast

from pydantic import (
    BeforeValidator,
    Discriminator,
    JsonValue,
    TypeAdapter,
    ValidationError,
)


@dataclass(frozen=True)
class Manual:
    """No-op trigger spec.

    The engine's ``tick()`` always returns ``None`` for this spec —
    fires happen only through explicit ``cp.checkpoint()`` calls.
    """

    kind: Literal["manual"] = "manual"
    """Discriminator identifying this trigger in serialized form. See
    :data:`CheckpointTrigger`."""


@dataclass(frozen=True)
class TurnInterval:
    """Fire after every ``every`` agent turns of work.

    The very first ``tick()`` call marks the boundary *before* turn 1
    has run — agents place ``cp.tick()`` at the top of their loop, so
    the opening tick stands between "no turn yet" and "turn 1." That
    boundary is informational and doesn't count toward the threshold;
    otherwise ``every=1`` would fire an empty checkpoint on the
    opening tick.
    """

    every: int

    kind: Literal["turn"] = "turn"
    """Discriminator identifying this trigger in serialized form. See
    :data:`CheckpointTrigger`."""


@dataclass(frozen=True)
class TimeInterval:
    """Fire after a wall-clock interval.

    The engine fires when at least ``every`` has elapsed since the
    last fire (or since the session opened, for the first fire).
    """

    every: timedelta

    kind: Literal["time"] = "time"
    """Discriminator identifying this trigger in serialized form. See
    :data:`CheckpointTrigger`."""


@dataclass(frozen=True)
class TokenInterval:
    """Fire every ``every`` tokens of sample-level usage.

    Sample total tokens are read from
    :func:`inspect_ai.model.sample_total_tokens`; the trigger fires
    each time the running total crosses another ``every``-token
    boundary since the last fire.
    """

    every: int

    kind: Literal["token"] = "token"
    """Discriminator identifying this trigger in serialized form. See
    :data:`CheckpointTrigger`."""


@dataclass(frozen=True)
class CostInterval:
    """Fire every ``every`` dollars of sample-level cost.

    Sample total cost is read from
    :func:`inspect_ai.model.sample_total_cost`; the trigger fires
    each time the running total crosses another ``every``-dollar
    boundary since the last fire.
    """

    every: float

    kind: Literal["cost"] = "cost"
    """Discriminator identifying this trigger in serialized form. See
    :data:`CheckpointTrigger`."""


BudgetKind = Literal["token", "cost", "time", "working"]
"""Which of the sample's tracked budgets ``BudgetPercent`` watches."""


@dataclass(frozen=True)
class BudgetPercent:
    """Fire on each ``percent``-percent slice of the active ``budget``.

    ``percent`` is in 0..100. With ``percent=25``, the trigger fires
    at ~25% / 50% / 75% / 100% of the relevant limit's usage. Has no
    effect when no limit is set for the chosen budget.
    """

    budget: BudgetKind
    percent: float

    kind: Literal["budget"] = "budget"
    """Discriminator identifying this trigger in serialized form. See
    :data:`CheckpointTrigger`."""


CheckpointTriggerKind = Literal[
    "time", "turn", "manual", "token", "cost", "budget", "agent_complete"
]
"""Identifier of which trigger fired, as recorded on the checkpoint file.

``"agent_complete"`` is an internal label emitted only by the
harness-driven final fire on clean solver exit (see
:meth:`_CheckpointerSetup.__aexit__`). It is never returned from a
public :class:`Trigger` spec's ``tick()``; users cannot configure it
from :class:`CheckpointConfig`.
"""


_NUMERIC_KINDS: tuple[tuple[type, str], ...] = (
    (int, "turn"),
    (float, "cost"),
    (timedelta, "time"),
)
"""How a lone ``every`` is read when nothing names its kind, in the
order the undiscriminated union resolved it: whole number = turns,
fractional = dollars, anything left that is a duration = time. Applied
to a string as well, since a serialized ``every`` may be quoted."""


def _untagged_every_kind(every: Any) -> str | None:
    """Which kind a lone, untagged ``every`` value used to mean.

    A ``bool`` is an ``int`` and so was coerced to turns. A real that
    is neither ``int`` nor ``float`` — a ``Decimal`` from a loader told
    to parse JSON floats as one — was coerced to dollars.
    """
    if isinstance(every, bool):
        return "turn"
    for target, kind in _NUMERIC_KINDS:
        if isinstance(every, target):
            return kind
        if isinstance(every, str):
            try:
                TypeAdapter(target).validate_python(every)
            except ValidationError:
                continue
            return kind
    if isinstance(every, Number):
        return "cost"
    return None


def _tag_untagged_trigger(value: Any) -> Any:
    """Name the kind of a trigger payload that does not name its own.

    Triggers were serialized without a discriminator before there was
    one, so a payload already on disk — a JSON dataset, a recorded
    sample — carries only its fields. Its kind is inferred from their
    shape, so that such a payload keeps loading as the undiscriminated
    union loaded it.

    The one kind the shape cannot recover is ``token``, which is the
    defect the discriminator exists to fix: a lone ``every`` written
    by a ``token`` trigger is indistinguishable from one written by a
    ``turn`` trigger, and ``turn`` is what it loaded as, so ``turn``
    is what it still loads as. Only a payload naming ``kind`` can say
    ``token``.

    Not every shape the union used to accept is inferred. One that
    matches no trigger — ``{"every": [1]}``, or a ``budget`` missing
    its ``percent`` — is left for the discriminator to reject, where
    before it validated as ``Manual`` (the first arm, and dataclasses
    ignore extra fields) and silently meant "never checkpoint".
    """
    if not isinstance(value, dict) or "kind" in value:
        return value
    fields = cast(dict[str, Any], value)
    kind: str | None
    if "budget" in fields or "percent" in fields:
        kind = "budget"
    elif "every" not in fields:
        kind = "manual"
    else:
        kind = _untagged_every_kind(fields["every"])
    return {**fields, "kind": kind} if kind is not None else value


CheckpointTrigger = Annotated[
    Annotated[
        Manual
        | TurnInterval
        | TimeInterval
        | TokenInterval
        | CostInterval
        | BudgetPercent,
        Discriminator("kind"),
    ],
    BeforeValidator(_tag_untagged_trigger),
]
"""User-facing checkpoint trigger spec — a union of frozen dataclass
config types. See :mod:`._engine` for the runtime dispatch.

Discriminated on ``kind``, because ``TurnInterval`` and
``TokenInterval`` are both a lone integer ``every`` and so serialize
identically (as does a hand-written ``CostInterval`` whose ``every``
is written without a decimal point). Undiscriminated, each of those
came back from a JSON round-trip as ``TurnInterval``, the first arm
that fits — including ``DEFAULT_CHECKPOINT_TRIGGER``, a
``TokenInterval``, which came back as a checkpoint every 500,000
*turns*, so nothing shorter than that checkpointed at all.

A payload written before the discriminator existed does not name its
kind; :func:`_tag_untagged_trigger` names it from the field shape so
that such payloads keep loading as they did.
"""


@dataclass(frozen=True)
class TriggerFire:
    """Result of a :meth:`Trigger.tick` that fired."""

    kind: CheckpointTriggerKind
    """Which trigger fired."""

    metadata: dict[str, JsonValue] | None = None
    """Trigger-specific fire details (e.g. configured threshold vs.
    actual usage at fire time). Recorded on the checkpoint file as
    ``trigger_metadata``."""


class Trigger(Protocol):
    """Runtime trigger — one instance per checkpointed session."""

    def tick(self) -> TriggerFire | None:
        """Advance the trigger's state; return the fire details, or ``None``."""
        ...
