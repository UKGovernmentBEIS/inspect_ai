"""JSON-RPC transport implementation for sandbox environments."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from inspect_ai._util._json_rpc import (
    JSONRPCParamsType,
    JSONRPCTransport,
    create_json_rpc_request,
    rpc_call_description,
)

if TYPE_CHECKING:
    from .environment import SandboxEnvironment

logger = logging.getLogger(__name__)

# Retry config for transient sandbox.exec failures
_MAX_RETRIES = 2
_RETRY_DELAY_SECS = 1.0


class SandboxJSONRPCTransport(JSONRPCTransport):
    """A transport that uses a sandbox for RPC communication.

    This class implements the JSONRPCTransport protocol. The timeout and user
    parameters are passed via transport_extra_args in the __call__ method.
    """

    def __init__(
        self,
        sandbox: SandboxEnvironment,
        cli: str,
    ):
        """Initialize a new SandboxJSONRPCTransport.

        Args:
            sandbox: The sandbox environment to use.
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
        """Execute an RPC request using the sandbox transport.

        Retries transient sandbox.exec failures (non-zero exit code) up to
        _MAX_RETRIES times with a short delay.  The MCP server inside the
        container is a separate long-lived process, so a failed exec does not
        affect server state — retrying the same CLI invocation is safe.

        Timeouts are already handled by the sandbox backend's own
        timeout_retry logic and are not retried here.

        Args:
            method: The JSON-RPC method to call.
            params: The parameters for the JSON-RPC method.
            is_notification: Whether this is a notification (no response expected).
            **transport_extra_args: Additional parameters including timeout and user.

        Returns:
            The response from the RPC call.

        Raises:
            RuntimeError: If the sandbox execution fails after all retries.
        """
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                exec_result = await self.sandbox.exec(
                    [self.cli, "exec"],
                    input=create_json_rpc_request(method, params, is_notification),
                    timeout=transport_extra_args.get("timeout", None),
                    timeout_retry=transport_extra_args.get("timeout_retry", True),
                    user=transport_extra_args.get("user", None),
                    concurrency=transport_extra_args.get("concurrency", True),
                )
            except TimeoutError:
                # Already handled by the sandbox backend's timeout_retry.
                raise
            except Exception as exc:
                # sandbox.exec() itself raised (e.g. Docker daemon
                # unreachable, connection refused, etc.)
                last_error = exc
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        f"Sandbox.exec raised (attempt {attempt + 1}/{_MAX_RETRIES + 1}), "
                        f"retrying in {_RETRY_DELAY_SECS}s: "
                        f"{rpc_call_description(method, params)}: {exc}"
                    )
                    await asyncio.sleep(_RETRY_DELAY_SECS)
                    continue
                raise

            if exec_result.success:
                return exec_result.stdout

            # Non-zero exit code — the CLI invocation failed but the
            # MCP server inside the container is unaffected. Prefer stderr,
            # but fall back to stdout — some failures (e.g. MCP server
            # crash, entrypoint error) only surface in stdout because the
            # sandbox CLI wrote its diagnostic there.
            error_detail = (
                exec_result.stderr
                or exec_result.stdout
                or "(no output captured — check container startup.log)"
            )
            last_error = RuntimeError(
                f"Sandbox.exec failure executing "
                f"{rpc_call_description(method, params)}: {error_detail}"
            )

            if attempt < _MAX_RETRIES:
                logger.warning(
                    f"Sandbox.exec failed (attempt {attempt + 1}/{_MAX_RETRIES + 1}), "
                    f"retrying in {_RETRY_DELAY_SECS}s: "
                    f"{rpc_call_description(method, params)}: {error_detail}"
                )
                await asyncio.sleep(_RETRY_DELAY_SECS)

        assert last_error is not None
        raise last_error
