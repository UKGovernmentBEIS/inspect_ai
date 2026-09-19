# tests/tools/test_bash_session_type_submit_no_input.py
from typing import Any

from inspect_ai.tool._tools import _bash_session as bash_session_module


async def test_bash_session_type_submit_without_input_submits_only_newline(
    monkeypatch,
) -> None:
    """Omitting `input` for "type_submit" must submit the pending line.

    `input` is documented as optional for this action, so a bare submit is a
    plain Enter keystroke and must not type any characters before it.
    """
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

    tool = bash_session_module.bash_session(instance="type-submit-no-input")
    result = await tool(action="type_submit")

    assert result == "ok"
    assert captured_params["input"] == "\n"
