from itertools import tee
from typing import Iterable, SupportsIndex, overload

from inspect_ai.model._chat_message import ChatMessage, ChatMessageBase
from inspect_ai.util._limit import check_message_limit


class ChatMessageList(list[ChatMessage]):
    """A limited list of ChatMessage items.

    Raises an exception if an operation would exceed the active message limit.
    """

    def __init__(self, iterable: Iterable[ChatMessage]):
        items, length = self._iterable_length(iterable)
        self._check_size(length)
        super().__init__(items)

    def _check_size(self, additional_items: int) -> None:
        check_message_limit(len(self) + additional_items, raise_for_equal=False)

    def append(self, item: ChatMessage) -> None:
        self._check_size(1)
        super().append(item)

    def extend(self, items: Iterable[ChatMessage]) -> None:
        items, length = self._iterable_length(items)
        self._check_size(length)
        super().extend(items)

    def insert(self, index: SupportsIndex, item: ChatMessage) -> None:
        self._check_size(1)
        super().insert(index, item)

    @overload
    def __setitem__(self, index: SupportsIndex, item: ChatMessage) -> None: ...

    @overload
    def __setitem__(self, index: slice, item: Iterable[ChatMessage]) -> None: ...

    def __setitem__(
        self, index: SupportsIndex | slice, item: ChatMessage | Iterable[ChatMessage]
    ) -> None:
        if isinstance(index, slice) and not isinstance(item, ChatMessageBase):
            item, length = self._iterable_length(item)
            size_change = length - len(self[index])
            if size_change > 0:
                self._check_size(size_change)

        super().__setitem__(index, item)  # type: ignore[assignment,index]

    def _iterable_length(
        self, items: Iterable[ChatMessage]
    ) -> tuple[Iterable[ChatMessage], int]:
        items, counter = tee(items)
        length = sum(1 for _ in counter)
        return items, length
