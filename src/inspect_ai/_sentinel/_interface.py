"""What inspect_ai and the package that runs sentinels exchange.

inspect_ai is the host: it builds each step, makes the model calls, asks a person, emits `SentinelEvent`s and applies the verdict. The implementation, `inspect_sentinel`, chooses the root from what the user gave, says which stages it watches and runs it for one step. It calls `register_sentinel` when imported.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, NamedTuple, Protocol, TypeAlias

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.event._sentinel import (
    SentinelAction,
    SentinelStage,
    SentinelStatus,
    SentinelSuspicion,
)
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer._metric import Reference
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._store import Store


@dataclass(frozen=True)
class ModelInputStep:
    """One of the agent's generates, before the request is sent.

    The messages, tools and config are the host's own objects; the implementation must not mutate them.
    """

    stage: ClassVar[SentinelStage] = "model_input"

    model: str
    """The model the request is for, as `provider/name`."""

    conversation: str
    """Id linking this agent's steps across compactions."""

    input: list[ChatMessage]
    """Exactly what the model is sent."""

    history: list[ChatMessage]
    """The caller's message list."""

    tools: list[ToolInfo]
    """The tools the model is offered."""

    tool_choice: ToolChoice
    """The tool choice the model is sent."""

    config: GenerateConfig
    """The generation config the model is sent."""


@dataclass(frozen=True)
class ModelOutputStep:
    """One of the agent's generates, after it completed and before its output reaches the agent."""

    stage: ClassVar[SentinelStage] = "model_output"

    model: str
    """The model the request was for, as `provider/name`."""

    conversation: str
    """Id linking this agent's steps across compactions."""

    input: list[ChatMessage]
    """Exactly what the model was sent."""

    history: list[ChatMessage]
    """The caller's message list."""

    tools: list[ToolInfo]
    """The tools the model was offered."""

    tool_choice: ToolChoice
    """The tool choice the model was sent."""

    config: GenerateConfig
    """The generation config the model was sent."""

    output: ModelOutput
    """What the model returned."""


@dataclass(frozen=True)
class ToolCallStep:
    """A tool call about to execute."""

    stage: ClassVar[SentinelStage] = "tool_call"

    conversation: str
    """Id linking this agent's steps across compactions."""

    message: str
    """Assistant text alongside the call."""

    call: ToolCall
    """The call as it will execute."""

    view: ToolCallView
    """Rendering of the call."""

    input: list[ChatMessage] | None
    """What the model was sent for the generate that produced the call, or `None` when no recorded model call produced it."""

    history: list[ChatMessage]
    """The scaffold's message list."""

    tools: list[ToolInfo] | None
    """The tools offered to the model call that produced the call; `None` exactly when `input` is `None`."""


class Truncation(NamedTuple):
    """A cut the host made to a tool's output before the model saw it."""

    original_bytes: int
    """The size of the tool's output, in UTF-8 bytes of its text."""

    limit_bytes: int
    """The limit the output was cut to, in bytes."""


@dataclass(frozen=True)
class ToolResultStep:
    """A tool call that has executed, before the model sees its result."""

    stage: ClassVar[SentinelStage] = "tool_result"

    conversation: str
    """Id linking this agent's steps across compactions."""

    message: str
    """Assistant text alongside the call."""

    call: ToolCall
    """The call as executed."""

    result: ChatMessageTool
    """What the model will see, after truncation."""

    output: ToolResult
    """The tool's untruncated return value."""

    view: ToolCallView
    """Rendering of the call."""

    input: list[ChatMessage] | None
    """As `ToolCallStep.input`."""

    history: list[ChatMessage]
    """The scaffold's message list."""

    tools: list[ToolInfo] | None
    """As `ToolCallStep.tools`."""

    truncated: Truncation | None
    """The cut the host made to the output, or `None` when it made none."""


SentinelStep: TypeAlias = (
    ModelInputStep | ModelOutputStep | ToolCallStep | ToolResultStep
)
"""A step at any stage."""


@dataclass(frozen=True)
class SentinelVerdict:
    """The outcome of a step, as the host applies it."""

    action: Literal["proceed", "modify", "reject", "terminate"]
    """What happens at the step."""

    message: str | None = None
    """Text the agent reads when the step is rejected."""

    explanation: str | None = None
    """Why, for a terminate's reason."""

    modified: ToolCall | None = None
    """The replacement call, for `modify`."""


class SentinelEscalation(NamedTuple):
    """An escalation shown to a person who is asked about a step."""

    name: str
    """Instance name of the monitor or protocol that escalated."""

    explanation: str | None
    """Why it escalated."""


@dataclass(frozen=True)
class SentinelHumanAnswer:
    """What a person answered when asked about a step."""

    decision: Literal["approve", "reject", "terminate"]
    """One of the offered choices or, when the person ended the prompt without one, `reject` if it was offered and `terminate` otherwise."""

    reason: str | None = None
    """The reason the approval surface gives for the answer."""


@dataclass(frozen=True, kw_only=True)
class SentinelEvalContext:
    """The eval sample the step belongs to."""

    task: str
    task_description: str | None
    sample_id: str | int
    epoch: int
    sample_description: str | None
    sample_input: str | list[ChatMessage]
    metadata: dict[str, Any]
    """Task metadata merged with sample metadata."""


@dataclass(frozen=True, kw_only=True)
class SentinelRecord:
    """One report, failure or cancellation of a monitor or protocol, which the host records as a `SentinelEvent` for the step."""

    factory: str
    """Registry name of the factory, package prefix included."""

    path: str
    """Instance path (e.g. "attempt/internet_attempt"); empty for the root."""

    kind: Literal["observation", "decision"]
    status: SentinelStatus
    function: str | None = None
    suspicion: SentinelSuspicion | None = None
    action: SentinelAction | None = None
    audit: bool = False
    message: str | None = None
    explanation: str | None = None
    references: Sequence[Reference] = ()
    metadata: dict[str, Any] | None = None
    modified: ToolCall | None = None
    error: str | None = None


class SentinelHost(Protocol):
    """What the host gives the implementation for one step."""

    @property
    def eval(self) -> SentinelEvalContext | None:
        """The eval sample, or `None` outside one."""
        ...

    @property
    def store(self) -> Store:
        """The sample store."""
        ...

    async def generate(
        self,
        input: str | list[ChatMessage],
        *,
        model: str | None = None,
        role: str | None = None,
        tools: list[ToolInfo] | None = None,
        tool_choice: ToolChoice | None = None,
        config: GenerateConfig | None = None,
    ) -> ModelOutput:
        """Generate with the model for `role` (by default `monitor`), or with `model`."""
        ...

    async def ask_human(
        self,
        step: SentinelStep,
        choices: Sequence[str],
        escalations: Sequence[SentinelEscalation],
    ) -> SentinelHumanAnswer:
        """Ask a person to decide about the step, offering `choices` in order."""
        ...

    def record(self, record: SentinelRecord) -> None:
        """Record a report about the step this host was given for, at that step's stage and conversation."""
        ...


class SentinelImplementation(Protocol):
    """The package that runs sentinels."""

    def resolve(self, sentinels: object) -> object:
        """Choose the root, the one protocol that decides each step, from what the user gave.

        Raises:
            ValueError: If `sentinels` holds no protocol.
        """
        ...

    def watched_stages(self, root: object) -> frozenset[SentinelStage]:
        """The stages at which the root runs."""
        ...

    async def run(
        self, root: object, host: SentinelHost, step: SentinelStep
    ) -> SentinelVerdict | None:
        """Run the root for one step and return its outcome, or `None` when nothing decided."""
        ...


_implementation: SentinelImplementation | None = None


def register_sentinel(implementation: SentinelImplementation) -> None:
    """Register the package that runs sentinels.

    Registering the same object again does nothing.

    Raises:
        RuntimeError: If a different implementation is registered.
    """
    global _implementation
    if _implementation is not None and _implementation is not implementation:
        raise RuntimeError(
            f"A sentinel implementation ({type(_implementation).__module__}) is "
            f"already registered, so {type(implementation).__module__} cannot be."
        )
    _implementation = implementation


def sentinel_implementation() -> SentinelImplementation:
    """The registered implementation.

    Raises:
        PrerequisiteError: If none is registered.
    """
    if _implementation is None:
        raise PrerequisiteError(
            "[bold]ERROR[/bold]: Sentinel support requires the inspect_sentinel package. "
            "Install it with:\n\n"
            "[bold]pip install inspect-sentinel[/bold]"
        )
    return _implementation


@contextmanager
def sentinel_registered(
    implementation: SentinelImplementation | None,
) -> Iterator[None]:
    """For tests: put `implementation`, or nothing, in place of the registered one until exit."""
    global _implementation
    registered = _implementation
    _implementation = implementation
    try:
        yield
    finally:
        _implementation = registered
