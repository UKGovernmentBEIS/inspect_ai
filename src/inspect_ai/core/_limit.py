from __future__ import annotations

import logging
from typing import Literal

from ._warn import warn_once

logger = logging.getLogger(__name__)


class LimitExceededError(Exception):
    """Exception raised when a limit is exceeded.

    In some scenarios this error may be raised when `value >= limit` to
    prevent another operation which is guaranteed to exceed the limit from being
    wastefully performed.

    Args:
       type: Type of limit exceeded.
       value: Value compared to.
       limit: Limit applied.
       message (str | None): Optional. Human readable message.
       source (object | None): Optional. The `Limit` instance which was responsible for raising this error.
    """

    def __init__(
        self,
        type: Literal[
            "message", "time", "working", "token", "turn", "cost", "operator", "custom"
        ],
        *,
        value: float,
        limit: float,
        message: str | None = None,
        source: object | None = None,
    ) -> None:
        self.type = type
        self.value = value
        self.value_str = self._format_float_or_int(value)
        self.limit = limit
        self.limit_str = self._format_float_or_int(limit)
        self.message = message or f"Exceeded {type} limit: {limit:,}"
        self.source = source
        super().__init__(self.message)

    def with_state(self, state: object) -> LimitExceededError:
        warn_once(
            logger,
            "LimitExceededError.with_state() is deprecated (no longer required).",
        )
        return self

    def _format_float_or_int(self, value: float | int) -> str:
        if isinstance(value, int):
            return f"{value:,}"
        else:
            return f"{value:,.2f}"
