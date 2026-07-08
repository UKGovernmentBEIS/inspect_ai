"""JSON-RPC transport implementation for sandbox environments."""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any

from inspect_ai._util._json_rpc import (
    JSONRPCParamsType,
    JSONRPCTransport,
    create_json_rpc_request,
    rpc_call_description,
)

if TYPE_CHECKING:
    from .environment import SandboxEnvironment


_JSON_RPC_RESPONSE_CHUNK_METHOD = "__inspect_json_rpc_response_chunk__"
_JSON_RPC_RESPONSE_CHUNK_MARKER = "inspect-json-rpc-response-chunk-v1"


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

        Args:
            method: The JSON-RPC method to call.
            params: The parameters for the JSON-RPC method.
            is_notification: Whether this is a notification (no response expected).
            **transport_extra_args: Additional parameters including timeout and user.

        Returns:
            The response from the RPC call.

        Raises:
            RuntimeError: If the sandbox execution fails.
        """
        request = create_json_rpc_request(method, params, is_notification)
        response = await self._sandbox_exec(
            request, rpc_call_description(method, params), transport_extra_args
        )
        return await self._complete_chunked_response(response, transport_extra_args)

    async def _sandbox_exec(
        self,
        request: str,
        description: str,
        transport_extra_args: dict[str, Any],
    ) -> str:
        exec_result = await self.sandbox.exec(
            [self.cli, "exec"],
            input=request,
            timeout=transport_extra_args.get("timeout", None),
            timeout_retry=transport_extra_args.get("timeout_retry", True),
            user=transport_extra_args.get("user", None),
            concurrency=transport_extra_args.get("concurrency", True),
        )

        if not exec_result.success:
            raise RuntimeError(
                f"Sandbox.exec failure executing {description}: {exec_result.stderr}"
            )
        return exec_result.stdout

    async def _complete_chunked_response(
        self,
        response: str,
        transport_extra_args: dict[str, Any],
    ) -> str:
        chunk = _parse_response_chunk(response)
        if chunk is None:
            return response

        response_bytes = bytearray()
        while chunk is not None:
            response_bytes.extend(_decode_chunk(chunk))
            if chunk.get("done") is True:
                return response_bytes.decode("utf-8")

            handle = chunk.get("handle")
            offset = chunk.get("next_offset")
            if not isinstance(handle, str) or not isinstance(offset, int):
                raise RuntimeError("Invalid chunked JSON-RPC response metadata")

            next_response = await self._sandbox_exec(
                create_json_rpc_request(
                    _JSON_RPC_RESPONSE_CHUNK_METHOD,
                    {"handle": handle, "offset": offset},
                    False,
                ),
                "chunked JSON-RPC response continuation",
                transport_extra_args,
            )
            chunk = _parse_response_chunk(next_response, require_chunk=True)

        raise RuntimeError("Unreachable chunked JSON-RPC response state")


def _parse_response_chunk(
    response: str, *, require_chunk: bool = False
) -> dict[str, Any] | None:
    try:
        payload = json.loads(response)
    except json.JSONDecodeError:
        if require_chunk:
            raise RuntimeError("Chunk continuation did not return valid JSON")
        return None

    if not isinstance(payload, dict):
        if require_chunk:
            raise RuntimeError("Chunk continuation did not return a JSON object")
        return None
    if "error" in payload:
        if require_chunk:
            raise RuntimeError(
                f"Chunked JSON-RPC response fetch failed: {payload['error']}"
            )
        return None

    result = payload.get("result")
    if not isinstance(result, dict):
        if require_chunk:
            raise RuntimeError("Chunk continuation did not return chunk metadata")
        return None
    if (
        result.get("__inspect_json_rpc_response_chunk__")
        != _JSON_RPC_RESPONSE_CHUNK_MARKER
    ):
        if require_chunk:
            raise RuntimeError("Chunk continuation did not return chunk metadata")
        return None
    return result


def _decode_chunk(chunk: dict[str, Any]) -> bytes:
    encoded = chunk.get("chunk")
    if not isinstance(encoded, str):
        raise RuntimeError("Invalid chunked JSON-RPC response payload")
    return base64.b64decode(encoded)
