"""A stand-in for `inspect_sentinel`, for tests of inspect_ai's sentinel code.

The `fake_sentinel` fixture in `tests/sentinel` installs this module as both
`inspect_sentinel` and `inspect_sentinel._integration`. It defines the names
inspect_ai imports from them, and enough of the author API (`@monitor`, `@protocol`, groups,
steps and reports) to write monitors and protocols in tests.

A lone instance runs at the empty path. A list or mapping of instances runs
each member at its name and returns the most severe decision. Every report,
monitor failure and cancellation goes to the host's `Recorder`, as
`inspect_sentinel` records them. A protocol is handed no escalations. There
are no compositions (`observe_only`, `threshold`, `sequential`, `concurrent`)
and no final decisions: their behavior is `inspect_sentinel`'s, and its own
tests cover it.
"""

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import wraps
from typing import (
    Any,
    Generic,
    Literal,
    TypeAlias,
    TypeVar,
    cast,
    get_type_hints,
    overload,
)

from anyio import get_cancelled_exc_class

from inspect_ai._sentinel._config import SentinelConfig, SentinelEntry
from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_add,
    registry_info,
    registry_lookup,
    registry_name,
    registry_params,
    registry_tag,
    registry_unqualified_name,
)
from inspect_ai.event import SentinelAction, SentinelSuspicion
from inspect_ai.model import ChatMessage, ChatMessageTool, GenerateConfig, ModelOutput
from inspect_ai.scorer import Reference
from inspect_ai.tool import ToolCall, ToolCallView, ToolChoice, ToolInfo, ToolResult
from inspect_ai.util import Store, StoreModel


@dataclass(frozen=True, kw_only=True)
class Observation:
    suspicion: SentinelSuspicion
    explanation: str | None = None
    references: list[Reference] = field(default_factory=list[Reference])
    metadata: dict[str, Any] | None = None

    @classmethod
    def score(
        cls,
        suspicion: SentinelSuspicion,
        explanation: str | None = None,
        *,
        references: Sequence[Reference] = (),
    ) -> "Observation":
        return cls(
            suspicion=suspicion, explanation=explanation, references=list(references)
        )


@dataclass(frozen=True, kw_only=True)
class Decision:
    action: SentinelAction
    audit: bool = False
    modified: ToolCall | None = None
    explanation: str | None = None
    references: list[Reference] = field(default_factory=list[Reference])
    message: str | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def proceed(cls, explanation: str | None = None) -> "Decision":
        return cls(action="proceed", explanation=explanation)

    @classmethod
    def reject(
        cls,
        explanation: str | None = None,
        *,
        message: str | None = None,
        references: Sequence[Reference] = (),
    ) -> "Decision":
        return cls(
            action="reject",
            explanation=explanation,
            message=message,
            references=list(references),
        )

    @classmethod
    def terminate(cls, explanation: str | None = None) -> "Decision":
        return cls(action="terminate", explanation=explanation)

    @classmethod
    def escalate(cls, explanation: str | None = None) -> "Decision":
        return cls(action="escalate", explanation=explanation)


Report: TypeAlias = Observation | Decision

R = TypeVar("R", bound=Report)


@dataclass(frozen=True)
class Reported(Generic[R]):
    name: str
    path: str
    report: R
    function: str


Escalations: TypeAlias = tuple[Reported[Decision], ...]


@dataclass(frozen=True)
class Failed:
    name: str
    path: str
    function: str
    error: Exception


@dataclass(frozen=True)
class HumanDecision:
    stage: Literal["model_input", "model_output", "tool_call", "tool_result"]
    step_id: str
    call_ids: tuple[str, ...]
    decided: Reported[Decision]


@dataclass(frozen=True)
class BeforeGenerate:
    model: str
    conversation: str
    input: list[ChatMessage]
    agent_messages: list[ChatMessage] | None
    history: list[ChatMessage] | None = field(default=None, kw_only=True)
    human_decisions: tuple[HumanDecision, ...] | None = field(
        default=None, kw_only=True
    )
    tools: list[ToolInfo]
    tool_choice: ToolChoice
    config: GenerateConfig


@dataclass(frozen=True)
class AfterGenerate:
    model: str
    conversation: str
    input: list[ChatMessage]
    agent_messages: list[ChatMessage] | None
    history: list[ChatMessage] | None = field(default=None, kw_only=True)
    human_decisions: tuple[HumanDecision, ...] | None = field(
        default=None, kw_only=True
    )
    tools: list[ToolInfo]
    tool_choice: ToolChoice
    config: GenerateConfig
    output: ModelOutput


@dataclass(frozen=True)
class Truncation:
    original_bytes: int
    limit_bytes: int


@dataclass(frozen=True)
class BeforeToolCall:
    conversation: str
    message: str
    message_id: str
    call: ToolCall
    view: ToolCallView
    input: list[ChatMessage] | None
    agent_messages: list[ChatMessage] | None
    history: list[ChatMessage] | None = field(default=None, kw_only=True)
    human_decisions: tuple[HumanDecision, ...] | None = field(
        default=None, kw_only=True
    )
    tools: list[ToolInfo] | None = None
    tool_choice: ToolChoice | None = None


@dataclass(frozen=True)
class AfterToolCall:
    conversation: str
    message: str
    message_id: str
    call: ToolCall
    result: ChatMessageTool
    output: ToolResult
    view: ToolCallView
    input: list[ChatMessage] | None
    agent_messages: list[ChatMessage] | None
    history: list[ChatMessage] | None = field(default=None, kw_only=True)
    human_decisions: tuple[HumanDecision, ...] | None = field(
        default=None, kw_only=True
    )
    tools: list[ToolInfo] | None = None
    tool_choice: ToolChoice | None = None
    truncated: Truncation | Literal[False] | None = None


Step: TypeAlias = BeforeGenerate | AfterGenerate | BeforeToolCall | AfterToolCall

STAGES: tuple[type[Step], ...] = (
    BeforeGenerate,
    AfterGenerate,
    BeforeToolCall,
    AfterToolCall,
)


@dataclass(frozen=True, kw_only=True)
class EvalContext:
    task: str
    task_description: str | None
    sample_id: str | int
    epoch: int
    sample_description: str | None
    sample_input: str | list[ChatMessage]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class HumanAnswer:
    decision: str
    reason: str | None = None
    modified: ToolCall | None = None


SMT = TypeVar("SMT", bound=StoreModel)


@dataclass(frozen=True, kw_only=True)
class Context:
    path: str
    # the host's `_HostNative`; inspect_sentinel wraps it in a `Host`
    host: Any
    store: Store

    @property
    def eval(self) -> EvalContext | None:
        return cast(EvalContext | None, self.host.eval)

    def store_as(self, model_cls: type[SMT]) -> SMT:
        return model_cls(store=self.store, instance=self.path)


@dataclass(frozen=True, kw_only=True)
class HostContext:
    host: Any
    recorder: Any
    store: Store

    @property
    def context(self) -> Context:
        return Context(path="", host=self.host, store=self.store)


Monitor: TypeAlias = Callable[[Context, Any], Awaitable[Observation | None]]
Protocol: TypeAlias = Callable[[Context, Any, Escalations], Awaitable[Decision | None]]


class MonitorGroup:
    """Several monitor functions configured as one instance."""

    def __init__(self, *functions: Monitor) -> None:
        self.functions: tuple[Callable[..., Awaitable[Report | None]], ...] = functions


class ProtocolGroup:
    """Several protocol functions configured as one instance."""

    def __init__(self, *functions: Protocol) -> None:
        self.functions: tuple[Callable[..., Awaitable[Report | None]], ...] = functions


Kind = Literal["monitor", "protocol"]
F = TypeVar("F", bound=Callable[..., Any])

# the configuration entry an instance was created from
_ENTRY = "__fake_sentinel_entry__"


@overload
def monitor(factory: F, /) -> F: ...
@overload
def monitor(*, name: str | None = None, version: int = 0) -> Callable[[F], F]: ...
def monitor(
    factory: F | None = None, /, *, name: str | None = None, version: int = 0
) -> F | Callable[[F], F]:
    """Register a monitor factory, as `@monitor` or `@monitor(name=, version=)`."""
    if factory is not None:
        return _register("monitor", factory, None, 0)
    return lambda factory: _register("monitor", factory, name, version)


@overload
def protocol(factory: F, /) -> F: ...
@overload
def protocol(*, name: str | None = None, version: int = 0) -> Callable[[F], F]: ...
def protocol(
    factory: F | None = None, /, *, name: str | None = None, version: int = 0
) -> F | Callable[[F], F]:
    """Register a protocol factory, as `@protocol` or `@protocol(name=, version=)`."""
    if factory is not None:
        return _register("protocol", factory, None, 0)
    return lambda factory: _register("protocol", factory, name, version)


def _register(kind: Kind, factory: F, name: str | None, version: int) -> F:
    info = RegistryInfo(
        type=kind, name=registry_name(factory, name or factory.__name__)
    )

    @wraps(factory)
    def create(*args: Any, **kwargs: Any) -> object:
        instance = factory(*args, **kwargs)
        registry_tag(factory, instance, info, *args, **kwargs)
        arguments = inspect.signature(factory).bind(*args, **kwargs).arguments
        nested = {k: v for k, v in arguments.items() if _is_sentinels(v)}
        entry = {
            "name": info.name,
            "params": {
                k: v for k, v in registry_params(instance).items() if k not in nested
            },
            **({"version": version} if version else {}),
            **{k: config_from_sentinel(v).model_dump() for k, v in nested.items()},
        }
        setattr(instance, _ENTRY, entry)
        return instance

    registry_add(create, info)
    return cast(F, create)


def _is_sentinels(value: object) -> bool:
    if isinstance(value, Mapping):
        values = list(cast(Mapping[str, object], value).values())
    elif isinstance(value, list):
        values = cast(list[object], value)
    else:
        values = [value]
    return bool(values) and all(is_registry_object(v) for v in values)


Sentinels: TypeAlias = Any


@dataclass(frozen=True)
class Group:
    """A list or mapping of instances, as `resolve_sentinel` returns it."""

    members: tuple[tuple[str, object], ...]


def sentinel_from_config(config: str | SentinelConfig | Any) -> Sentinels:
    if isinstance(config, str):
        config = {"name": config}
    return _build(SentinelConfig.model_validate(config).root)


def _build(
    layer: SentinelEntry | list[SentinelEntry] | dict[str, SentinelEntry],
) -> Any:
    if isinstance(layer, list):
        return [_build(entry) for entry in layer]
    if isinstance(layer, dict):
        return {name: _build(entry) for name, entry in layer.items()}
    factory = registry_lookup("protocol", layer.name) or registry_lookup(
        "monitor", layer.name
    )
    if factory is None:
        raise ValueError(f"{layer.name!r} is not a registered monitor or protocol.")
    nested = {k: _build(v.root) for k, v in layer.nested.items()}
    return cast(Callable[..., object], factory)(**layer.params, **nested)


def config_from_sentinel(sentinels: Sentinels) -> SentinelConfig:
    if isinstance(sentinels, list):
        layer: Any = [getattr(s, _ENTRY) for s in cast(list[object], sentinels)]
    elif isinstance(sentinels, Mapping):
        mapping = cast(Mapping[str, object], sentinels)
        layer = {name: getattr(s, _ENTRY) for name, s in mapping.items()}
    else:
        layer = getattr(sentinels, _ENTRY)
    return SentinelConfig.model_validate(layer)


def resolve_sentinel(sentinels: Sentinels) -> object:
    if isinstance(sentinels, Mapping):
        mapping = cast(Mapping[str, object], sentinels)
        return Group(tuple(mapping.items()))
    if isinstance(sentinels, list):
        return Group(
            tuple(
                (registry_unqualified_name(s), s) for s in cast(list[object], sentinels)
            )
        )
    return sentinels


def _functions(instance: object) -> tuple[Callable[..., Awaitable[Report | None]], ...]:
    if isinstance(instance, MonitorGroup | ProtocolGroup):
        return instance.functions
    return (cast(Callable[..., Awaitable[Report | None]], instance),)


def _stage(function: Callable[..., Any]) -> type[Step]:
    stage = get_type_hints(function)["step"]
    assert stage in STAGES, f"{function.__name__} must take one stage, not {stage}"
    return cast(type[Step], stage)


def _instances(root: object) -> tuple[tuple[str, str, object], ...]:
    """(name, path, instance) for each instance the root runs."""
    if isinstance(root, Group):
        return tuple((name, name, instance) for name, instance in root.members)
    return ((registry_unqualified_name(root), "", root),)


def watched_stages(root: object) -> set[type[Step]]:
    return {
        _stage(function)
        for _, _, instance in _instances(root)
        for function in _functions(instance)
    }


_PRECEDENCE: dict[SentinelAction, int] = {
    "proceed": 1,
    "escalate": 2,
    "modify": 3,
    "reject": 4,
    "terminate": 5,
}


async def run_sentinel(root: object, host: HostContext, step: Step) -> Decision | None:
    decisions = [
        decision
        for name, path, instance in _instances(root)
        for decision in await _run_instance(name, path, instance, host, step)
    ]
    return max(decisions, key=lambda d: _PRECEDENCE[d.action], default=None)


async def _run_instance(
    name: str, path: str, instance: object, host: HostContext, step: Step
) -> list[Decision]:
    info = registry_info(instance)
    context = Context(path=path, host=host.host, store=host.store)
    decisions: list[Decision] = []
    for function in _functions(instance):
        if _stage(function) is not type(step):
            continue
        try:
            report = await (
                function(context, step)
                if info.type == "monitor"
                else function(context, step, ())
            )
        except get_cancelled_exc_class():
            host.recorder.cancelled(context, info.name, step, name)
            raise
        except Exception as ex:
            if info.type == "protocol":
                raise
            host.recorder.failed(
                context, info.name, step, Failed(name, path, function.__name__, ex)
            )
            continue
        if report is not None:
            host.recorder.record(
                context,
                info.name,
                step,
                Reported(name, path, report, function.__name__),
            )
            if isinstance(report, Decision):
                decisions.append(report)
    return decisions


# the registry name of inspect_sentinel's `human()`; a test registers the
# protocol that asks its person under it
_HUMAN = "inspect_sentinel/human"


def kept_human_decision(
    factory: str, step: Step, step_id: str, reported: Reported[Report]
) -> HumanDecision | None:
    if factory != _HUMAN or not isinstance(reported.report, Decision):
        return None
    decided = Reported(reported.name, reported.path, reported.report, reported.function)
    if isinstance(step, AfterGenerate):
        message = step.output.message if step.output.choices else None
        calls = (message.tool_calls if message is not None else None) or []
        return HumanDecision(
            "model_output", step_id, tuple(c.id for c in calls), decided
        )
    if isinstance(step, BeforeGenerate):
        return HumanDecision("model_input", step_id, (), decided)
    stage: Literal["tool_call", "tool_result"] = (
        "tool_result" if isinstance(step, AfterToolCall) else "tool_call"
    )
    return HumanDecision(stage, step_id, (step.call.id,), decided)


def supersedes(path: str, reported: Reported[Decision], kept: HumanDecision) -> bool:
    own = kept.decided.path
    above = path == "" or own == path or own.startswith(path + "/")
    return above and kept.decided.report.action == reported.report.action
