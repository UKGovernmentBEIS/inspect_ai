"""
This module provides helper code for handling JSON-RPC communication between the inspect process and the `inspect-tool-support` package code running in the sandbox environment.

It includes definitions for JSON-RPC request and response models, as well as functions to create and parse JSON-RPC requests and responses.
"""

from functools import partial
from typing import Type

from inspect_ai.tool._tool import ToolError
from inspect_ai.tool.tool_support._tool_support_sandbox import (
    SANDBOX_CLI,
    inject_tool_support_code,
)
from inspect_ai.util._sandbox.context import sandbox_with_injection
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from .._json_rpc_helpers import (
    BaseModelT,
    JSONRPCParamsType,
    JSONRPCServerErrorMapper,
    JSONRPCTransport,
    ScalarT,
    _rpc_call_description,
    create_json_rpc_request,
)
from .._json_rpc_helpers import exec_model_request as model_request
from .._json_rpc_helpers import exec_notification as notification_helper
from .._json_rpc_helpers import exec_scalar_request as scalar_request


async def exec_scalar_request(
    sandbox: SandboxEnvironment,
    method: str,
    params: JSONRPCParamsType,
    result_type: Type[ScalarT],
    timeout: int,
    user: str | None = None,
) -> ScalarT:
    return await scalar_request(
        method,
        params,
        result_type,
        transport=ToolSupportSandboxTransport(sandbox, timeout, user),
        server_error_mapper=ToolSupportServerErrorMapper(),
    )


async def exec_model_request(
    sandbox: SandboxEnvironment,
    method: str,
    params: JSONRPCParamsType,
    result_type: Type[BaseModelT],
    timeout: int,
    user: str | None = None,
) -> BaseModelT:
    return await model_request(
        method,
        params,
        result_type,
        transport=ToolSupportSandboxTransport(sandbox, timeout, user),
        server_error_mapper=ToolSupportServerErrorMapper(),
    )


async def exec_notification(
    sandbox: SandboxEnvironment,
    method: str,
    params: JSONRPCParamsType,
    timeout: int,
    user: str | None = None,
) -> None:
    return await notification_helper(
        method, params, transport=ToolSupportSandboxTransport(sandbox, timeout, user)
    )


class ToolSupportServerErrorMapper(JSONRPCServerErrorMapper):
    def __call__(
        self, code: int, message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        """Map `inspect-tool-support` defined custom codes to an exception."""
        match code:
            case -32099:  # This is a ToolException from the container
                return ToolError(message)
            case -32098:  # This is an unexpected exception inside the container
                return RuntimeError(message)
            case _:
                return RuntimeError(message)


class ToolSupportSandboxTransport(JSONRPCTransport):
    """
    A transport that uses a sandbox for RPC communication.

    This class implements the TransportCallable protocol and encapsulates the
    sandbox, timeout, and user parameters needed for sandbox-based RPC
    communication.
    """

    def __init__(
        self,
        sandbox: SandboxEnvironment,
        timeout: int,
        user: str | None = None,
    ):
        """
        Initialize a new SandboxTransportCallable.

        Args:
            sandbox (SandboxEnvironment): The sandbox environment to use.
            timeout (int | None, optional): The timeout for executions. Defaults to None.
            user (str | None, optional): Username or UID to run commands as. Defaults to None.
        """
        self.sandbox = sandbox
        self.timeout = timeout
        self.user = user

    async def __call__(
        self, method: str, params: JSONRPCParamsType, is_notification: bool
    ) -> str:
        """
        Execute an RPC request using the sandbox transport.

        Args:
            method (str): The JSON-RPC method to call.
            params (dict[str, object] | tuple[object, ...]): The parameters for the JSON-RPC method.
            is_notification (bool): Whether this is a notification (no response expected).

        Returns:
            str: The response from the RPC call.

        Raises:
            RuntimeError: If the sandbox execution fails.
        """
        exec_result = await self.sandbox.exec(
            [SANDBOX_CLI, "exec"],
            input=create_json_rpc_request(method, params, is_notification),
            timeout=self.timeout,
            user=self.user,
        )

        if not exec_result.success:
            raise RuntimeError(
                f"Sandbox.exec failure executing {_rpc_call_description(method, params)}: {exec_result.stderr}"
            )
        return exec_result.stdout


async def tool_support_sandbox(
    *, sandbox_name: str | None = None, with_web_browser: bool = False
) -> SandboxEnvironment:
    return await sandbox_with_injection(
        SANDBOX_CLI,
        partial(inject_tool_support_code, with_browser=with_web_browser),
        sandbox_name=sandbox_name,
    )


def create_sandbox_transport(
    sandbox: SandboxEnvironment, timeout: int, user: str | None = None
) -> JSONRPCTransport:
    """
    Create a transport callable that uses a sandbox for RPC communication.

    Args:
        sandbox (SandboxEnvironment): The sandbox environment to use.
        timeout (int | None, optional): The timeout for executions. Defaults to None.
        user (str | None, optional): Username or UID to run commands as. Defaults to None.

    Returns:
        TransportCallable: A transport callable that conforms to the TransportCallable protocol.
    """
    return ToolSupportSandboxTransport(sandbox=sandbox, timeout=timeout, user=user)
