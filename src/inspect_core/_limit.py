from __future__ import annotations

import abc
import logging
from collections.abc import Callable
from types import TracebackType
from typing import Literal

from ._warn import warn_once

logger = logging.getLogger(__name__)


class Limit(abc.ABC):
    """Base class for all limit context managers."""

    def __init__(self) -> None:
        self._entered = False
        # live override source for a sample-root node (attached by
        # inspect_ai.util._limit_overrides.sample_limit_override_scope and
        # resolved by the node's `limit` property); None for ordinary nodes
        self._limit_override: Callable[[], int | None] | None = None

    def _limit_override_value(self) -> int | None:
        """The live override for this node, or ``None`` when none applies."""
        return self._limit_override() if self._limit_override is not None else None

    @abc.abstractmethod
    def __enter__(self) -> Limit:
        pass

    @abc.abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    @property
    @abc.abstractmethod
    def limit(self) -> float | None:
        """The value of the limit being applied.

        Can be None which represents no limit.
        """
        pass

    @property
    @abc.abstractmethod
    def usage(self) -> float:
        """The current usage of the resource being limited."""
        pass

    @property
    def remaining(self) -> float | None:
        """The remaining "unused" amount of the resource being limited.

        Returns None if the limit is None.
        """
        if self.limit is None:
            return None
        return self.limit - self.usage

    def _check_reuse(self) -> None:
        if self._entered:
            raise RuntimeError(
                "Each Limit may only be used once in a single 'with' block. Please "
                "create a new instance of the Limit."
            )
        self._entered = True


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
       source (Limit | None): Optional. The `Limit` instance which was responsible for raising this error.
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
        source: Limit | None = None,
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
