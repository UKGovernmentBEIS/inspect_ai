from enum import IntEnum
from typing import NewType


class ServerErrorCode(IntEnum):
    """JSON-RPC server-defined error codes (-32000..-32099) this server sends.

    The host defines the same codes in
    `inspect_ai.tool._sandbox_tools_utils._error_mapper`; a host test checks that
    they match.
    """

    TOOL_ERROR = -32099
    """A `ToolException`: an error to report to the model."""

    UNEXPECTED_ERROR = -32098
    """An unexpected exception in the server."""

    SESSION_NOT_FOUND = -32097
    """The server has no bound shell of that name."""

    SESSION_OWNER = -32096
    """The bound shell belongs to another user."""


class ToolException(Exception):
    """Raised when a tool encounters an error."""

    code: int = ServerErrorCode.TOOL_ERROR
    """JSON-RPC error code of the response."""

    def __init__(self, message: str):
        self.message = message


JSONRPCResponseJSON = NewType("JSONRPCResponseJSON", str)
"""Branded str so that we don't pass the wrong thing"""
