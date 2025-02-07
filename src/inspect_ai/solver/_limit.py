from typing import Literal

from ._task_state import TaskState


class SampleLimitExceededError(Exception):
    """Exception raised when a sample limit is exceeded.

    Args:
       type (Literal["message", "time", "token", "operator"]): Type of limit exceeded.
       value (int): Value compared to
       limit (int): Limit applied.
       message (str | None): Optional. Human readable message.
    """

    def __init__(
        self,
        type: Literal["message", "time", "token", "operator", "custom"],
        *,
        value: int,
        limit: int,
        message: str | None = None,
        state: TaskState | None = None,
    ) -> None:
        self.type = type
        self.value = value
        self.limit = limit
        self.message = f"Exceeded {type} limit: {limit:,}"
        self.state = state
        super().__init__(message)

    def with_state(self, state: TaskState) -> "SampleLimitExceededError":
        return SampleLimitExceededError(
            self.type,
            value=self.value,
            limit=self.limit,
            message=self.message,
            state=state,
        )
