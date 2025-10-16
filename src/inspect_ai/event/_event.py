from typing import TypeAlias, Union

from inspect_ai.event._score_edit import ScoreEditEvent

from ._approval import ApprovalEvent
from ._error import ErrorEvent
from ._info import InfoEvent
from ._input import InputEvent
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
    ApprovalEvent,
    InputEvent,
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
