from dataclasses import dataclass, field
from functools import wraps
from typing import (
    Any,
    Awaitable,
    Callable,
    Literal,
    ParamSpec,
    Protocol,
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

from .result import Result
from .._transcript.types import (
    EventType,
    MessageType,
    Transcript,
    TranscriptContent,
)
from .filter import (
    normalize_events_filter,
    normalize_messages_filter,
)
from .loader import Loader
from .validate import infer_filters_from_type, validate_scanner_signature

# core types
T = TypeVar("T", contravariant=True)
P = ParamSpec("P")

# overloads to enable scanners to take T or list[T]
TMessage = TypeVar("TMessage", ChatMessage, list[ChatMessage])
TEvent = TypeVar("TEvent", Event, list[Event])


class Scanner(Protocol[T]):
    def __call__(self, input: T, /) -> Awaitable[Result | None]: ...


@dataclass
class ScannerConfig:
    name: str
    content: TranscriptContent = field(default_factory=TranscriptContent)
    loader: Loader[Any] | None = field(default=None)


ScannerFactory = Callable[P, Scanner[T]]


# overloads for both messages and events present: scanner takes Transcript
# mypy: disable-error-code="overload-overlap"
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


# overload for direct decoration without parentheses (will infer from types)
# This needs to be last as it's the most general
@overload
def scanner(factory: ScannerFactory[P, T], /) -> ScannerFactory[P, T]: ...


@overload  # type: ignore[overload-overlap]
def scanner(
    *,
    loader: Loader[T] | None = None,
    messages: list[MessageType] | Literal["all"] | None = None,
    events: list[EventType] | Literal["all"] | None = None,
    name: str | None = None,
) -> Callable[[ScannerFactory[P, T]], ScannerFactory[P, T]]: ...


def scanner(
    factory: ScannerFactory[P, T] | None = None,
    /,
    *,
    loader: Loader[T] | None = None,
    messages: list[MessageType] | Literal["all"] | None = None,
    events: list[EventType] | Literal["all"] | None = None,
    name: str | None = None,
) -> ScannerFactory[P, T] | Callable[[ScannerFactory[P, T]], ScannerFactory[P, T]]:
    # Handle direct decoration without parentheses
    if factory is not None:
        # Called as @scanner (without parentheses)
        return scanner()(factory)  # type: ignore[arg-type,return-value]

    # Don't raise error here anymore - we'll check after attempting inference
    messages = normalize_messages_filter(messages) if messages is not None else None
    events = normalize_events_filter(events) if events is not None else None

    def decorate(factory_fn: ScannerFactory[P, T]) -> ScannerFactory[P, T]:
        scanner_name = registry_name(
            factory_fn, name or str(getattr(factory_fn, "__name__", "scanner"))
        )

        @wraps(factory_fn)
        def factory_wrapper(*args: P.args, **kwargs: P.kwargs) -> Scanner[T]:
            scanner_fn = factory_fn(*args, **kwargs)

            if not is_callable_coroutine(scanner_fn):
                raise TypeError(
                    f"'{scanner_name}' is not declared as an async callable."
                )

            # Infer filters from type annotations if not provided
            # Use explicit filters if provided, otherwise try to infer
            inferred_messages = messages
            inferred_events = events

            # Only infer if no loader and no explicit filters
            if loader is None and messages is None and events is None:
                temp_messages, temp_events = infer_filters_from_type(
                    scanner_fn, factory_fn.__globals__
                )
                # Cast to proper types (mypy can't infer the string literals)
                inferred_messages = (
                    cast(list[MessageType] | None, temp_messages)
                    if temp_messages
                    else None
                )
                inferred_events = (
                    cast(list[EventType] | None, temp_events) if temp_events else None
                )
                # If we couldn't infer anything, raise an error
                if inferred_messages is None and inferred_events is None:
                    raise ValueError(
                        f"scanner '{scanner_name}' requires at least one of: "
                        "messages=..., events=..., loader=..., or specific type annotations"
                    )

            # Validate scanner signature matches filters
            # Only validate if we have filters (not just a custom loader)
            if inferred_messages is not None or inferred_events is not None:
                validate_scanner_signature(
                    scanner_fn,
                    inferred_messages,
                    inferred_events,
                    factory_fn.__globals__,
                )

            scanner_config = ScannerConfig(name=scanner_name)
            if inferred_messages is not None:
                scanner_config.content.messages = inferred_messages
            if inferred_events is not None:
                scanner_config.content.events = inferred_events
            if loader is not None:
                scanner_config.loader = cast(Loader[Any], loader)
            setattr(scanner_fn, "__scanner__", scanner_config)  # type: ignore[attr-defined]

            registry_tag(
                factory_fn,
                scanner_fn,
                RegistryInfo(type="scanner", name=scanner_name),
                *args,
                **kwargs,
            )
            return scanner_fn

        registry_add(
            factory_fn,
            RegistryInfo(type="scanner", name=scanner_name),
        )
        return cast(ScannerFactory[P, T], factory_wrapper)

    return decorate
