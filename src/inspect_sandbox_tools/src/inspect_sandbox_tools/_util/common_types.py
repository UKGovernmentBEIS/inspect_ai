from typing import NewType


class ToolException(Exception):
    """Raised when a tool encounters an error."""

    code = -32099
    """JSON-RPC error code of the response."""

    def __init__(self, message: str):
        self.message = message


JSONRPCResponseJSON = NewType("JSONRPCResponseJSON", str)
"""Branded str so that we don't pass the wrong thing"""
