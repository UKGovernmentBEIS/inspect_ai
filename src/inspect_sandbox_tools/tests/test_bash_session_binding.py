"""Bash session creation: names, the owner check and the working directory."""

import asyncio
import json
import os
import pwd
import re
import threading
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest
from inspect_sandbox_tools._remote_tools._bash_session import (
    _controller,
    json_rpc_methods,
)
from inspect_sandbox_tools._remote_tools._bash_session._session import Session
from inspect_sandbox_tools._util.common_types import ServerErrorCode
from jsonrpcserver import async_dispatch

# Binding a shell to the current user needs no user switch, so no root.
ME = pwd.getpwuid(os.getuid()).pw_name


class FakeSession:
    """Records the requests a shell acted on, in place of a real bash process."""

    def __init__(self, owner: str | None, cwd: str | None = None) -> None:
        self.owner = owner
        self.cwd = cwd
        self.requests: list[str] = []

    @classmethod
    async def create(
        cls, user: object = None, owner: str | None = None, cwd: str | None = None
    ) -> Any:
        return cls(owner, cwd)

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


async def test_a_shell_starts_in_the_requested_directory(
    server: _controller.Controller,
) -> None:
    bound = await new_session(user=ME, bind=True, cwd="/tmp")
    shell = server.session_for_name(bound)
    assert isinstance(shell, FakeSession) and shell.cwd == "/tmp"

    response = await call("bash_session_new_session", user=ME, bind=True, cwd="tmp")
    assert error_code(response) == ServerErrorCode.TOOL_ERROR
    assert "absolute" in response["error"]["message"]


async def test_a_real_shell_starts_and_restarts_in_its_directory(
    tmp_path: Path,
) -> None:
    session = await Session.create(cwd=str(tmp_path))
    try:
        assert str(tmp_path.resolve()) in await shell_output(session, "pwd -P")
        await session.restart(timeout=10)
        assert str(tmp_path.resolve()) in await shell_output(session, "pwd -P")
    finally:
        await session.terminate(timeout=10)


async def test_a_directory_the_user_cannot_enter_fails_creation(
    server: _controller.Controller, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(_controller, "Session", Session)
    unusable = [tmp_path / "missing"]
    if os.getuid() != 0:  # root enters any directory
        unusable.append(tmp_path / "closed")
        unusable[-1].mkdir(mode=0)
    for cwd in unusable:
        response = await call("bash_session_new_session", cwd=str(cwd))
        assert error_code(response) == ServerErrorCode.TOOL_ERROR
        assert f"cannot start in {str(cwd)!r}" in response["error"]["message"]
    assert server._sessions == {}


async def shell_output(session: Session, command: str) -> str:
    # the quotes keep the marker out of any echo of the command itself
    output = await session.interact(f"{command}; echo __do''ne__\n", 5, 0.2, None)
    for _ in range(20):
        if "__done__" in output:
            break
        output += await session.interact(None, 5, 0.2, None)
    return output


class Gate:
    """Holds one session creation until released."""

    def __init__(self, fail: bool = False) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.fail = fail


def gated_sessions(gates: list[Gate]) -> type[FakeSession]:
    """Sessions whose creations wait, in turn, for `gates`; later ones do not."""
    pending = list(gates)

    class GatedSession(FakeSession):
        @classmethod
        async def create(
            cls, user: object = None, owner: str | None = None, cwd: str | None = None
        ) -> Any:
            if pending:
                gate = pending.pop(0)
                gate.started.set()
                await gate.release.wait()
                if gate.fail:
                    raise RuntimeError("the shell did not start")
            return cls(owner, cwd)

    return GatedSession


def run_with_deadline(scenario: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Run `scenario` on its own event loop in a thread, failing if it hangs.

    A lock that blocks the event loop thread stops the loop itself, so the
    deadline has to be outside it.
    """
    errors: list[BaseException] = []

    def run() -> None:
        try:
            asyncio.run(scenario())
        except BaseException as ex:
            errors.append(ex)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=20)
    assert not thread.is_alive(), "the server's event loop is blocked"
    if errors:
        raise errors[0]


async def start_overlapping_creation(
    server: _controller.Controller,
    monkeypatch: pytest.MonkeyPatch,
    first: Gate,
    bind: bool,
) -> tuple["asyncio.Task[str]", "asyncio.Task[str]"]:
    """Start a creation held at `first`, then a second one while it is held.

    Checks that the server still answers a request for an existing shell while
    both wait.
    """
    existing = await server.new_session()
    monkeypatch.setattr(_controller, "Session", gated_sessions([first]))
    first_task = asyncio.create_task(server.new_session(user=ME, bind=bind))
    await first.started.wait()
    second_task = asyncio.create_task(server.new_session(user=ME, bind=bind))
    await asyncio.sleep(0)
    assert not second_task.done()
    assert (await interact(existing))["result"] == "out"
    return first_task, second_task


def check_names(names: list[str], bind: bool) -> None:
    if bind:
        assert all(re.fullmatch(r"BashSession_[0-9a-f]{32}", n) for n in names)
        assert len(set(names)) == len(names)
    else:
        assert names == [f"BashSession_{i}" for i in range(1, len(names) + 1)]


@pytest.mark.parametrize("bind", [False, True], ids=["counted", "bound"])
def test_overlapping_creations_both_complete(
    server: _controller.Controller, monkeypatch: pytest.MonkeyPatch, bind: bool
) -> None:
    async def scenario() -> None:
        first = Gate()
        first_task, second_task = await start_overlapping_creation(
            server, monkeypatch, first, bind
        )
        first.release.set()
        names = [await first_task, await second_task]
        check_names(names, bind)
        assert set(names) < set(server._sessions)

    run_with_deadline(scenario)


@pytest.mark.parametrize("bind", [False, True], ids=["counted", "bound"])
def test_a_failed_creation_does_not_hold_up_the_next(
    server: _controller.Controller, monkeypatch: pytest.MonkeyPatch, bind: bool
) -> None:
    async def scenario() -> None:
        first = Gate(fail=True)
        first_task, second_task = await start_overlapping_creation(
            server, monkeypatch, first, bind
        )
        first.release.set()
        with pytest.raises(RuntimeError, match="did not start"):
            await first_task
        names = [await second_task, await server.new_session(user=ME, bind=bind)]
        check_names(names, bind)
        assert len(server._sessions) == 3

    run_with_deadline(scenario)


@pytest.mark.parametrize("bind", [False, True], ids=["counted", "bound"])
def test_a_cancelled_creation_does_not_hold_up_the_next(
    server: _controller.Controller, monkeypatch: pytest.MonkeyPatch, bind: bool
) -> None:
    async def scenario() -> None:
        first = Gate()
        first_task, second_task = await start_overlapping_creation(
            server, monkeypatch, first, bind
        )
        first_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_task
        names = [await second_task, await server.new_session(user=ME, bind=bind)]
        check_names(names, bind)
        assert len(server._sessions) == 3

    run_with_deadline(scenario)
