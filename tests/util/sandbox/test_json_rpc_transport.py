import base64
import json
from typing import Any

from inspect_ai.util._sandbox._json_rpc_transport import SandboxJSONRPCTransport
from inspect_ai.util._subprocess import ExecResult

_CHUNK_MARKER = "inspect-json-rpc-response-chunk-v1"
_CHUNK_METHOD = "__inspect_json_rpc_response_chunk__"
_CHUNK_SIZE = 48


async def test_sandbox_json_rpc_transport_reassembles_chunked_response() -> None:
    original_response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "x" * 200})
    original_response_bytes = original_response.encode("utf-8")
    exec_inputs: list[str] = []

    def chunk_response(offset: int) -> str:
        chunk = original_response_bytes[offset : offset + _CHUNK_SIZE]
        next_offset = offset + len(chunk)
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "__inspect_json_rpc_response_chunk__": _CHUNK_MARKER,
                    "handle": "handle",
                    "chunk": base64.b64encode(chunk).decode("ascii"),
                    "next_offset": next_offset,
                    "done": next_offset >= len(original_response_bytes),
                },
            }
        )

    class FakeSandbox:
        async def exec(self, *args: Any, **kwargs: Any) -> ExecResult[str]:
            exec_inputs.append(kwargs["input"])
            if len(exec_inputs) == 1:
                return ExecResult(True, 0, chunk_response(0), "")

            params = json.loads(kwargs["input"])["params"]
            return ExecResult(
                True,
                0,
                chunk_response(params["offset"]),
                "",
            )

    transport = SandboxJSONRPCTransport(FakeSandbox(), "sandbox-cli")  # type: ignore[arg-type]

    assert await transport("large", {}, False) == original_response
    assert len(exec_inputs) > 1
    assert json.loads(exec_inputs[1])["method"] == _CHUNK_METHOD


async def test_sandbox_json_rpc_transport_leaves_plain_response() -> None:
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "ok"})

    class FakeSandbox:
        async def exec(self, *args: Any, **kwargs: Any) -> ExecResult[str]:
            assert json.loads(kwargs["input"])["method"] == "plain"
            return ExecResult(True, 0, response, "")

    transport = SandboxJSONRPCTransport(FakeSandbox(), "sandbox-cli")  # type: ignore[arg-type]

    assert await transport("plain", {}, False) == response


async def test_sandbox_json_rpc_transport_leaves_json_rpc_errors() -> None:
    response = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32099, "message": "tool failed"},
        }
    )

    class FakeSandbox:
        async def exec(self, *args: Any, **kwargs: Any) -> ExecResult[str]:
            return ExecResult(True, 0, response, "")

    transport = SandboxJSONRPCTransport(FakeSandbox(), "sandbox-cli")  # type: ignore[arg-type]

    assert await transport("plain", {}, False) == response
