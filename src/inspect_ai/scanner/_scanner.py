from functools import wraps
from typing import (
    Any,
    Awaitable,
    Callable,
    Literal,
    ParamSpec,
    Protocol,
    Required,
    TypedDict,
    TypeVar,
    cast,
)

from typing_extensions import overload

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_name,
    registry_tag,
)
from inspect_ai.log._transcript import Event, ModelEvent, ToolEvent
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.scanner._result import Result
from inspect_ai.scanner._transcript import Transcript

from ._filter import (
    EventType,
    MessageType,
    normalize_events_filter,
    normalize_messages_filter,
)
from ._loader import Loader

T = TypeVar("T", contravariant=True)
P = ParamSpec("P")


class Scanner(Protocol[T]):
    def __call__(self, input: T, /) -> Awaitable[Result | None]: ...

    __scanner__: "ScannerConfig"


class ScannerConfig(TypedDict, total=False):
    name: Required[str]
    messages: list[MessageType]
    events: list[EventType]
    loader: Loader[Any]


ScannerFactory = Callable[P, Scanner[T]]


# overloads for both messages and events present => factory must return Scanner[Transcript]
@overload
def scanner(
    *,
    messages: MessageType,
    events: list[EventType],
    loader: Loader[Transcript] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, Transcript]], ScannerFactory[P, Transcript]]: ...
@overload
def scanner(
    *,
    messages: list[MessageType],
    events: EventType,
    loader: Loader[Transcript] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, Transcript]], ScannerFactory[P, Transcript]]: ...
@overload
def scanner(
    *,
    messages: list[MessageType],
    events: list[EventType],
    loader: Loader[Transcript] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, Transcript]], ScannerFactory[P, Transcript]]: ...
@overload
def scanner(
    *,
    messages: MessageType,
    events: EventType,
    loader: Loader[Transcript] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, Transcript]], ScannerFactory[P, Transcript]]: ...


# overload for messages as a list (events absent) => list[ChatMessage]
@overload
def scanner(
    *,
    messages: list[MessageType],
    events: None = ...,
    loader: Loader[list[ChatMessage]] | None = ...,
    name: str | None = ...,
) -> Callable[
    [ScannerFactory[P, list[ChatMessage]]], ScannerFactory[P, list[ChatMessage]]
]: ...


# (E) overload for events is a list (messages absent) => list[Event]
@overload
def scanner(
    *,
    events: list[EventType],
    messages: None = ...,
    loader: Loader[list[Event]] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, list[Event]]], ScannerFactory[P, list[Event]]]: ...


# (F) SINGLE-VALUE messages (events absent) => specific message type
@overload
def scanner(
    *,
    messages: Literal["system"],
    events: None = ...,
    loader: Loader[ChatMessageSystem] | None = ...,
    name: str | None = ...,
) -> Callable[
    [ScannerFactory[P, ChatMessageSystem]], ScannerFactory[P, ChatMessageSystem]
]: ...
@overload
def scanner(
    *,
    messages: Literal["user"],
    events: None = ...,
    loader: Loader[ChatMessageUser] | None = ...,
    name: str | None = ...,
) -> Callable[
    [ScannerFactory[P, ChatMessageUser]], ScannerFactory[P, ChatMessageUser]
]: ...
@overload
def scanner(
    *,
    messages: Literal["assistant"],
    events: None = ...,
    loader: Loader[ChatMessageAssistant] | None = ...,
    name: str | None = ...,
) -> Callable[
    [ScannerFactory[P, ChatMessageAssistant]], ScannerFactory[P, ChatMessageAssistant]
]: ...
@overload
def scanner(
    *,
    messages: Literal["tool"],
    events: None = ...,
    loader: Loader[ChatMessageTool] | None = ...,
    name: str | None = ...,
) -> Callable[
    [ScannerFactory[P, ChatMessageTool]], ScannerFactory[P, ChatMessageTool]
]: ...


# (G) SINGLE-VALUE events (messages absent) => specific event type
@overload
def scanner(
    *,
    events: Literal["tool"],
    messages: None = ...,
    loader: Loader[ToolEvent] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, ToolEvent]], ScannerFactory[P, ToolEvent]]: ...
@overload
def scanner(
    *,
    events: Literal["model"],
    messages: None = ...,
    loader: Loader[ModelEvent] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, ModelEvent]], ScannerFactory[P, ModelEvent]]: ...
@overload
def scanner(
    *,
    events: Literal["all"],
    messages: None = ...,
    loader: Loader[Event] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, Event]], ScannerFactory[P, Event]]: ...


# (H) Loader-only path (no filters) => arbitrary T from loader instance
@overload
def scanner(
    *,
    name: str | None = ...,
    loader: Loader[T],
    messages: None = ...,
    events: None = ...,
) -> Callable[[ScannerFactory[P, T]], ScannerFactory[P, T]]: ...


def scanner(
    *,
    loader: Loader[T] | None = None,
    messages: MessageType | list[MessageType] | None = None,
    events: EventType | list[EventType] | None = None,
    name: str | None = None,
) -> Callable[[ScannerFactory[P, T]], ScannerFactory[P, T]]:
    if loader is None and messages is None and events is None:
        raise ValueError(
            "scanner(...) requires at least one of: messages=..., events=..., or loader=..."
        )

    messages = normalize_messages_filter(messages) if messages is not None else None
    events = normalize_events_filter(events) if events is not None else None

    def decorate(factory: ScannerFactory[P, T]) -> ScannerFactory[P, T]:
        scanner_name = registry_name(
            factory, name or str(getattr(factory, "__name__", "scanner"))
        )

        @wraps(factory)
        def factory_wrapper(*args: P.args, **kwargs: P.kwargs) -> Scanner[T]:
            scanner_fn = factory(*args, **kwargs)

            if not is_callable_coroutine(scanner_fn):
                raise TypeError(
                    f"'{scanner_name}' is not declared as an async callable."
                )

            scanner_config: ScannerConfig = {"name": scanner_name}
            if messages is not None:
                scanner_config["messages"] = messages
            if events is not None:
                scanner_config["events"] = events
            if loader is not None:
                scanner_config["loader"] = cast(Loader[Any], loader)
            setattr(scanner_fn, "__scanner__", scanner_config)  # type: ignore[attr-defined]

            registry_tag(
                factory,
                scanner_fn,
                RegistryInfo(type="scanner", name=scanner_name),
                *args,
                **kwargs,
            )
            return scanner_fn

        registry_add(
            factory,
            RegistryInfo(type="scanner", name=scanner_name),
        )
        return cast(ScannerFactory[P, T], factory_wrapper)

    return decorate
