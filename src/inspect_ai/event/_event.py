from typing import Annotated, TypeAlias, Union

from pydantic import Field

from inspect_ai.event._score_edit import ScoreEditEvent

from ._anchor import AnchorEvent
from ._approval import ApprovalEvent
from ._branch import BranchEvent
from ._checkpoint import CheckpointEvent
from ._compaction import CompactionEvent
from ._error import ErrorEvent
from ._info import InfoEvent
from ._input import InputEvent
from ._interrupt import InterruptEvent
from ._logger import LoggerEvent
from ._model import ModelEvent
from ._sample_init import SampleInitEvent
from ._sample_limit import SampleLimitEvent
from ._sandbox import SandboxEvent
from ._score import ScoreEvent
from ._span import SpanBeginEvent, SpanEndEvent
from ._state import StateEvent
from ._step import StepEvent
from ._store import StoreEvent
from ._subtask import SubtaskEvent
from ._tool import ToolEvent

Event: TypeAlias = Union[
    SampleInitEvent,
    SampleLimitEvent,
    SandboxEvent,
    StateEvent,
    StoreEvent,
    ModelEvent,
    ToolEvent,
    AnchorEvent,
    ApprovalEvent,
    BranchEvent,
    CheckpointEvent,
    CompactionEvent,
    InputEvent,
    InterruptEvent,
    ScoreEvent,
    ScoreEditEvent,
    ErrorEvent,
    LoggerEvent,
    InfoEvent,
    SpanBeginEvent,
    SpanEndEvent,
    StepEvent,
    SubtaskEvent,
]
"""Event in a transcript."""


DiscriminatedEvent: TypeAlias = Annotated[Event, Field(discriminator="event")]
"""`Event` tagged with a pydantic discriminator for fast validation.

Every member carries a unique ``event`` Literal, so validating against this
alias is a single keyed lookup instead of pydantic trying all 23 union
members in turn (and re-running each candidate's validators — including the
timestamp ``BeforeValidator`` — on every rejected branch).

Use this in the ``list[Event]`` fields that are validated when reading logs.
The plain :data:`Event` alias above is deliberately left un-annotated so
``get_args(Event)`` and other type introspection keep working; wrapping the
public alias itself is what forced the revert of #2714. Serialization is
unaffected — the ``event`` tag is already emitted by every member."""
