"""
This module provides helper code for handling JSON-RPC communication between the inspect process and the `inspect-tool-support` package code running in the sandbox environment.

It includes definitions for JSON-RPC request and response models, as well as functions to create and parse JSON-RPC requests and responses.
"""

from textwrap import dedent
from typing import Type

import semver

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.tool._tool import ToolError
from inspect_ai.util import sandbox_with
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from ._json_rpc_helpers import (
    BaseModelT,
    JSONRPCParamsType,
    JSONRPCServerErrorMapper,
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


SANDBOX_CLI = "inspect-tool-support"
INSPECT_TOOL_SUPPORT_IMAGE_DOCKERHUB = "aisiuk/inspect-tool-support"
FIRST_PUBLISHED_VERSION = semver.Version.parse("0.1.6")
MIN_SUPPORTED_VERSION = FIRST_PUBLISHED_VERSION
MIN_NON_DEPRECATED_VERSION = semver.Version.parse("1.0.0")


async def _get_sandbox_tool_support_version(
    sandbox: SandboxEnvironment,
) -> semver.Version:
    try:
        return semver.Version.parse(
            await exec_scalar_request(sandbox, "version", {}, str, 5)
        )
    except RuntimeError as rte:
        if "-32601" in str(rte):
            # The container doesn't even have a version method. The first version
            # published was 0.1.6, so we'll have to assume it was that old.
            return FIRST_PUBLISHED_VERSION
        raise rte


async def tool_support_sandbox(
    tool_name: str, *, sandbox_name: str | None = None
) -> tuple[SandboxEnvironment, semver.Version]:
    if sb := await sandbox_with(SANDBOX_CLI, True, name=sandbox_name):
        current_version = await _get_sandbox_tool_support_version(sb)
        return (sb, current_version)

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
