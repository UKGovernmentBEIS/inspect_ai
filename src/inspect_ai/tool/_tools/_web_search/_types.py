from typing import Protocol


class SearchProvider(Protocol):
    async def __call__(self, query: str) -> str | None: ...
