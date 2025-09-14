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
from inspect_ai.log._transcript import Event
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.scanner._result import Result
from inspect_ai.scanner._transcript import Transcript

from ._filter import (
    EventType,
    MessageType,
    normalize_events_filter,
    normalize_messages_filter,
)
from ._loader import Loader

# core types
T = TypeVar("T", contravariant=True)
P = ParamSpec("P")

# overloads to enable scanners to take T or list[T]
TMessage = TypeVar("TMessage", ChatMessage, list[ChatMessage])
TEvent = TypeVar("TEvent", Event, list[Event])


class Scanner(Protocol[T]):
    def __call__(self, input: T, /) -> Awaitable[Result | None]: ...


class ScannerConfig(TypedDict, total=False):
    name: Required[str]
    messages: list[MessageType] | Literal["all"]
    events: list[EventType] | Literal["all"]
    loader: Loader[Any]


ScannerFactory = Callable[P, Scanner[T]]


# overloads for both messages and events present: scanner takes Transcript
@overload
def scanner(
    *,
    messages: Literal["all"],
    events: list[EventType],
    loader: Loader[Transcript] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, Transcript]], ScannerFactory[P, Transcript]]: ...
@overload
def scanner(
    *,
    messages: list[MessageType],
    events: Literal["all"],
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
    messages: Literal["all"],
    events: Literal["all"],
    loader: Loader[Transcript] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, Transcript]], ScannerFactory[P, Transcript]]: ...


# overloads for type lists: scanner can take T or list[T]
@overload
def scanner(
    *,
    messages: list[MessageType],
    events: None = ...,
    loader: Loader[list[ChatMessage]] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, Any]], ScannerFactory[P, TMessage]]: ...
@overload
def scanner(
    *,
    events: list[EventType],
    messages: None = ...,
    loader: Loader[list[Event]] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, Any]], ScannerFactory[P, TEvent]]: ...


# overloads for "all": scanner can take T or list[T]
@overload
def scanner(
    *,
    messages: Literal["all"],
    events: None = ...,
    loader: Loader[ChatMessage] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, TMessage]], ScannerFactory[P, TMessage]]: ...
@overload
def scanner(
    *,
    events: Literal["all"],
    messages: None = ...,
    loader: Loader[Event] | None = ...,
    name: str | None = ...,
) -> Callable[[ScannerFactory[P, TEvent]], ScannerFactory[P, TEvent]]: ...


# overload for custom loader (no filters): scanner can take arbitrary T from loader instance
@overload
def scanner(
    *,
    name: str | None = ...,
    loader: Loader[T],
    messages: None = ...,
    events: None = ...,
) -> Callable[[ScannerFactory[P, T]], ScannerFactory[P, T]]: ...


# NOTE: @scanner can decorate the more liberal ScannerFactory[P, Any] type so
# that users can write scanners with narrowed types, e.g.
#
# @scanner(messages=["assistant"])
# def instruction_auditor() -> Scanner[ChatMessageAssistant]:
#     async def scan(message: ChatMessageAssistant) -> Result:
#         return Result(value=10)
#
#     return scan
#
# Getting the overloads/type system to be down with this isn't feasible,
# but we don't want the limits of the type system to force users to write
# scan(message: ChatMessage) then do their own narrowing. Here we let
# them do the potentially incompatible (with the filter) thing but we
# will additionally validate at runtime that the input type matches
# the filter (including e.g. checking that ["system", "user"] targets
# either ChatMessage or ChatMessageSystem | ChatMessageUser.


def scanner(
    *,
    loader: Loader[T] | None = None,
    messages: list[MessageType] | Literal["all"] | None = None,
    events: list[EventType] | Literal["all"] | None = None,
    name: str | None = None,
) -> Callable[[ScannerFactory[P, Any]], ScannerFactory[P, T]]:
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
