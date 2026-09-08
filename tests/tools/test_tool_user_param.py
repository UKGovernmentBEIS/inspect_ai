"""The sandbox tools send the sandbox's default identity unless a user is given."""

from typing import Any

import pytest

from inspect_ai.tool._tools import _bash_session as bash_session_module
from inspect_ai.tool._tools import _text_editor as text_editor_module
from inspect_ai.util._sandbox.environment import SandboxDefaultUser

DEFAULT_USER = SandboxDefaultUser(uid=1111, gid=1111, groups=[1111], home="/h")


class FakeSandbox:
    _tools_user = "root"
    _tools_default_user = DEFAULT_USER


def _patch_module(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_sandbox_with_injected_tools(**_kwargs: Any) -> FakeSandbox:
        return FakeSandbox()

    async def fake_request(*_args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        if kwargs["method"] == "bash_session_new_session":
            return bash_session_module.NewSessionResult(session_name="s")
        return "ok"

    monkeypatch.setattr(
        module, "sandbox_with_injected_tools", fake_sandbox_with_injected_tools
    )
    monkeypatch.setattr(module, "SandboxJSONRPCTransport", lambda *a, **k: None)
    for name in ("exec_model_request", "exec_scalar_request"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, fake_request)
    return calls


@pytest.mark.parametrize(
    "user, expected", [(None, DEFAULT_USER._asdict()), ("nobody", "nobody")]
)
async def test_text_editor_sends_user(
    monkeypatch: pytest.MonkeyPatch, user: str | None, expected: object
) -> None:
    calls = _patch_module(monkeypatch, text_editor_module)
    await text_editor_module.text_editor(user=user)(command="view", path="/x")
    [call] = calls
    assert call["params"]["_run_as"] == expected
    assert call["user"] == "root"


@pytest.mark.parametrize(
    "user, expected", [(None, DEFAULT_USER._asdict()), ("nobody", "nobody")]
)
async def test_bash_session_sends_user(
    monkeypatch: pytest.MonkeyPatch, user: str | None, expected: object
) -> None:
    from inspect_ai.util._store import Store, init_subtask_store

    init_subtask_store(Store())
    calls = _patch_module(monkeypatch, bash_session_module)
    await bash_session_module.bash_session(user=user)(action="read")
    new_session, _interact = calls
    assert new_session["method"] == "bash_session_new_session"
    assert new_session["params"]["user"] == expected
    assert new_session["user"] == "root"
