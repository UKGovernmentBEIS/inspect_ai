import inspect
from types import UnionType
from typing import (
    Any,
    Callable,
    Literal,
    Type,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.event._error import ErrorEvent
from inspect_ai.event._event import (
    Event,
)
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._input import InputEvent
from inspect_ai.event._logger import LoggerEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.event._sample_limit import SampleLimitEvent
from inspect_ai.event._sandbox import SandboxEvent
from inspect_ai.event._score import ScoreEvent
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.event._state import StateEvent
from inspect_ai.event._store import StoreEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)

from .._transcript.types import EventType, MessageType, Transcript

# Reverse mappings for inferring filters from types
TYPE_TO_MESSAGE_FILTER: dict[type[Any], str] = {
    ChatMessageSystem: "system",
    ChatMessageUser: "user",
    ChatMessageAssistant: "assistant",
    ChatMessageTool: "tool",
}

TYPE_TO_EVENT_FILTER: dict[type[Any], str] = {
    ModelEvent: "model",
    ToolEvent: "tool",
    SampleInitEvent: "sample_init",
    SampleLimitEvent: "sample_limit",
    SandboxEvent: "sandbox",
    StateEvent: "state",
    StoreEvent: "store",
    ApprovalEvent: "approval",
    InputEvent: "input",
    ScoreEvent: "score",
    ErrorEvent: "error",
    LoggerEvent: "logger",
    InfoEvent: "info",
    SpanBeginEvent: "span_begin",
    SpanEndEvent: "span_end",
}


def infer_filters_from_type(
    scanner_fn: Callable[..., Any],
    factory_globals: dict[str, Any],
) -> tuple[list[str] | None, list[str] | None]:
    """
    Infer message and event filters from scanner function type annotations.

    Args:
        scanner_fn: The scanner function to analyze
        factory_globals: Global namespace for type resolution

    Returns:
        Tuple of (message_filters, event_filters) or (None, None) if can't infer
    """
    # Get type hints
    try:
        hints = get_type_hints(
            scanner_fn, globalns=factory_globals, localns=factory_globals
        )
    except Exception:
        return None, None

    # Get the input parameter type
    param_names = list(inspect.signature(scanner_fn).parameters.keys())
    if not param_names:
        return None, None

    input_param = param_names[0]
    if input_param not in hints:
        return None, None

    input_type = hints[input_param]

    # First check if it's ChatMessage, Event, or Transcript (even if they're unions)
    # We don't want to infer for these "base" types
    if input_type == ChatMessage or input_type == Event or input_type == Transcript:
        return None, None

    # Extract the actual type (unwrap list if needed)
    if get_origin(input_type) is list:
        args = get_args(input_type)
        if args:
            input_type = args[0]
            # Check again for base types after unwrapping
            if (
                input_type == ChatMessage
                or input_type == Event
                or input_type == Transcript
            ):
                return None, None
        else:
            return None, None

    # Check if it's a specific message type or union
    message_filters = []
    event_filters = []

    # Handle Union types
    if get_origin(input_type) in (Union, UnionType):
        for arg in get_args(input_type):
            if arg in TYPE_TO_MESSAGE_FILTER:
                message_filters.append(TYPE_TO_MESSAGE_FILTER[arg])
            elif arg in TYPE_TO_EVENT_FILTER:
                event_filters.append(TYPE_TO_EVENT_FILTER[arg])
    # Handle single specific types
    elif input_type in TYPE_TO_MESSAGE_FILTER:
        message_filters.append(TYPE_TO_MESSAGE_FILTER[input_type])
    elif input_type in TYPE_TO_EVENT_FILTER:
        event_filters.append(TYPE_TO_EVENT_FILTER[input_type])
    else:
        # Also check if it's a subclass of Transcript (the only class we can check)
        try:
            if inspect.isclass(input_type) and issubclass(input_type, Transcript):
                # It's Transcript, we don't have a specific filter for it
                return None, None
        except TypeError:
            # Not a class type
            pass
        return None, None

    # If we have both message and event filters, can't use inference
    # (should use Transcript instead)
    if message_filters and event_filters:
        return None, None

    # Return inferred filters
    # Type: ignore because mypy can't understand that the lists contain the right string literals
    return (
        message_filters if message_filters else None,  # type: ignore[return-value]
        event_filters if event_filters else None,  # type: ignore[return-value]
    )


def validate_scanner_signature(
    scanner_fn: Callable[..., Any],
    messages: list[MessageType] | Literal["all"] | None,
    events: list[EventType] | Literal["all"] | None,
    factory_globals: dict[str, Any],
) -> None:
    """
    Validate that scanner function signature matches its declared filters.

    Args:
        scanner_fn: The scanner function to validate
        messages: Message filter from decorator
        events: Event filter from decorator
        factory_globals: Global namespace from factory function for type resolution

    Raises:
        TypeError: If scanner signature doesn't match filters
    """
    # Get type hints with proper resolution
    try:
        # Also include localns for better resolution
        hints = get_type_hints(
            scanner_fn, globalns=factory_globals, localns=factory_globals
        )
    except Exception:
        # If we can't get type hints, we can't validate - let it pass
        return

    # Get the input parameter type - scanner takes positional-only 'input' param
    # Check for both 'input' and first positional parameter
    param_names = list(inspect.signature(scanner_fn).parameters.keys())
    if not param_names:
        return

    # The first parameter should be the input
    input_param = param_names[0]
    if input_param not in hints:
        # No type annotation - can't validate
        return

    input_type = hints[input_param]

    # Check what the scanner should accept based on filters
    if messages is not None and events is not None:
        # Both filters present - should accept Transcript
        _validate_transcript_type(input_type, messages, events)
    elif messages is not None:
        # Only message filter - validate message types
        _validate_message_type(input_type, messages)
    elif events is not None:
        # Only event filter - validate event types
        _validate_event_type(input_type, events)


def _validate_transcript_type(
    scanner_type: Any,
    messages: list[MessageType] | Literal["all"],
    events: list[EventType] | Literal["all"],
) -> None:
    """Validate that scanner accepts Transcript when both filters present."""
    if not _is_compatible_with_type(scanner_type, Transcript):
        raise TypeError(
            f"Scanner with both messages and events filters must accept Transcript, "
            f"but scanner accepts {scanner_type}"
        )


def _validate_message_type(
    scanner_type: Any,
    message_filter: list[MessageType] | Literal["all"],
) -> None:
    """
    Validate scanner type against message filter.

    Scanner must be able to handle ALL message types in the filter.
    Scanner can accept Transcript (which will contain filtered messages).
    """
    # Get the core type (unwrap list if needed)
    is_list, core_type = _unwrap_list_type(scanner_type)

    # Accept Transcript as a valid input type (messages will be filtered)
    if _is_compatible_with_type(core_type, Transcript):
        return

    # If it's the base ChatMessage type, it's always valid
    if _is_compatible_with_type(core_type, ChatMessage):
        return

    # For "all" filter, scanner must accept base ChatMessage type
    if message_filter == "all":
        raise TypeError(
            f"Scanner with messages='all' must accept ChatMessage or list[ChatMessage], "
            f"but scanner accepts {scanner_type}"
        )

    # Get the required message types from filter
    required_types = _get_message_types_from_filter(message_filter)

    # Check if scanner type can handle all required types
    if not _can_handle_all_types(core_type, required_types, ChatMessage):
        filter_names = ", ".join(sorted(message_filter))
        type_names = ", ".join(t.__name__ for t in required_types)
        # Get actual scanner type name for better error message
        scanner_type_name = getattr(scanner_type, "__name__", str(scanner_type))
        raise TypeError(
            f"Scanner with messages=[{filter_names}] must be able to handle all types: {type_names}, "
            f"but scanner accepts {scanner_type_name}"
        )


def _validate_event_type(
    scanner_type: Any,
    event_filter: list[EventType] | Literal["all"],
) -> None:
    """
    Validate scanner type against event filter.

    Scanner must be able to handle ALL event types in the filter.
    Scanner can accept Transcript (which will contain filtered events).
    """
    # Get the core type (unwrap list if needed)
    is_list, core_type = _unwrap_list_type(scanner_type)

    # Accept Transcript as a valid input type (events will be filtered)
    if _is_compatible_with_type(core_type, Transcript):
        return

    # If it's the base Event type, it's always valid
    if _is_compatible_with_type(core_type, Event):
        return

    # For "all" filter, scanner must accept base Event type
    if event_filter == "all":
        raise TypeError(
            f"Scanner with events='all' must accept Event or list[Event], "
            f"but scanner accepts {scanner_type}"
        )

    # Get the required event types from filter
    required_types = _get_event_types_from_filter(event_filter)

    # Check if scanner type can handle all required types
    if not _can_handle_all_types(core_type, required_types, Event):
        filter_names = ", ".join(sorted(event_filter))
        type_names = ", ".join(t.__name__ for t in required_types)
        raise TypeError(
            f"Scanner with events=[{filter_names}] must be able to handle all types: {type_names}, "
            f"but scanner accepts {scanner_type}"
        )


def _get_message_types_from_filter(
    message_filter: list[MessageType],
) -> set[Type[ChatMessage]]:
    """Map message filter strings to concrete ChatMessage types."""
    type_map: dict[MessageType, Type[ChatMessage]] = {
        "system": ChatMessageSystem,
        "user": ChatMessageUser,
        "assistant": ChatMessageAssistant,
        "tool": ChatMessageTool,
    }
    return {type_map[f] for f in message_filter}


def _get_event_types_from_filter(
    event_filter: list[EventType],
) -> set[Type[Event]]:
    """Map event filter strings to concrete Event types."""
    type_map: dict[str, Type[Event]] = {
        "model": ModelEvent,
        "tool": ToolEvent,
        "sample_init": SampleInitEvent,
        "sample_limit": SampleLimitEvent,
        "sandbox": SandboxEvent,
        "state": StateEvent,
        "store": StoreEvent,
        "approval": ApprovalEvent,
        "input": InputEvent,
        "score": ScoreEvent,
        "error": ErrorEvent,
        "logger": LoggerEvent,
        "info": InfoEvent,
        "span_begin": SpanBeginEvent,
        "span_end": SpanEndEvent,
    }
    return {type_map[f] for f in event_filter}


def _unwrap_list_type(type_hint: Any) -> tuple[bool, Any]:
    """
    Unwrap a list type to get the element type.

    Returns:
        (is_list, element_type)
    """
    origin = get_origin(type_hint)
    if origin is list:
        args = get_args(type_hint)
        if args:
            return True, args[0]
        # Unparameterized list
        return True, Any
    return False, type_hint


def _can_handle_all_types(
    scanner_type: Any,
    required_types: set[Type[Any]],
    base_type: Any,
) -> bool:
    """
    Check if scanner_type can handle all required_types.

    Valid patterns:
    - Base type (ChatMessage/Event)
    - Union containing ALL required types
    """
    # Check if it's the base type
    if _is_compatible_with_type(scanner_type, base_type):
        return True

    # Get union members if it's a Union
    union_members = _get_union_members(scanner_type)
    if union_members:
        # Check if all required types are in the union
        # Need to check each member for compatibility
        for req_type in required_types:
            if not any(
                _is_compatible_with_type(member, req_type) for member in union_members
            ):
                return False
        return True

    # Single type - check if it's trying to handle multiple required types
    if len(required_types) > 1:
        # Single type can't handle multiple required types unless it's a base type
        # (but we already checked that above)
        return False

    # Single required type - check direct compatibility
    required_type = next(iter(required_types))
    return _is_compatible_with_type(scanner_type, required_type)


def _get_union_members(type_hint: Any) -> set[Type[Any]] | None:
    """Get the member types of a Union, or None if not a Union."""
    origin = get_origin(type_hint)

    # Handle Union from typing module
    if origin is Union:
        return set(get_args(type_hint))

    # Handle Python 3.10+ union syntax (X | Y)
    if isinstance(type_hint, UnionType):
        return set(get_args(type_hint))

    return None


def _is_compatible_with_type(scanner_type: Any, target_type: Any) -> bool:
    """
    Check if scanner_type is compatible with target_type.

    Compatible means:
    - Exact match
    - scanner_type is a subclass of target_type
    - scanner_type is the target_type
    """
    try:
        # Handle None types
        if scanner_type is None or target_type is None:
            return False

        # Direct equality
        if scanner_type == target_type:
            return True

        # Try to check subclass relationship
        # This works for normal classes
        if inspect.isclass(scanner_type) and inspect.isclass(target_type):
            return issubclass(scanner_type, target_type)

        # For generic types, check origin
        scanner_origin = get_origin(scanner_type)
        target_origin = get_origin(target_type)

        if scanner_origin and target_origin:
            return bool(scanner_origin == target_origin)

        return False
    except (TypeError, AttributeError):
        # If we can't determine compatibility, be conservative
        return False
