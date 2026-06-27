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

    output = response["result"]
    assert "bash_session output exceeded" in output
    assert "bytes omitted" in output
    assert "-tail" in output
    assert "head-" not in output
    assert len(output.encode("utf-8")) <= 2048


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
