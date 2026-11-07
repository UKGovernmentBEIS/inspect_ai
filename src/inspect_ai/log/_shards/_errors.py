"""Errors raised by the shard merge (see :func:`merge_eval_log_shards`)."""

from typing import Literal


class ShardSetError(Exception):
    """The shards directory's contents cannot be merged (details in the message)."""


class ShardSelectionError(ShardSetError):
    """The shards hold samples outside the intended selection."""

    def __init__(self, message: str, outside: list[str] | None) -> None:
        super().__init__(message)
        self.outside = outside
        """Held ids outside an id selection, sorted; `None` for a count."""


class ShardSetIncomplete(Exception):
    """The shard set is incomplete and `allow_incomplete` was not set."""

    def __init__(
        self,
        message: str,
        *,
        status: Literal["started", "error"],
        missing: list[str | int] | None,
        running: list[str],
        failed: list[str],
    ) -> None:
        super().__init__(message)
        self.status = status
        """Status the merged log would have."""
        self.missing = missing
        """Ids of the intended selection that no shard holds for every epoch
        (`None` for a count or no selection)."""
        self.running = running
        """Shards whose current attempt is `started`."""
        self.failed = failed
        """Shards whose current attempt is `error` or `cancelled`."""
