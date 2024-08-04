import contextlib
from contextvars import ContextVar
from datetime import datetime
from typing import (
    Any,
    Iterator,
    Literal,
    TypeAlias,
    Union,
)

from pydantic import BaseModel, Field, JsonValue, field_serializer

from inspect_ai._util.constants import SAMPLE_SUBTASK
from inspect_ai._util.json import JsonChange, json_changes
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer._metric import Score
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from .._task_state import state_jsonable
from .store import store, store_changes, store_jsonable


class BaseEvent(BaseModel):
    event: str
    """Type of event."""

    timestamp: datetime = Field(default_factory=datetime.now)
    """Time at which event occurred."""

    data: BaseModel
    """Type specific event data."""

    @field_serializer("timestamp")
    def serialize_timestamp(self, dt: datetime) -> str:
        return dt.astimezone().isoformat()


class StoreEvent(BaseEvent):
    """Change to data within the current `Store`."""

    class Data(BaseModel):
        changes: list[JsonChange]

    event: Literal["store"] = Field(default="store")
    """Event type."""

    data: Data
    """Event datta."""


class StateEvent(BaseEvent):
    """Change to the current `TaskState`"""

    class Data(BaseModel):
        changes: list[JsonChange]

    event: Literal["state"] = Field(default="state")
    """Event type."""

    data: Data
    """Event data."""


class ModelEvent(BaseEvent):
    """Call to a language model."""

    class Data(BaseModel):
        model: str
        """Model name."""

        input: list[ChatMessage]
        """Model input (list of messages)."""

        tools: list[ToolInfo]
        """Tools available to the model."""

        tool_choice: ToolChoice
        """Directive to the model which tools to prefer."""

        config: GenerateConfig
        """Generate config used for call to model."""

        output: ModelOutput
        """Output from model."""

    event: Literal["model"] = Field(default="model")
    """Event type."""

    data: Data
    """Event data."""


class LoggerEvent(BaseEvent):
    """Log message recorded with Python logger."""

    class Data(BaseModel):
        name: str | None = Field(default=None)
        """Name of logging module."""

        level: str
        """Logging level."""

        message: str
        """Log message."""

        created: float
        """Message created time."""

        filename: str = Field(default="unknown")
        """Logged from filename."""

        module: str = Field(default="unknown")
        """Logged from module."""

        lineno: int = Field(default=0)
        """Logged from line number."""

        args: JsonValue = Field(default=None)
        """Extra arguments passed to log function."""

    event: Literal["logger"] = Field(default="logger")
    """Event type."""

    data: Data
    """Event data."""


class InfoEvent(BaseEvent):
    """Event with custom info/data."""

    class Data(BaseModel):
        data: JsonValue

    event: Literal["info"] = Field(default="info")
    """Event type."""

    data: Data
    """Event data."""


class ScoreEvent(BaseEvent):
    """Event with sample score."""

    class Data(BaseModel):
        score: Score

    event: Literal["score"] = Field(default="score")
    """Event type."""

    data: Data
    """Event data."""


class StepEvent(BaseEvent):
    """Step within current sample or subtask."""

    class Data(BaseModel):
        action: Literal["begin", "end"]
        """Designates beginning or end of event."""

        type: str | None = Field(default=None)
        """Optional 'type' field for events"""

        name: str
        """Event name."""

    event: Literal["step"] = Field(default="step")
    """Event type."""

    data: Data
    """Event data."""


class SubtaskEvent(BaseEvent):
    """Subtask spawned."""

    class Data(BaseModel):
        name: str
        """Name of subtask function."""

        input: dict[str, Any]
        """Subtask function inputs."""

        result: Any
        """Subtask function result."""

        transcript: "Transcript"
        """Transcript of events for subtask."""

    event: Literal["subtask"] = Field(default="subtask")
    """Event type."""

    data: Data
    """Event data."""


Event: TypeAlias = Union[
    StateEvent
    | StoreEvent
    | ModelEvent
    | ScoreEvent
    | LoggerEvent
    | InfoEvent
    | StepEvent
    | SubtaskEvent,
]
"""Event in a transcript."""


class Transcript(BaseModel):
    """Transcript of events."""

    name: str = Field(default="")
    """Transcript name (e.g. 'sample')."""

    events: list[Event] = Field(default=[])
    """List of events."""

    def info(self, data: JsonValue) -> None:
        """Add an `InfoEvent` to the transcript.

        Args:
           data (JsonValue): Data associated with the event.
        """
        self._event(InfoEvent(data=InfoEvent.Data(data=data)))

    @contextlib.contextmanager
    def step(self, name: str, type: str | None = None) -> Iterator[None]:
        """Context manager for recording StepEvent.

        Args:
            name (str): Step name.
            type (str | None): Optional step type.
        """
        # step event
        self._event(
            StepEvent(data=StepEvent.Data(action="begin", name=name, type=type))
        )

        # run the step (tracking state/store changes)
        with track_state_changes(type), track_store_changes():
            yield

        # end step event
        self._event(StepEvent(data=StepEvent.Data(action="end", name=name, type=type)))

    def _event(self, event: Event) -> None:
        self.events.append(event)


def transcript() -> Transcript:
    """Get the current `Transcript`."""
    return _transcript.get()


@contextlib.contextmanager
def track_store_changes() -> Iterator[None]:
    before = store_jsonable(store())
    yield
    after = store_jsonable(store())

    changes = store_changes(before, after)
    if changes:
        transcript()._event(StoreEvent(data=StoreEvent.Data(changes=changes)))


@contextlib.contextmanager
def track_state_changes(type: str | None = None) -> Iterator[None]:
    # we only want to track for step() inside the the sample
    # (solver level tracking is handled already and there are
    # no state changes in subtasks)
    if transcript().name == SAMPLE_SUBTASK and type != "solver":
        before = state_jsonable()
        yield
        after = state_jsonable()

        changes = json_changes(before, after)
        if changes:
            transcript()._event(StateEvent(data=StateEvent.Data(changes=changes)))
    else:
        yield


def init_transcript(transcript: Transcript) -> None:
    _transcript.set(transcript)


_transcript: ContextVar[Transcript] = ContextVar(
    "subtask_transcript", default=Transcript()
)
