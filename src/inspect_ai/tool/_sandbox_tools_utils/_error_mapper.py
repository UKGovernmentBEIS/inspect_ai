"""Helper code for handling JSON-RPC communication between the inspect process and the injected tool code running in the sandbox environment."""

from enum import IntEnum

from inspect_ai._util._json_rpc import (
    JSONRPCErrorMapper,
    JSONRPCParamsType,
)
from inspect_ai.tool._tool import ToolError, ToolParsingError


class ServerErrorCode(IntEnum):
    """JSON-RPC server-defined error codes (-32000..-32099) the tools server sends.

    The injected server cannot import inspect_ai, so it defines the same codes in
    `inspect_sandbox_tools._util.common_types`; a test checks that they match.
    """

    TOOL_ERROR = -32099
    """A tool error to report to the model."""

    UNEXPECTED_ERROR = -32098
    """An unexpected exception in the tools server."""

    SESSION_NOT_FOUND = -32097
    """The server has no bound shell of that name."""

    SESSION_OWNER = -32096
    """The bound shell belongs to another user."""


class SandboxToolsErrorMapper(JSONRPCErrorMapper):
    """Error mapper for sandbox tool JSON-RPC error codes.

    Maps JSON-RPC errors to tool-layer exceptions so that errors are fed back
    to the model rather than crashing the eval.
    """

    @staticmethod
    def server_error(
        code: int, message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        """Map server-defined codes (-32000..-32099) to an exception."""
        del method, params
        match code:
            case ServerErrorCode.TOOL_ERROR:
                return ToolError(message)
            case ServerErrorCode.UNEXPECTED_ERROR:
                return RuntimeError(message)
            case _:
                return RuntimeError(message)

    @staticmethod
    def invalid_params(
        message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        del method, params
        return ToolParsingError(message)

    @staticmethod
    def internal_error(
        message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        del method, params
        return ToolError(message)
