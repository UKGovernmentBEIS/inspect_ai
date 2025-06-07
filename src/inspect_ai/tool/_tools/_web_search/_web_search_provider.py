from typing import Awaitable, Callable, TypeAlias

from inspect_ai._util.content import ContentText

SearchProvider: TypeAlias = Callable[
    [str], Awaitable[str | ContentText | list[ContentText] | None]
]
