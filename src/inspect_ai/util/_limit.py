from typing import Literal


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
    ) -> None:
        self.type = type
        self.value = value
        self.limit = limit
        self.message = f"Exceeded {type} limit: {limit:,}"
        super().__init__(message)
