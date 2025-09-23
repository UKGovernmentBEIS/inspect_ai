from dataclasses import dataclass, field
from typing import Any, Literal

import ijson  # type: ignore

# Cache for common string constants to avoid repeated string creation
ATTACHMENT_PREFIX = "attachment://"
ATTACHMENT_PREFIX_LEN = len(ATTACHMENT_PREFIX)
ATTACHMENTS_PREFIX = "attachments."
ATTACHMENTS_PREFIX_LEN = len(ATTACHMENTS_PREFIX)


@dataclass(slots=True)
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


def _process_array_item_event(
    *,
    state: ProcessorState,
    prefix: str,
    event: str,
    value: Any,
    config: "ListProcessingConfig",
) -> tuple[Any, set[str]] | None:
    """Process a single array item event using mutable state.

    Returns a tuple of (parsed_item, attachment_refs) only when an item finishes
    (on end_map). Returns None for all other events to avoid per-event allocations.
    """
    if prefix == config.array_item_prefix and event == "start_map":
        _start_item(state, event, value)
        return None

    elif prefix == config.array_item_prefix and event == "end_map":
        parsed_item = _finish_item(state, event, value)
        if parsed_item is not None:
            # Copy attachments to decouple from mutable state
            return parsed_item, state.attachments.copy()
        return None

    elif state.builder is not None:
        # Check for filter field to make filtering decision
        if prefix == config.filter_prefix and event == "string":
            if _should_skip(value, config.filter_list):
                _skip_and_reset(state)
                return None

        # Only build if we're not skipping this item
        if not state.skip_current:
            _feed_event(state, event, value)
            # Track attachments in string values
            if event == "string":
                _track_attachment(state, str(value))
            return None

    return None


# Stream Processing Pipeline Functions


@dataclass(frozen=True, slots=True)
class ListProcessingConfig:
    """Configuration for stream processing."""

    array_item_prefix: str
    filter_field: str
    filter_list: None | Literal["all"] | list[str]
    # Precomputed filter prefix to avoid repeated string concatenation
    filter_prefix: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "filter_prefix", f"{self.array_item_prefix}.{self.filter_field}"
        )


@dataclass(slots=True)
class ParseState:
    """Complete parsing state with all accumulators.

    Uses mutable state for better performance, eliminating expensive object copying.
    """

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
    if prefix.startswith("messages.item"):
        if messages_config is None:
            return
        result = _process_array_item_event(
            state=state.messages_processor,
            prefix=prefix,
            event=event,
            value=value,
            config=messages_config,
        )
        if result is not None:
            parsed_item, attachment_refs = result
            state.messages.append(parsed_item)
            state.attachment_refs.update(attachment_refs)
        return

    elif prefix.startswith("events.item"):
        if events_config is None:
            return
        result = _process_array_item_event(
            state=state.events_processor,
            prefix=prefix,
            event=event,
            value=value,
            config=events_config,
        )
        if result is not None:
            parsed_item, attachment_refs = result
            state.events.append(parsed_item)
            state.attachment_refs.update(attachment_refs)
        return

    elif prefix.startswith(ATTACHMENTS_PREFIX):
        if event == "string":
            # Handle attachment values
            # Extract the id after "attachments." and before the next dot (if any)
            end = prefix.find(".", ATTACHMENTS_PREFIX_LEN)
            attachment_id = (
                prefix[ATTACHMENTS_PREFIX_LEN:]
                if end == -1
                else prefix[ATTACHMENTS_PREFIX_LEN:end]
            )
            if attachment_id in state.attachment_refs:
                # value is str for "string" event
                state.attachments[attachment_id] = value
        return

    else:
        # Ignore the top-level array containers themselves (messages and events)
        # as well as all other top level fields
        return
