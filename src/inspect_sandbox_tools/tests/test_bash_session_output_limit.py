from tests.conftest import DEFAULT_RPC_TIMEOUT, RpcClient


def test_bash_session_truncates_large_output_before_jsonrpc_response(
    monkeypatch, rpc_client: RpcClient, sandbox_server_cleanup: None
) -> None:
    monkeypatch.setenv("INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE", "2048")

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
                "input": (
                    "python - <<'PY'\n"
                    "print('head-' + 'a' * 12000 + '-tail')\n"
                    "PY\n"
                ),
                "wait_for_output": 5,
                "idle_timeout": 0.2,
            },
            "id": 2,
        },
        DEFAULT_RPC_TIMEOUT,
    )

    output = response["result"]
    assert "bash_session output exceeded 2 KiB" in output
    assert "bytes omitted" in output
    assert "-tail" in output
    assert "head-" not in output
    assert len(output.encode("utf-8")) < 2048
