from __future__ import annotations

import json
from typing import Any, Literal, Union

from pydantic import BaseModel, Field


class TaskInfo(BaseModel):
    name: str
    model: str
    dataset: str
    scorer: str
    samples: int
    steps: int
    log_location: str
    tags: list[str] | None = None


class TaskProgress(BaseModel):
    task_name: str
    model: str
    samples_complete: int = 0
    samples_total: int = 0
    steps_complete: int = 0
    steps_total: int = 0
    metrics: list[MetricValue] = Field(default_factory=list)
    status: Literal["running", "success", "error", "cancelled"] = "running"


class MetricValue(BaseModel):
    scorer: str
    name: str
    value: float | int | None = None
    reducer: str | None = None


class SampleInfo(BaseModel):
    sample_id: str | int
    task_name: str = ""
    model: str = ""
    status: Literal["pending", "running", "complete", "cancelled", "error"] = "pending"
    started_at: float | None = None
    scores: dict[str, Any] | None = None


# --- Server → Client messages ---


class SnapshotMessage(BaseModel):
    type: Literal["snapshot"] = "snapshot"
    tasks: list[TaskProgress] = Field(default_factory=list)
    active_samples: list[SampleInfo] = Field(default_factory=list)
    recent_events: list[dict[str, Any]] = Field(default_factory=list)


class TaskStartMessage(BaseModel):
    type: Literal["task_start"] = "task_start"
    task: TaskInfo


class SampleCompleteMessage(BaseModel):
    type: Literal["sample_complete"] = "sample_complete"
    task_name: str
    model: str
    complete: int
    total: int


class MetricsUpdateMessage(BaseModel):
    type: Literal["metrics_update"] = "metrics_update"
    task_name: str
    model: str
    metrics: list[MetricValue]


class TaskCompleteMessage(BaseModel):
    type: Literal["task_complete"] = "task_complete"
    task_name: str
    model: str
    status: Literal["success", "error", "cancelled"]
    samples_completed: int
    error: str | None = None


class EvalCompleteMessage(BaseModel):
    type: Literal["eval_complete"] = "eval_complete"


class SampleStartMessage(BaseModel):
    type: Literal["sample_start"] = "sample_start"
    run_id: str
    eval_id: str
    sample_id: str


class SampleEndMessage(BaseModel):
    type: Literal["sample_end"] = "sample_end"
    run_id: str
    eval_id: str
    sample_id: str
    scores: dict[str, Any] | None = None


class PrintMessage(BaseModel):
    type: Literal["print"] = "print"
    message: str


class SampleCancelledMessage(BaseModel):
    type: Literal["sample_cancelled"] = "sample_cancelled"
    sample_id: str | int
    reason: str | None = None


class InputRequestedMessage(BaseModel):
    type: Literal["input_requested"] = "input_requested"
    request_id: str
    prompt: str
    sample_id: str | None = None


class InputResolvedMessage(BaseModel):
    type: Literal["input_resolved"] = "input_resolved"
    request_id: str
    responded_by: str | None = None


class ProgressUpdateMessage(BaseModel):
    type: Literal["progress_update"] = "progress_update"
    task_name: str
    model: str
    steps_complete: int
    steps_total: int


ServerMessage = Union[
    SnapshotMessage,
    TaskStartMessage,
    SampleCompleteMessage,
    MetricsUpdateMessage,
    TaskCompleteMessage,
    EvalCompleteMessage,
    SampleStartMessage,
    SampleEndMessage,
    PrintMessage,
    SampleCancelledMessage,
    ProgressUpdateMessage,
    InputRequestedMessage,
    InputResolvedMessage,
]

# --- Client → Server messages ---


class CancelSampleCommand(BaseModel):
    type: Literal["cancel_sample"] = "cancel_sample"
    sample_id: str | int


class InputResponseCommand(BaseModel):
    type: Literal["input_response"] = "input_response"
    request_id: str
    text: str


ClientMessage = Union[CancelSampleCommand, InputResponseCommand]


# --- Serialization helpers ---

_SERVER_MESSAGE_TYPES: dict[str, type[BaseModel]] = {
    "snapshot": SnapshotMessage,
    "task_start": TaskStartMessage,
    "sample_complete": SampleCompleteMessage,
    "metrics_update": MetricsUpdateMessage,
    "task_complete": TaskCompleteMessage,
    "eval_complete": EvalCompleteMessage,
    "sample_start": SampleStartMessage,
    "sample_end": SampleEndMessage,
    "print": PrintMessage,
    "sample_cancelled": SampleCancelledMessage,
    "progress_update": ProgressUpdateMessage,
    "input_requested": InputRequestedMessage,
    "input_resolved": InputResolvedMessage,
}

_CLIENT_MESSAGE_TYPES: dict[str, type[BaseModel]] = {
    "cancel_sample": CancelSampleCommand,
    "input_response": InputResponseCommand,
}


def to_json_line(msg: BaseModel) -> bytes:
    return msg.model_dump_json().encode("utf-8") + b"\n"


def parse_server_message(line: str | bytes) -> ServerMessage:
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    line = line.strip()
    data = json.loads(line)
    msg_type = data.get("type")
    cls = _SERVER_MESSAGE_TYPES.get(msg_type)
    if cls is None:
        raise ValueError(f"Unknown server message type: {msg_type}")
    return cls.model_validate(data)


def parse_client_message(line: str | bytes) -> ClientMessage:
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    line = line.strip()
    data = json.loads(line)
    msg_type = data.get("type")
    cls = _CLIENT_MESSAGE_TYPES.get(msg_type)
    if cls is None:
        raise ValueError(f"Unknown client message type: {msg_type}")
    return cls.model_validate(data)
