import base64
import json
from functools import partial
from typing import Any

import anyio
import pytest

from inspect_ai._util._async import tg_collect
from inspect_ai.util._sandbox._cli import SANDBOX_CLI
from inspect_ai.util._sandbox._json_rpc_transport import SandboxJSONRPCTransport
from inspect_ai.util._sandbox.limits import override_max_exec_output_size
from inspect_ai.util._subprocess import ExecResult

_CHUNK_FIELD = "__inspect_json_rpc_response_chunk__"
_CHUNK_METHOD = "__inspect_json_rpc_response_chunk__"


async def test_sandbox_json_rpc_transport_reassembles_large_unicode_response() -> None:
    original_response = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "stdout": "stdout-" + "🙂" * 1000,
                "stderr": "stderr-" + "界" * 1000,
            },
        },
        ensure_ascii=False,
    )
    original_bytes = original_response.encode("utf-8")
    exec_inputs: list[dict[str, Any]] = []
    handle = "a" * 32

    class FakeSandbox:
        async def exec(self, *args: Any, **kwargs: Any) -> ExecResult[str]:
            exec_inputs.append(kwargs)
            request = json.loads(kwargs["input"])
            if request["method"] == _CHUNK_METHOD:
                params = request["params"]
                if params.get("release") is True:
                    return ExecResult(True, 0, _success_response(), "")
                return ExecResult(
                    True,
                    0,
                    _chunk_response(original_bytes, handle, params["offset"], 127),
                    "",
                )
            return ExecResult(
                True, 0, _chunk_response(original_bytes, handle, 0, 127), ""
            )

    transport = SandboxJSONRPCTransport(FakeSandbox(), SANDBOX_CLI)  # type: ignore[arg-type]

    with override_max_exec_output_size(1024):
        assert await transport("large", {}, False) == original_response

    continuation_offsets = [
        json.loads(call["input"])["params"]["offset"] for call in exec_inputs[1:-1]
    ]
    assert continuation_offsets == sorted(continuation_offsets)
    assert len(continuation_offsets) > 2
    assert all(
        call["env"]["INSPECT_SANDBOX_JSON_RPC_RESPONSE_MAX_BYTES"] == "1024"
        for call in exec_inputs
    )
    assert json.loads(exec_inputs[-1]["input"])["params"]["release"] is True


async def test_sandbox_json_rpc_transport_leaves_plain_response() -> None:
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "ok"})

    class FakeSandbox:
        async def exec(self, *args: Any, **kwargs: Any) -> ExecResult[str]:
            assert json.loads(kwargs["input"])["method"] == "plain"
            return ExecResult(True, 0, response, "")

    transport = SandboxJSONRPCTransport(FakeSandbox(), SANDBOX_CLI)  # type: ignore[arg-type]

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

    transport = SandboxJSONRPCTransport(FakeSandbox(), SANDBOX_CLI)  # type: ignore[arg-type]

    assert await transport("plain", {}, False) == response


async def test_sandbox_json_rpc_transport_rejects_out_of_order_chunk() -> None:
    original_bytes = b'{"jsonrpc":"2.0","id":1,"result":"abcdefghijklmno"}'
    handle = "b" * 32
    continuation_count = 0

    class FakeSandbox:
        async def exec(self, *args: Any, **kwargs: Any) -> ExecResult[str]:
            nonlocal continuation_count
            request = json.loads(kwargs["input"])
            if request["method"] != _CHUNK_METHOD:
                return ExecResult(
                    True, 0, _chunk_response(original_bytes, handle, 0, 10), ""
                )
            if request["params"].get("release") is True:
                return ExecResult(True, 0, _success_response(), "")
            continuation_count += 1
            offset = request["params"]["offset"] + 1
            return ExecResult(
                True, 0, _chunk_response(original_bytes, handle, offset, 10), ""
            )

    transport = SandboxJSONRPCTransport(FakeSandbox(), SANDBOX_CLI)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="out of order"):
        await transport("large", {}, False)
    assert continuation_count == 1


async def test_sandbox_json_rpc_transport_surfaces_continuation_error() -> None:
    original_bytes = b'{"jsonrpc":"2.0","id":1,"result":"abcdefghijklmno"}'
    handle = "c" * 32

    class FakeSandbox:
        async def exec(self, *args: Any, **kwargs: Any) -> ExecResult[str]:
            request = json.loads(kwargs["input"])
            if request["method"] != _CHUNK_METHOD:
                return ExecResult(
                    True, 0, _chunk_response(original_bytes, handle, 0, 10), ""
                )
            if request["params"].get("release") is True:
                return ExecResult(True, 0, _success_response(), "")
            return ExecResult(
                True,
                0,
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "error": {"code": -32000, "message": "chunk missing"},
                    }
                ),
                "",
            )

    transport = SandboxJSONRPCTransport(FakeSandbox(), SANDBOX_CLI)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="chunk missing"):
        await transport("large", {}, False)


async def test_sandbox_json_rpc_transport_keeps_concurrent_handles_separate() -> None:
    responses = {
        "one": json.dumps({"jsonrpc": "2.0", "id": 1, "result": "one" * 200}),
        "two": json.dumps({"jsonrpc": "2.0", "id": 2, "result": "two" * 200}),
    }
    handles = {"one": "1" * 32, "two": "2" * 32}
    response_for_handle = {
        handles[name]: response.encode("utf-8") for name, response in responses.items()
    }

    class FakeSandbox:
        async def exec(self, *args: Any, **kwargs: Any) -> ExecResult[str]:
            await anyio.sleep(0)
            request = json.loads(kwargs["input"])
            if request["method"] == _CHUNK_METHOD:
                params = request["params"]
                if params.get("release") is True:
                    return ExecResult(True, 0, _success_response(), "")
                handle = params["handle"]
                return ExecResult(
                    True,
                    0,
                    _chunk_response(
                        response_for_handle[handle], handle, params["offset"], 31
                    ),
                    "",
                )
            handle = handles[request["method"]]
            return ExecResult(
                True,
                0,
                _chunk_response(response_for_handle[handle], handle, 0, 31),
                "",
            )

    transport = SandboxJSONRPCTransport(FakeSandbox(), SANDBOX_CLI)  # type: ignore[arg-type]
    results = await tg_collect(
        [
            partial(transport, "one", {}, False),
            partial(transport, "two", {}, False),
        ]
    )

    assert results == [responses["one"], responses["two"]]


async def test_legacy_sandbox_transport_does_not_enable_chunk_protocol() -> None:
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "legacy"})

    class FakeSandbox:
        async def exec(self, *args: Any, **kwargs: Any) -> ExecResult[str]:
            assert kwargs["env"] is None
            return ExecResult(True, 0, response, "")

    transport = SandboxJSONRPCTransport(FakeSandbox(), "inspect-tool-support")  # type: ignore[arg-type]

    assert await transport("legacy", {}, False) == response


async def test_sandbox_exec_error_uses_stdout_when_stderr_is_empty() -> None:
    class FakeSandbox:
        async def exec(self, *args: Any, **kwargs: Any) -> ExecResult[str]:
            return ExecResult(False, 1, "stdout diagnostic", "")

    transport = SandboxJSONRPCTransport(FakeSandbox(), SANDBOX_CLI)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="stdout diagnostic"):
        await transport("failing", {}, False)


def _chunk_response(
    response: bytes,
    handle: str,
    offset: int,
    chunk_size: int,
) -> str:
    chunk = response[offset : offset + chunk_size]
    next_offset = offset + len(chunk)
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            _CHUNK_FIELD: {
                "version": 1,
                "handle": handle,
                "offset": offset,
                "next_offset": next_offset,
                "total_size": len(response),
                "done": next_offset == len(response),
                "chunk": base64.b64encode(chunk).decode("ascii"),
            },
        }
    )


def _success_response() -> str:
    return json.dumps({"jsonrpc": "2.0", "id": 1, "result": None})
