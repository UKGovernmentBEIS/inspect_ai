from typing import Any

from inspect_ai.tool._tools import _bash_session as bash_session_module
from inspect_ai.util import Store, tool_state_instance, tool_state_scope
from inspect_ai.util._sandbox.limits import override_max_exec_output_size
from inspect_ai.util._store import init_subtask_store


async def test_bash_session_passes_effective_max_output_size(monkeypatch) -> None:
    captured_params: dict[str, Any] = {}

    class FakeSandbox:
        _tools_user = None
        _tools_default_user = None

    class FakeTransport:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    async def fake_sandbox_with_injected_tools() -> FakeSandbox:
        return FakeSandbox()

    async def fake_exec_model_request(*args: Any, **kwargs: Any) -> Any:
        return bash_session_module.NewSessionResult(session_name="session")

    async def fake_exec_scalar_request(*args: Any, **kwargs: Any) -> str:
        captured_params.update(kwargs["params"])
        return "ok"

    monkeypatch.setattr(
        bash_session_module,
        "sandbox_with_injected_tools",
        fake_sandbox_with_injected_tools,
    )
    monkeypatch.setattr(bash_session_module, "SandboxJSONRPCTransport", FakeTransport)
    monkeypatch.setattr(
        bash_session_module, "exec_model_request", fake_exec_model_request
    )
    monkeypatch.setattr(
        bash_session_module, "exec_scalar_request", fake_exec_scalar_request
    )

    with override_max_exec_output_size(20 * 1024**2):
        tool = bash_session_module.bash_session(instance="output-limit-test")
        result = await tool(action="type_submit", input="echo ok")

    assert result == "ok"
    assert captured_params["max_output_bytes"] == 20 * 1024**2


async def test_bash_session_type_submit_without_input_sends_bare_return(
    monkeypatch,
) -> None:
    captured_params: dict[str, Any] = {}

    class FakeSandbox:
        _tools_user = None
        _tools_default_user = None

    class FakeTransport:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    async def fake_sandbox_with_injected_tools() -> FakeSandbox:
        return FakeSandbox()

    async def fake_exec_model_request(*args: Any, **kwargs: Any) -> Any:
        return bash_session_module.NewSessionResult(session_name="session")

    async def fake_exec_scalar_request(*args: Any, **kwargs: Any) -> str:
        captured_params.update(kwargs["params"])
        return "ok"

    monkeypatch.setattr(
        bash_session_module,
        "sandbox_with_injected_tools",
        fake_sandbox_with_injected_tools,
    )
    monkeypatch.setattr(bash_session_module, "SandboxJSONRPCTransport", FakeTransport)
    monkeypatch.setattr(
        bash_session_module, "exec_model_request", fake_exec_model_request
    )
    monkeypatch.setattr(
        bash_session_module,
        "exec_scalar_request",
        fake_exec_scalar_request,
    )

    tool = bash_session_module.bash_session(instance="no-input-submit-test")
    result = await tool(action="type_submit")

    assert result == "ok"
    assert captured_params["input"] == "\n"


async def test_bash_session_default_instance_is_per_tool_state_scope(
    monkeypatch,
) -> None:
    new_sessions: list[str] = []
    used_sessions: list[tuple[str | None, object]] = []

    class FakeSandbox:
        _tools_user = None
        _tools_default_user = None

    class FakeTransport:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    async def fake_sandbox_with_injected_tools() -> FakeSandbox:
        return FakeSandbox()

    async def fake_exec_model_request(*args: Any, **kwargs: Any) -> Any:
        new_sessions.append(f"session-{len(new_sessions) + 1}")
        return bash_session_module.NewSessionResult(session_name=new_sessions[-1])

    async def fake_exec_scalar_request(*args: Any, **kwargs: Any) -> str:
        used_sessions.append(
            (tool_state_instance(None), kwargs["params"]["session_name"])
        )
        return "ok"

    monkeypatch.setattr(
        bash_session_module,
        "sandbox_with_injected_tools",
        fake_sandbox_with_injected_tools,
    )
    monkeypatch.setattr(bash_session_module, "SandboxJSONRPCTransport", FakeTransport)
    monkeypatch.setattr(
        bash_session_module, "exec_model_request", fake_exec_model_request
    )
    monkeypatch.setattr(
        bash_session_module, "exec_scalar_request", fake_exec_scalar_request
    )

    init_subtask_store(Store())
    tool = bash_session_module.bash_session()
    for scope in ["w-1", "w-2", "w-1", "w-2"]:
        with tool_state_scope(scope):
            await tool(action="type_submit", input="echo ok")
    await tool(action="type_submit", input="echo ok")

    assert new_sessions == ["session-1", "session-2", "session-3"]
    assert used_sessions == [
        ("@w-1", "session-1"),
        ("@w-2", "session-2"),
        ("@w-1", "session-1"),
        ("@w-2", "session-2"),
        (None, "session-3"),
    ]
