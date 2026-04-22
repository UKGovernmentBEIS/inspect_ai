from inspect_ai._util.deprecation import relocated_module_attribute

from ._approval import ApprovalEvent
from ._branch import BranchEvent
from ._compaction import CompactionEvent
from ._error import ErrorEvent
from ._event import Event
from ._info import InfoEvent
from ._input import InputEvent
from ._logger import LoggerEvent, LoggingLevel, LoggingMessage
from ._model import ModelEvent
from ._sample_init import SampleInitEvent
from ._sample_limit import SampleLimitEvent
from ._sandbox import SandboxEvent
from ._score import ScoreEvent
from ._score_edit import ScoreEditEvent
from ._span import SpanBeginEvent, SpanEndEvent
from ._state import StateEvent
from ._step import StepEvent
from ._store import StoreEvent
from ._subtask import SubtaskEvent
from ._timeline import (
    Outline,
    OutlineNode,
    Timeline,
    TimelineEvent,
    TimelineSpan,
    timeline_branch,
    timeline_build,
    timeline_dump,
    timeline_filter,
    timeline_load,
)
from ._tool import ToolEvent
from ._tree import (
    EventTree,
    EventTreeNode,
    EventTreeSpan,
    event_sequence,
    event_tree,
    event_tree_walk,
)

__all__ = [
    "Event",
    "ApprovalEvent",
    "BranchEvent",
    "ErrorEvent",
    "InfoEvent",
    "InputEvent",
    "LoggerEvent",
    "ModelEvent",
    "CompactionEvent",
    "SampleInitEvent",
    "SampleLimitEvent",
    "SandboxEvent",
    "ScoreEvent",
    "ScoreEditEvent",
    "SpanBeginEvent",
    "SpanEndEvent",
    "StateEvent",
    "StepEvent",
    "StoreEvent",
    "SubtaskEvent",
    "ToolEvent",
    "LoggingLevel",
    "LoggingMessage",
    "event_tree",
    "event_sequence",
    "event_tree_walk",
    "EventTree",
    "EventTreeSpan",
    "EventTreeNode",
    "Timeline",
    "TimelineEvent",
    "TimelineSpan",
    "Outline",
    "OutlineNode",
    "timeline_build",
    "timeline_dump",
    "timeline_filter",
    "timeline_load",
    "timeline_branch",
]

_EVENT_TREE_VERSION_0_3_180 = "0.3.180"
_REMOVED_IN = "0.4"

relocated_module_attribute(
    "EventNode",
    "inspect_ai.event.EventTreeNode",
    _EVENT_TREE_VERSION_0_3_180,
    _REMOVED_IN,
)

relocated_module_attribute(
    "SpanNode",
    "inspect_ai.event.EventTreeSpan",
    _EVENT_TREE_VERSION_0_3_180,
    _REMOVED_IN,
)
