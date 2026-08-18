"""Helper code for handling JSON-RPC communication between the inspect process and the injected tool code running in the sandbox environment."""

from inspect_ai._util._json_rpc import (
    JSONRPCErrorMapper,
    JSONRPCParamsType,
)
from inspect_ai.tool._tool import ToolError, ToolParsingError


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
            case -32099:  # ToolException from the container
                return ToolError(message)
            case -32098:  # Unexpected exception inside the container
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
