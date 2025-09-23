from dataclasses import dataclass, field
from typing import Any, Literal

import ijson  # type: ignore

# Cache for common string constants to avoid repeated string creation
ATTACHMENT_PREFIX = "attachment://"
ATTACHMENT_PREFIX_LEN = len(ATTACHMENT_PREFIX)
MESSAGES_PREFIX = "messages"
EVENTS_PREFIX = "events"
ATTACHMENTS_PREFIX = "attachments."


@dataclass
class ProcessorState:
    """Mutable state for processing array items (messages/events)."""

    builder: ijson.ObjectBuilder | None = None
    attachments: set[str] = field(default_factory=set)
    skip_current: bool = False

    def reset(self) -> None:
        """Reset state for reuse."""
        self.builder = None
        self.attachments.clear()
        self.skip_current = False


def _start_item(state: ProcessorState, event: str, value: Any) -> None:
    """Initialize a new item and start building."""
    state.builder = ijson.ObjectBuilder()
    state.builder.event(event, value)
    state.attachments.clear()
    state.skip_current = False


def _finish_item(
    state: ProcessorState,
    event: str,
    value: Any,
) -> Any | None:
    """Finish building current item and return raw dict."""
    if not state.builder or state.skip_current:
        state.builder = None
        return None

    try:
        state.builder.event(event, value)
        item_data = state.builder.value
        state.builder = None
        return item_data
    except (ValueError, TypeError, KeyError):
        state.builder = None
        return None


def _feed_event(state: ProcessorState, event: str, value: Any) -> None:
    """Feed an event to the current builder if not skipping."""
    if state.builder and not state.skip_current:
        state.builder.event(event, value)


def _track_attachment(state: ProcessorState, value: str) -> None:
    """Track attachment reference if value is an attachment URL."""
    if (
        isinstance(value, str)
        and value.startswith(ATTACHMENT_PREFIX)
        and len(value) >= 45
    ):
        attachment_id = value[ATTACHMENT_PREFIX_LEN : ATTACHMENT_PREFIX_LEN + 32]
        state.attachments.add(attachment_id)


def _should_skip(
    filter_field_value: str, filter_list: None | Literal["all"] | list[str]
) -> bool:
    """Determine if current item should be skipped based on filter."""
    if filter_list is None:
        return True
    if filter_list == "all":
        return False
    return filter_field_value not in filter_list


def _skip_and_reset(state: ProcessorState) -> None:
    """Mark current item to be skipped and reset state."""
    state.skip_current = True
    state.builder = None
    state.attachments.clear()


@dataclass
class ArrayItemResult:
    """Result of processing an array item event."""

    parsed_item: Any | None = None
    attachment_refs: set[str] = field(default_factory=set)


def _process_array_item_event(
    *,
    state: ProcessorState,
    prefix: str,
    event: str,
    value: Any,
    array_item_prefix: str,
    filter_field: str,
    filter_list: None | Literal["all"] | list[str],
) -> ArrayItemResult:
    """Process a single array item event using mutable state."""
    if prefix == array_item_prefix and event == "start_map":
        _start_item(state, event, value)
        return ArrayItemResult()

    elif prefix == array_item_prefix and event == "end_map":
        parsed_item = _finish_item(state, event, value)
        result = ArrayItemResult(
            parsed_item=parsed_item,
            attachment_refs=(
                state.attachments.copy() if parsed_item is not None else set()
            ),
        )
        return result

    elif state.builder is not None:
        # Check for filter field to make filtering decision
        filter_prefix = f"{array_item_prefix}.{filter_field}"
        if prefix == filter_prefix and event == "string":
            if _should_skip(str(value), filter_list):
                _skip_and_reset(state)
                return ArrayItemResult()

        # Only build if we're not skipping this item
        if not state.skip_current:
            _feed_event(state, event, value)
            # Track attachments in string values
            if event == "string":
                _track_attachment(state, str(value))
            return ArrayItemResult()

    return ArrayItemResult()


# Stream Processing Pipeline Functions


@dataclass(frozen=True)
class ListProcessingConfig:
    """Configuration for stream processing."""

    array_item_prefix: str
    filter_field: str
    filter_list: None | Literal["all"] | list[str]


@dataclass(frozen=True)
class ProcessingResult:
    """Final result of processing a stream."""

    items: tuple[Any, ...]
    attachment_refs: frozenset[str]


@dataclass
class ParseState:
    """Complete parsing state with all accumulators.

    Uses mutable state for better performance, eliminating expensive object copying.
    """

    transcript_id: str = ""
    messages_processor: ProcessorState = field(default_factory=ProcessorState)
    events_processor: ProcessorState = field(default_factory=ProcessorState)
    messages: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    attachment_refs: set[str] = field(default_factory=set)
    attachments: dict[str, str] = field(default_factory=dict)


def reduce_parse_event(
    state: ParseState,
    prefix: str,
    event: str,
    value: Any,
    messages_config: ListProcessingConfig | None = None,
    events_config: ListProcessingConfig | None = None,
) -> None:
    """Mutate state by applying an action."""
    # Inline target detection logic directly
    if prefix == "id" and event == "string":
        state.transcript_id = str(value)
        return

    elif prefix.startswith("messages.item"):
        if messages_config is None:
            return
        result = _process_array_item_event(
            state=state.messages_processor,
            prefix=prefix,
            event=event,
            value=value,
            array_item_prefix=messages_config.array_item_prefix,
            filter_field=messages_config.filter_field,
            filter_list=messages_config.filter_list,
        )

        if result.parsed_item is not None:
            state.messages.append(result.parsed_item)
            state.attachment_refs.update(result.attachment_refs)
        return

    elif prefix.startswith("events.item"):
        if events_config is None:
            return
        result = _process_array_item_event(
            state=state.events_processor,
            prefix=prefix,
            event=event,
            value=value,
            array_item_prefix=events_config.array_item_prefix,
            filter_field=events_config.filter_field,
            filter_list=events_config.filter_list,
        )

        if result.parsed_item is not None:
            state.events.append(result.parsed_item)
            state.attachment_refs.update(result.attachment_refs)
        return

    elif prefix.startswith(ATTACHMENTS_PREFIX):
        # Handle attachment values
        attachment_id = prefix.split(".")[1]
        if attachment_id in state.attachment_refs and event == "string":
            state.attachments[attachment_id] = str(value)
        return

    elif prefix == MESSAGES_PREFIX or prefix == EVENTS_PREFIX:
        # Ignore the top-level array containers themselves
        return

    else:
        # Everything else is ignored (metadata is handled by database)
        return
