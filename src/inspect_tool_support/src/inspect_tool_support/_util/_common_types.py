from typing import NewType

from pydantic import BaseModel


class JSONRPCError(BaseModel):
    """
    The shape of the `error` field in a JSON RPC error response. This represents the app layer result of the method invocation.

    See: https://www.jsonrpc.org/specification#error_object
    """

    code: int
    message: str
    data: object | None = None


class ToolException(Exception):
    """Raised when a tool encounters an error."""

    def __init__(self, message: str):
        self.message = message


JSONRPCResponseJSON = NewType("JSONRPCResponseJSON", str)
"""Branded str so that we don't pass the wrong thing"""
