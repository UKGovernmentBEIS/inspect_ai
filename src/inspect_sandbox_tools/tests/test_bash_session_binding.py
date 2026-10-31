"""Bound bash sessions: unique names and the owner check, through JSON-RPC dispatch."""

import json
import os
import pwd
import re
from typing import Any

import pytest
from inspect_sandbox_tools._remote_tools._bash_session import (
    _controller,
    json_rpc_methods,
)
from inspect_sandbox_tools._util.common_types import ServerErrorCode
from jsonrpcserver import async_dispatch

# Binding a shell to the current user needs no user switch, so no root.
ME = pwd.getpwuid(os.getuid()).pw_name


class FakeSession:
    """Records the requests a shell acted on, in place of a real bash process."""

    def __init__(self, owner: str | None) -> None:
        self.owner = owner
        self.requests: list[str] = []

    @classmethod
    async def create(cls, user: object = None, owner: str | None = None) -> Any:
        return cls(owner)

    async def interact(self, input_text: str | None, *_args: object) -> str:
        self.requests.append(input_text or "")
        return "out"

    async def restart(self, timeout: int = 30) -> str:
        self.requests.append("restart")
        return "shell restarted successfully"


@pytest.fixture(autouse=True)
def server(monkeypatch: pytest.MonkeyPatch) -> _controller.Controller:
    monkeypatch.setattr(_controller, "Session", FakeSession)
    return replace_server(monkeypatch)


def replace_server(monkeypatch: pytest.MonkeyPatch) -> _controller.Controller:
    """Start a new server's controller, which has no shells."""
    controller = _controller.Controller()
    monkeypatch.setattr(json_rpc_methods, "controller", controller)
    return controller


async def call(method: str, **params: Any) -> dict[str, Any]:
    request = {"jsonrpc": "2.0", "method": method, "id": 1, "params": params}
    return json.loads(await async_dispatch(json.dumps(request)))


async def new_session(**params: Any) -> str:
    response = await call("bash_session_new_session", **params)
    return response["result"]["session_name"]


async def interact(name: str, **params: Any) -> dict[str, Any]:
    return await call(
        "bash_session",
        session_name=name,
        input="id\n",
        wait_for_output=1,
        idle_timeout=0.1,
        **params,
    )


def error_code(response: dict[str, Any]) -> int:
    return response["error"]["code"]


async def test_unbound_shells_keep_counted_names() -> None:
    assert [await new_session(), await new_session(user=ME)] == [
        "BashSession",
        "BashSession_1",
    ]


async def test_a_replaced_server_never_has_a_bound_shell(
    server: _controller.Controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    bound = await new_session(user=ME, bind=True)
    assert re.fullmatch(r"BashSession_[0-9a-f]{32}", bound)
    assert (await interact(bound, owner=ME))["result"] == "out"

    replace_server(monkeypatch)
    first = await new_session()
    assert first == "BashSession"
    assert await new_session(user=ME, bind=True) not in (bound, first)
    assert (
        error_code(await interact(bound, owner=ME)) == ServerErrorCode.SESSION_NOT_FOUND
    )
    restart = await call("bash_session", session_name=bound, owner=ME, restart=True)
    assert error_code(restart) == ServerErrorCode.SESSION_NOT_FOUND
    # an unbound name the server does not have fails as before
    assert (
        error_code(await interact("BashSession_9")) == ServerErrorCode.UNEXPECTED_ERROR
    )


async def test_a_bound_shell_answers_only_its_owner(
    server: _controller.Controller,
) -> None:
    bound = await new_session(user=ME, bind=True)
    unbound = await new_session()
    shell = server.session_for_name(bound)
    assert isinstance(shell, FakeSession) and shell.owner == ME

    assert (
        error_code(await interact(bound, owner="someone-else"))
        == ServerErrorCode.SESSION_OWNER
    )
    assert error_code(await interact(bound)) == ServerErrorCode.SESSION_OWNER
    restart = await call("bash_session", session_name=bound, restart=True)
    assert error_code(restart) == ServerErrorCode.SESSION_OWNER
    assert shell.requests == []

    assert (await interact(bound, owner=ME))["result"] == "out"
    restart = await call("bash_session", session_name=bound, owner=ME, restart=True)
    assert "error" not in restart
    assert shell.requests == ["id\n", "restart"]

    # an owner never reaches an unbound shell either
    assert (
        error_code(await interact(unbound, owner=ME)) == ServerErrorCode.SESSION_OWNER
    )
    assert (await interact(unbound))["result"] == "out"


@pytest.mark.parametrize(
    "user", [None, {"uid": os.getuid(), "gid": os.getgid(), "groups": []}]
)
async def test_binding_needs_a_username(
    server: _controller.Controller, user: object
) -> None:
    response = await call("bash_session_new_session", user=user, bind=True)
    assert error_code(response) == ServerErrorCode.TOOL_ERROR
    assert server._sessions == {}
