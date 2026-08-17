from time import monotonic

from inspect_sandbox_tools._remote_tools._bash_session._process import Process

from tests.conftest import DEFAULT_RPC_TIMEOUT, RpcClient


def test_bash_session_truncates_large_output_before_jsonrpc_response(
    rpc_client: RpcClient, sandbox_server_cleanup: None
) -> None:
    session_response = rpc_client(
        {
            "jsonrpc": "2.0",
            "method": "bash_session_new_session",
            "id": 1,
        },
        DEFAULT_RPC_TIMEOUT,
    )
    session_name = session_response["result"]["session_name"]

    response = rpc_client(
        {
            "jsonrpc": "2.0",
            "method": "bash_session",
            "params": {
                "session_name": session_name,
                "max_output_bytes": 2048,
                "input": (
                    "python - <<'PY'\nprint('head-' + 'a' * 12000 + '-tail')\nPY\n"
                ),
                "wait_for_output": 5,
                "idle_timeout": 0.2,
            },
            "id": 2,
        },
        DEFAULT_RPC_TIMEOUT,
    )

    outputs = [response["result"]]
    combined_output = outputs[0]
    for request_id in range(3, 8):
        if "-tail" in combined_output:
            break
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "bash_session",
                "params": {
                    "session_name": session_name,
                    "max_output_bytes": 2048,
                    "wait_for_output": 5,
                    "idle_timeout": 0.2,
                },
                "id": request_id,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        output = response["result"]
        outputs.append(output)
        combined_output += output

    assert "bash_session output exceeded" in combined_output
    assert "bytes omitted" in combined_output
    assert "-tail" in combined_output
    assert "head-" not in outputs[0]
    assert all(len(output.encode("utf-8")) <= 2048 for output in outputs)


def test_bash_session_honors_larger_rpc_output_limit(
    rpc_client: RpcClient, sandbox_server_cleanup: None
) -> None:
    session_response = rpc_client(
        {
            "jsonrpc": "2.0",
            "method": "bash_session_new_session",
            "id": 1,
        },
        DEFAULT_RPC_TIMEOUT,
    )
    session_name = session_response["result"]["session_name"]

    response = rpc_client(
        {
            "jsonrpc": "2.0",
            "method": "bash_session",
            "params": {
                "session_name": session_name,
                "max_output_bytes": 8000,
                "input": (
                    "python - <<'PY'\nprint('head-' + 'a' * 3000 + '-tail')\nPY\n"
                ),
                "wait_for_output": 5,
                "idle_timeout": 0.2,
            },
            "id": 2,
        },
        DEFAULT_RPC_TIMEOUT,
    )

    output = response["result"]
    assert "bash_session output exceeded" not in output
    assert "head-" in output
    assert "-tail" in output


def test_bash_session_bounds_multibyte_stdout_and_stderr(
    rpc_client: RpcClient, sandbox_server_cleanup: None
) -> None:
    session_response = rpc_client(
        {
            "jsonrpc": "2.0",
            "method": "bash_session_new_session",
            "id": 1,
        },
        DEFAULT_RPC_TIMEOUT,
    )
    session_name = session_response["result"]["session_name"]
    params = {
        "session_name": session_name,
        "max_output_bytes": 4096,
        "wait_for_output": 5,
        "idle_timeout": 0.2,
    }

    first_response = rpc_client(
        {
            "jsonrpc": "2.0",
            "method": "bash_session",
            "params": {
                **params,
                "input": (
                    "python - <<'PY'\n"
                    "import sys\n"
                    "sys.stdout.write('stdout-head-' + '🙂' * 200000)\n"
                    "sys.stdout.flush()\n"
                    "sys.stderr.write('stderr-tail-' + '界' * 200000 + '-final')\n"
                    "sys.stderr.flush()\n"
                    "PY\n"
                ),
            },
            "id": 2,
        },
        DEFAULT_RPC_TIMEOUT,
    )
    outputs = [first_response["result"]]
    combined_output = outputs[0]
    deadline = monotonic() + 30
    request_id = 3
    while "-final" not in combined_output and monotonic() < deadline:
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "bash_session",
                "params": params,
                "id": request_id,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        output = response["result"]
        outputs.append(output)
        combined_output += output
        request_id += 1

    assert all(len(output.encode("utf-8")) <= 4096 for output in outputs)
    assert "bash_session output exceeded" in combined_output
    assert "-final" in combined_output
    assert "�" not in combined_output


def test_bash_session_truncation_notice_respects_tiny_limit() -> None:
    process = Process.__new__(Process)
    process._output_limit = 32
    process._output_data = bytearray(("🙂" * 100).encode("utf-8")[-32:])
    process._dropped_output_bytes = 368

    output = process._format_output()

    assert len(output.encode("utf-8")) <= 32
    assert "�" not in output
