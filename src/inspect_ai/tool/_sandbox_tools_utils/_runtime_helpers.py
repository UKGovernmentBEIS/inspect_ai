"""
This module provides helper code for handling JSON-RPC communication between the inspect process and the the injected tool code running in the sandbox environment.

It includes definitions for JSON-RPC request and response models, as well as functions to create and parse JSON-RPC requests and responses.
"""

from typing import Any

from inspect_ai.tool._tool import ToolError
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from .._json_rpc_helpers import (
    JSONRPCParamsType,
    JSONRPCServerErrorMapper,
    JSONRPCTransport,
    _rpc_call_description,
    create_json_rpc_request,
)


class SandboxToolsServerErrorMapper(JSONRPCServerErrorMapper):
    """Error mapper for inspect-tool-support server-specific JSON-RPC error codes.

    This mapper handles custom error codes defined by inspect sandbox tools server
    code and converts them into appropriate Python exceptions. It implements the
    JSONRPCServerErrorMapper protocol to provide domain-specific error handling
    for tool support operations.

    Supported error codes:
        -32099: ToolException from the container, mapped to ToolError
        -32098: Unexpected exception inside the container, mapped to RuntimeError
        Other codes: Mapped to RuntimeError with the original message
    """

    def __call__(
        self, code: int, message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        """Map `inspect-tool-support` defined custom codes to an exception."""
        del method, params  # unused parameters required by protocol
        match code:
            case -32099:  # This is a ToolException from the container
                return ToolError(message)
            case -32098:  # This is an unexpected exception inside the container
                return RuntimeError(message)
            case _:
                return RuntimeError(message)


class SandboxJSONRPCTransport(JSONRPCTransport):
    """
    A transport that uses a sandbox for RPC communication.

    This class implements the JSONRPCTransport protocol. The timeout and user
    parameters are passed via transport_extra_args in the __call__ method.
    """

    def __init__(
        self,
        sandbox: SandboxEnvironment,
        cli: str,
    ):
        """
        Initialize a new SandboxJSONRPCTransport.

        Args:
            sandbox (SandboxEnvironment): The sandbox environment to use.
            cli: The path to the cli available in the sandbox.
        """
        self.sandbox = sandbox
        self.cli = cli

    async def __call__(
        self,
        method: str,
        params: JSONRPCParamsType,
        is_notification: bool,
        **transport_extra_args: Any,
    ) -> str:
        """
        Execute an RPC request using the sandbox transport.

        Args:
            method (str): The JSON-RPC method to call.
            params (dict[str, object] | tuple[object, ...]): The parameters for the JSON-RPC method.
            is_notification (bool): Whether this is a notification (no response expected).
            **transport_extra_args: Additional parameters including timeout and user.

        Returns:
            str: The response from the RPC call.

        Raises:
            RuntimeError: If the sandbox execution fails.
        """
        exec_result = await self.sandbox.exec(
            [self.cli, "exec"],
            input=create_json_rpc_request(method, params, is_notification),
            timeout=transport_extra_args.get("timeout", None),
            user=transport_extra_args.get("user", None),
        )

        if not exec_result.success:
            raise RuntimeError(
                f"Sandbox.exec failure executing {_rpc_call_description(method, params)}: {exec_result.stderr}"
            )
        return exec_result.stdout
