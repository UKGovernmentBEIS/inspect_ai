import contextlib
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Iterator, Literal

from pydantic import BaseModel, Field, JsonValue

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


class Event(BaseModel):
    """Event in a transcript."""

    event: str
    """Event type"""

    timestamp: datetime = Field(default_factory=datetime.now)
    """Time at which event occurred."""

    class Config:
        # Write the datetime as an isoformatted string including timezone
        json_encoders = {datetime: lambda v: v.astimezone().isoformat()}


class StoreEvent(Event):
    """Change to data within the current `Store`."""

    event: Literal["store"] = Field(default="store")
    """Event type."""

    changes: list[JsonChange]
    """List of changes to the `Store`."""


class StateEvent(Event):
    """Change to the current `TaskState`"""

    event: Literal["state"] = Field(default="state")
    """Event type."""

    changes: list[JsonChange]
    """List of changes to the `TaskState`"""


class ModelEvent(Event):
    """Call to a language model."""

    event: Literal["model"] = Field(default="model")
    """Event type."""

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


class LoggerEvent(Event):
    """Log message recorded with Python logger."""

    event: Literal["logger"] = Field(default="logger")
    """Event type."""

    level: str
    """Log level."""

    message: str
    """Log message."""


class InfoEvent(Event):
    """Event with custom info/data."""

    event: Literal["info"] = Field(default="info")
    """Event type."""

    data: JsonValue
    """Data provided with event."""


class ScoreEvent(Event):
    """Event with sample score."""

    event: Literal["score"] = Field(default="score")
    """Event type."""

    score: Score
    """Sample score."""


class StepEvent(Event):
    """Step within current sample or subtask."""

    event: Literal["step"] = Field(default="step")
    """Event type."""

    action: Literal["begin", "end"]
    """Designates beginning or end of event."""

    type: str | None = Field(default=None)
    """Optional 'type' field for events"""

    name: str
    """Event name."""


class SubtaskEvent(Event):
    """Subtask spawned."""

    event: Literal["subtask"] = Field(default="subtask")
    """Event type."""

    name: str
    """Name of subtask function."""

    input: dict[str, Any]
    """Subtask function inputs."""

    result: Any
    """Subtask function result."""

    transcript: "Transcript"
    """Transcript of events for subtask."""


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
        self._event(InfoEvent(data=data))

    @contextlib.contextmanager
    def step(self, name: str, type: str | None = None) -> Iterator[None]:
        """Context manager for recording StepEvent.

        Args:
            name (str): Step name.
            type (str | None): Optional step type.
        """
        # step event
        self._event(StepEvent(action="begin", name=name, type=type))

        # run the step (tracking state/store changes)
        with track_state_changes(type), track_store_changes():
            yield

        # end step event
        self._event(StepEvent(action="end", name=name, type=type))

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
        transcript()._event(StoreEvent(changes=changes))


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
            transcript()._event(StateEvent(changes=changes))
    else:
        yield


def init_transcript(transcript: Transcript) -> None:
    _transcript.set(transcript)


_transcript: ContextVar[Transcript] = ContextVar(
    "subtask_transcript", default=Transcript()
)
