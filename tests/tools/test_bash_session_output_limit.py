from typing import Any

from inspect_ai.tool._tools import _bash_session as bash_session_module
from inspect_ai.util._sandbox.limits import override_max_exec_output_size


async def test_bash_session_passes_effective_max_output_size(monkeypatch) -> None:
    captured_params: dict[str, Any] = {}

    class FakeSandbox:
        _tools_user = None

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
