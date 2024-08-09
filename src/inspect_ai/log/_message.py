import re
from logging import LogRecord
from typing import Any, Literal, Type, cast

from pydantic import BaseModel, Field, JsonValue, model_validator
from pydantic_core import to_jsonable_python

LoggingLevel = Literal[
    "debug", "http", "sandbox", "info", "warning", "error", "critical"
]
"""Logging level."""


class LoggingMessage(BaseModel):
    name: str | None = Field(default=None)
    """Logger name (e.g. 'httpx')"""

    level: LoggingLevel
    """Logging level."""

    message: str
    """Log message."""

    created: float
    """Message created time."""

    filename: str = Field(default="unknown")
    """Logged from filename."""

    module: str = Field(default="unknown")
    """Logged from module."""

    lineno: int = Field(default=0)
    """Logged from line number."""

    args: JsonValue = Field(default=None)
    """Extra arguments passed to log function."""

    @staticmethod
    def from_log_record(record: LogRecord) -> "LoggingMessage":
        """Create a LoggingMesssage from a LogRecord.

        Args:
          record (LogRecord): LogRecord to convert.

        Returns:
          LoggingMessage for LogRecord

        """
        return LoggingMessage(
            # don't include full file paths (as the filename is also below),
            # we just want to use this to capture e.g. 'httpx', 'openai', etc.
            name=record.name
            if re.match(r"^[\w_]+$", record.name) is not None
            else None,
            level=cast(LoggingLevel, record.levelname.lower()),
            message=record.getMessage(),
            created=record.created * 1000,
            filename=str(record.filename),
            module=str(record.module),
            lineno=record.lineno or 0,
            # serialize anything we can from the additional arguments
            args=to_jsonable_python(record.args, fallback=lambda _x: None)
            if record.args
            else None,
        )

    @model_validator(mode="before")
    @classmethod
    def convert_log_levels(
        cls: Type["LoggingMessage"], values: dict[str, Any]
    ) -> dict[str, Any]:
        if "level" in values:
            level = values["level"]
            if level == "tools":
                values["level"] = "sandbox"

        return values
