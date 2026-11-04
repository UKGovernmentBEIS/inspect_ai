"""One step builder, for the live dispatcher (`_dispatch.py`) and the log driver (`_replay.py`).

Each driver gathers the facts a step is made from, live from its arguments and context variables, or from a sample's events, and hands them to the same functions here, so a field added to a step is built for both or fails both.
"""

import json
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterator, Sequence
from typing import (
    TYPE_CHECKING,
    Literal,
    NamedTuple,
    Protocol,
    TypeGuard,
    TypeVar,
    overload,
)

import mmh3

from inspect_ai._util.hash import mm3_hash
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sentinel import SentinelStage
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageTool,
    _logged_json_adapter,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

if TYPE_CHECKING:
    from inspect_sentinel import (
        AfterGenerate,
        AfterToolCall,
        BeforeGenerate,
        BeforeToolCall,
        HumanDecision,
        Step,
        Truncation,
    )

T = TypeVar("T")


class MalformedLogError(ValueError):
    """A log replay cannot read without guessing."""


class ListView(Sequence[T]):
    """A read-only view of `items[start:stop]`, for a list that is only appended to.

    A step holds one in place of a copy, so building a step costs nothing in the length of the conversation. Slicing gives a view too; equality is by contents, against any sequence.
    """

    __slots__ = ("_items", "_start", "_stop")

    def __init__(self, items: list[T], stop: int, start: int = 0) -> None:
        self._items = items
        self._start = start
        self._stop = stop

    def __len__(self) -> int:
        return self._stop - self._start

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> "Sequence[T]": ...

    def __getitem__(self, index: int | slice) -> "T | Sequence[T]":
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            if step == 1:
                return ListView(
                    self._items, self._start + max(stop, start), self._start + start
                )
            return [self._items[self._start + i] for i in range(start, stop, step)]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError("ListView index out of range")
        return self._items[self._start + index]

    def __iter__(self) -> Iterator[T]:
        # by index, so a view of a list's end does not walk the list to it
        for index in range(self._start, self._stop):
            yield self._items[index]

    def __reversed__(self) -> Iterator[T]:
        for index in range(self._stop - 1, self._start - 1, -1):
            yield self._items[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Sequence) and not isinstance(other, str | bytes):
            return len(self) == len(other) and all(a == b for a, b in zip(self, other))
        return NotImplemented

    def __repr__(self) -> str:
        return f"ListView({list(self)!r})"


def view(items: list[T]) -> ListView[T]:
    """The list as it stands: later appends are not in the view."""
    return ListView(items, len(items))


_EXCLUDED = {"id", "source", "metadata"}


def content_key(message: ChatMessage) -> str:
    """A hash of what the model is sent of a message: all but its id, source and metadata.

    It is encoded as the log is (`logged_json()`), so None, NaN and the infinities are told apart. Text with lone surrogates, which UTF-8 JSON cannot encode, is hashed from JSON with them escaped. A message that cannot be serialized at all (such as a numpy array in its tool arguments) is keyed by identity, so it matches only itself: a rebuilt copy of it is new, and an edit made to it in place is not seen.
    """
    try:
        return mmh3.hash_bytes(
            _logged_json_adapter.dump_json(message, exclude=_EXCLUDED)
        ).hex()
    except ValueError:
        pass
    # any value can fail to serialize, in any way; keyed by identity, a
    # message stays alive while its key can match, since the fold holds it
    try:
        logged = _logged_json_adapter.dump_python(
            message, mode="json", exclude=_EXCLUDED
        )
        return mm3_hash(json.dumps(logged))
    except Exception:
        return f"object:{id(message)}"


class FoldInput(Protocol):
    """One agent turn's input, as the fold reads it."""

    def __len__(self) -> int: ...

    def message(self, position: int) -> ChatMessage: ...

    def new_positions(self, previous: "FoldInput | None") -> Iterator[int]:
        """The positions of this input the fold counts as new, aligned against `previous` (see `_Sent`)."""
        ...


class KeyedInput:
    """A live input: every message's key is computed on every send, so an object changed in place since it was last sent counts as new."""

    def __init__(self, messages: Sequence[ChatMessage]) -> None:
        self._messages = messages
        self._keys = [content_key(message) for message in messages]

    def __len__(self) -> int:
        return len(self._keys)

    def message(self, position: int) -> ChatMessage:
        return self._messages[position]

    def new_positions(self, previous: FoldInput | None) -> Iterator[int]:
        if previous is None:
            yield from range(len(self))
            return
        assert isinstance(previous, KeyedInput)
        keys, before = self._keys, previous._keys
        pointer = 0
        # where each key sits in the previous input at or after the pointer,
        # built the first time the walk leaves the previous input's order
        later: dict[str, list[int]] | None = None
        for position, key in enumerate(keys):
            if pointer < len(before) and before[pointer] == key:
                pointer += 1
                continue
            if later is None:
                later = {}
                for at in range(pointer, len(before)):
                    later.setdefault(before[at], []).append(at)
            found = later.get(key, [])
            at = bisect_left(found, pointer)
            if at < len(found):
                pointer = found[at] + 1
            else:
                yield position


class _Sent:
    """What one conversation's agent turns have sent: every message once, where it was first sent.

    A message is new unless the previous input had the same content (`content_key()`) at the position the alignment has reached or later. Each input is aligned against the previous input only: a pointer walks the previous input from its start, a message the same as the one at the pointer or at a later position is matched and moves the pointer past it, and anything else is new. So a message rebuilt with a fresh id where it was is matched; a message edited, reordered behind a later one, or dropped by one call and restored by a later one is new again; and two equal messages sent at different turns are two messages. Ids play no part, so the fold over a log's inputs is the fold live.
    """

    def __init__(self) -> None:
        # every message sent, in the order sent, as the logged snapshots of
        # the inputs live (`_snapshot_messages`); only appended to
        self.messages: list[ChatMessage] = []
        self._previous: FoldInput | None = None

    def record(self, input: Sequence[ChatMessage]) -> None:
        self.record_input(KeyedInput(input))

    def record_input(self, input: FoldInput) -> None:
        for position in input.new_positions(self._previous):
            self.messages.append(input.message(position))
        self._previous = input


class ConversationRecord:
    """What a step reads of its conversation: what it has sent (`history`) and the `human()` decisions published so far.

    Each is a list only ever appended to, and a step holds a view of it cut at its length when the step is built.
    """

    def __init__(self) -> None:
        self.sent = _Sent()
        self._decisions: list["HumanDecision"] = []

    def publish(self, kept: Sequence["HumanDecision"]) -> None:
        """Add a settled step's `human()` decisions, once its sentinel span has ended."""
        self._decisions.extend(kept)

    def history(self) -> ListView[ChatMessage]:
        return view(self.sent.messages)

    def human_decisions(self) -> ListView["HumanDecision"]:
        """The `human()` decisions published so far: a step's own, or a parallel step's still running, are not among them."""
        return view(self._decisions)


class Producer(NamedTuple):
    """What a tool step reads of the model call that produced its call."""

    input: Sequence[ChatMessage]
    tools: Sequence[ToolInfo]
    tool_choice: ToolChoice


def producer_of(event: ModelEvent | None) -> Producer | None:
    return (
        Producer(view(event.input), view(event.tools), event.tool_choice)
        if event is not None
        else None
    )


def producing_message_id(event: Event) -> str | None:
    """The id of the assistant message a model call produced for its caller, or None for an event that produced none: a monitor's call, one still pending, or one with no choices."""
    if (
        isinstance(event, ModelEvent)
        and event.role != "monitor"
        and not event.pending
        and event.output.choices
    ):
        return event.output.choices[0].message.id
    return None


def produced_by(message_id: str) -> Callable[[Event], TypeGuard[ModelEvent]]:
    """Whether an event is the model call that produced the assistant message `message_id`."""

    def produced(event: Event) -> TypeGuard[ModelEvent]:
        return (
            isinstance(event, ModelEvent) and producing_message_id(event) == message_id
        )

    return produced


def step_stage(step: "Step") -> SentinelStage:
    from inspect_sentinel import AfterGenerate, BeforeGenerate, BeforeToolCall

    if isinstance(step, BeforeGenerate):
        return "model_input"
    elif isinstance(step, AfterGenerate):
        return "model_output"
    elif isinstance(step, BeforeToolCall):
        return "tool_call"
    return "tool_result"


def before_generate(
    *,
    model: str,
    conversation: str,
    input: Sequence[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
    agent_messages: Sequence[ChatMessage] | None,
    record: ConversationRecord,
) -> "BeforeGenerate":
    from inspect_sentinel import BeforeGenerate

    return BeforeGenerate(
        model=model,
        conversation=conversation,
        input=input,
        agent_messages=agent_messages,
        history=record.history(),
        human_decisions=record.human_decisions(),
        tools=tools,
        tool_choice=tool_choice,
        config=config,
    )


def after_generate(
    *,
    model: str,
    conversation: str,
    input: Sequence[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
    output: ModelOutput,
    agent_messages: Sequence[ChatMessage] | None,
    record: ConversationRecord,
) -> "AfterGenerate":
    from inspect_sentinel import AfterGenerate

    return AfterGenerate(
        model=model,
        conversation=conversation,
        input=input,
        agent_messages=agent_messages,
        history=record.history(),
        human_decisions=record.human_decisions(),
        tools=tools,
        tool_choice=tool_choice,
        config=config,
        output=output,
    )


def before_tool_call(
    *,
    conversation: str,
    message: str,
    message_id: str,
    call: ToolCall,
    view: ToolCallView,
    producer: Producer | None,
    agent_messages: Sequence[ChatMessage] | None,
    record: ConversationRecord,
) -> "BeforeToolCall":
    """The step before a tool call runs.

    Args:
        conversation: The conversation of the call's producing model call.
        message: The text of the assistant message that made the call.
        message_id: The id of that message.
        call: The call as it will execute.
        view: The call's view.
        producer: The model call that produced the call, if one did.
        agent_messages: The running agent's messages, or None when they are not known.
        record: The conversation's record.
    """
    from inspect_sentinel import BeforeToolCall

    return BeforeToolCall(
        conversation=conversation,
        message=message,
        message_id=message_id,
        call=call,
        view=view,
        input=producer.input if producer is not None else None,
        agent_messages=agent_messages,
        history=record.history(),
        human_decisions=record.human_decisions(),
        tools=producer.tools if producer is not None else None,
        tool_choice=producer.tool_choice if producer is not None else None,
    )


def after_tool_call(
    *,
    conversation: str,
    message: str,
    message_id: str,
    call: ToolCall,
    view: ToolCallView,
    result: ChatMessageTool,
    output: ToolResult | None,
    truncated: "Truncation | Literal[False] | None",
    producer: Producer | None,
    agent_messages: Sequence[ChatMessage] | None,
    record: ConversationRecord,
) -> "AfterToolCall":
    """The step after a tool call ran; the arguments are those of `before_tool_call`, and the call's result.

    Args:
        conversation: The conversation of the call's producing model call.
        message: The text of the assistant message that made the call.
        message_id: The id of that message.
        call: The call as it ran.
        view: The call's view.
        result: The result as the model will see it.
        output: The tool's untruncated output, or None when it is not known (replay).
        truncated: The cut made to the output, False for none, None when not known.
        producer: The model call that produced the call, if one did.
        agent_messages: The running agent's messages, or None when they are not known.
        record: The conversation's record.
    """
    from inspect_sentinel import AfterToolCall

    return AfterToolCall(
        conversation=conversation,
        message=message,
        message_id=message_id,
        call=call,
        result=result,
        output=output,
        view=view,
        input=producer.input if producer is not None else None,
        agent_messages=agent_messages,
        history=record.history(),
        human_decisions=record.human_decisions(),
        tools=producer.tools if producer is not None else None,
        tool_choice=producer.tool_choice if producer is not None else None,
        truncated=truncated,
    )


class PoolView(Sequence[ChatMessage]):
    """A model call's input as a read-only view over a log's message pool: the rows its `input_refs` name, read only when asked for."""

    __slots__ = ("_pool", "_refs", "_starts", "_length")

    def __init__(
        self, pool: Sequence[ChatMessage], refs: Sequence[tuple[int, int]]
    ) -> None:
        self._pool = pool
        self._refs = refs
        # the input position each range begins at
        self._starts: list[int] = []
        length = 0
        for start, end in refs:
            if not 0 <= start <= end <= len(pool):
                raise MalformedLogError(
                    f"A model input names pool rows [{start}, {end}), "
                    f"outside the pool of {len(pool)} messages."
                )
            self._starts.append(length)
            length += end - start
        self._length = length

    @property
    def refs(self) -> Sequence[tuple[int, int]]:
        return self._refs

    @property
    def starts(self) -> Sequence[int]:
        """The input position each range begins at."""
        return self._starts

    def row(self, position: int) -> int:
        """The pool row at an input position."""
        at = bisect_right(self._starts, position) - 1
        return self._refs[at][0] + position - self._starts[at]

    def __len__(self) -> int:
        return self._length

    @overload
    def __getitem__(self, index: int) -> ChatMessage: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[ChatMessage]: ...

    def __getitem__(self, index: int | slice) -> ChatMessage | Sequence[ChatMessage]:
        if isinstance(index, slice):
            start, stop, step = index.indices(self._length)
            if step != 1:
                return [self[i] for i in range(start, stop, step)]
            refs: list[tuple[int, int]] = []
            for (first, last), at in zip(self._refs, self._starts):
                low = max(start - at, 0)
                high = min(stop - at, last - first)
                if low < high:
                    refs.append((first + low, first + high))
            return PoolView(self._pool, refs)
        if index < 0:
            index += self._length
        if not 0 <= index < self._length:
            raise IndexError("PoolView index out of range")
        return self._pool[self.row(index)]

    def __iter__(self) -> Iterator[ChatMessage]:
        for start, end in self._refs:
            for row in range(start, end):
                yield self._pool[row]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Sequence) and not isinstance(other, str | bytes):
            return len(self) == len(other) and all(a == b for a, b in zip(self, other))
        return NotImplemented

    def __repr__(self) -> str:
        return f"PoolView({list(self)!r})"
