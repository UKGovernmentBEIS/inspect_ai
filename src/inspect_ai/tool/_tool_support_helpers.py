"""
This module provides helper code for handling JSON-RPC communication between the inspect process and the `inspect-tool-support` package code running in the sandbox environment.

It includes definitions for JSON-RPC request and response models, as well as functions to create and parse JSON-RPC requests and responses.
"""

from textwrap import dedent
from typing import Type

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util import sandbox_with
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from ._json_rpc_helpers import (
    BaseModelT,
    JSONRPCParamsType,
    JSONRPCTransport,
    ScalarT,
    _rpc_call_description,
    create_json_rpc_request,
)
from ._json_rpc_helpers import exec_model_request as model_request
from ._json_rpc_helpers import exec_notification as notification_helper
from ._json_rpc_helpers import exec_scalar_request as scalar_request


async def exec_scalar_request(
    sandbox: SandboxEnvironment,
    method: str,
    params: JSONRPCParamsType,
    result_type: Type[ScalarT],
    timeout: int | None = None,
    user: str | None = None,
) -> ScalarT:
    return await scalar_request(
        method,
        params,
        result_type,
        transport=ToolSupportSandboxTransport(sandbox, timeout, user),
    )


async def exec_model_request(
    sandbox: SandboxEnvironment,
    method: str,
    params: JSONRPCParamsType,
    result_type: Type[BaseModelT],
    timeout: int | None = None,
    user: str | None = None,
) -> BaseModelT:
    return await model_request(
        method,
        params,
        result_type,
        transport=ToolSupportSandboxTransport(sandbox, timeout, user),
    )


async def exec_notification(
    sandbox: SandboxEnvironment,
    method: str,
    params: JSONRPCParamsType,
    timeout: int | None = None,
    user: str | None = None,
) -> None:
    return await notification_helper(
        method, params, transport=ToolSupportSandboxTransport(sandbox, timeout, user)
    )


class ToolSupportSandboxTransport(JSONRPCTransport):
    """
    A transport callable that uses a sandbox for RPC communication.

    This class implements the TransportCallable protocol and encapsulates
    the sandbox, timeout, and user parameters needed for sandbox-based
    RPC communication.
    """

    def __init__(
        self,
        sandbox: SandboxEnvironment,
        timeout: int | None = None,
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


SANDBOX_CLI = "inspect-tool-support"
INSPECT_TOOL_SUPPORT_IMAGE_DOCKERHUB = "aisiuk/inspect-tool-support"


async def tool_container_sandbox(
    tool_name: str, *, sandbox_name: str | None = None
) -> SandboxEnvironment:
    if sb := await sandbox_with(SANDBOX_CLI, True, name=sandbox_name):
        return sb

    # This sort of programmatic sentence building will not cut it if we ever
    # support other languages.
    raise PrerequisiteError(
        dedent(f"""
            The {tool_name} service was not found in {"any of the sandboxes" if sandbox_name is None else f"the sandbox '{sandbox_name}'"} for this sample. Please add the {tool_name} to your configuration.

            For example, the following Docker compose file uses the {INSPECT_TOOL_SUPPORT_IMAGE_DOCKERHUB} reference image as its default sandbox:

            services:
              default:
                image: "{INSPECT_TOOL_SUPPORT_IMAGE_DOCKERHUB}"
                init: true

            Alternatively, you can include the service into your own Dockerfile:

            ENV PATH="$PATH:/opt/inspect_tool_support/bin"
            RUN python -m venv /opt/inspect_tool_support && \\
                /opt/inspect_tool_support/bin/pip install inspect-tool-support && \\
                /opt/inspect_tool_support/bin/inspect-tool-support post-install
            """).strip()
    )


def create_sandbox_transport(
    sandbox: SandboxEnvironment, timeout: int | None = None, user: str | None = None
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
