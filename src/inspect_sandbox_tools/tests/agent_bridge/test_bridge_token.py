"""The model proxy's bridge token: publishing it and requiring it."""

import asyncio
import os
import pwd
import socket
import stat
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from aiohttp import ClientSession
from inspect_sandbox_tools._agent_bridge.bridge_token import (
    TOKEN_DIR,
    TOKEN_FILE_ENV,
    TOKEN_USER_ENV,
    TokenRequest,
    new_token,
    publish_token,
    token_request,
)
from inspect_sandbox_tools._agent_bridge.proxy import (
    AsyncHTTPServer,
    serve_model_proxy,
)

USER = pwd.getpwuid(os.geteuid()).pw_name


@pytest.fixture
def request_in(tmp_path: Path) -> TokenRequest:
    return TokenRequest(tmp_path / "bridge" / "proxy_abc", USER)


def test_publish_creates_the_file_for_the_user_in_a_0711_directory(
    request_in: TokenRequest,
) -> None:
    token = new_token()
    publish_token(token, request_in)

    info = request_in.file.lstat()
    assert stat.S_ISREG(info.st_mode)
    assert stat.S_IMODE(info.st_mode) == 0o400
    assert info.st_uid == pwd.getpwnam(USER).pw_uid
    assert request_in.file.read_text() == token
    assert len(token) == 64
    directory = request_in.file.parent.lstat()
    assert stat.S_IMODE(directory.st_mode) == 0o711
    assert directory.st_uid == os.geteuid()
    assert os.listdir(request_in.file.parent) == [request_in.file.name]


def test_publish_adopts_an_existing_0711_directory(request_in: TokenRequest) -> None:
    request_in.file.parent.mkdir()
    request_in.file.parent.chmod(0o711)
    publish_token(new_token(), request_in)
    assert request_in.file.exists()


@pytest.mark.parametrize("planted", ["file", "temp"])
@pytest.mark.parametrize("kind", ["regular", "symlink"])
def test_publish_refuses_a_planted_entry(
    request_in: TokenRequest, tmp_path: Path, planted: str, kind: str
) -> None:
    publish_token(new_token(), TokenRequest(request_in.file.parent / "other", USER))
    path = (
        request_in.file
        if planted == "file"
        else request_in.file.parent / f".{request_in.file.name}.tmp"
    )
    target = tmp_path / "target"
    target.write_text("planted")
    if kind == "regular":
        path.write_text("planted")
    else:
        path.symlink_to(target)

    with pytest.raises(RuntimeError, match="already exists"):
        publish_token(new_token(), request_in)

    assert target.read_text() == "planted"
    assert path.is_symlink() if kind == "symlink" else path.read_text() == "planted"
    if planted == "temp":
        assert not request_in.file.exists()


def test_publish_refuses_a_symlinked_directory(
    request_in: TokenRequest, tmp_path: Path
) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o711)
    request_in.file.parent.symlink_to(real)
    with pytest.raises(RuntimeError, match="cannot be trusted"):
        publish_token(new_token(), request_in)
    assert os.listdir(real) == []


def test_publish_refuses_a_directory_with_another_mode(
    request_in: TokenRequest,
) -> None:
    request_in.file.parent.mkdir()
    request_in.file.parent.chmod(0o777)
    with pytest.raises(RuntimeError, match="not 0711"):
        publish_token(new_token(), request_in)
    assert stat.S_IMODE(request_in.file.parent.stat().st_mode) == 0o777


def test_publish_refuses_an_unknown_user(request_in: TokenRequest) -> None:
    with pytest.raises(RuntimeError, match="does not exist"):
        publish_token(new_token(), request_in._replace(user="no-such-user-x9"))
    assert not request_in.file.parent.exists()


def test_token_request_reads_the_environment() -> None:
    assert token_request({}) is None
    file = str(TOKEN_DIR / "proxy_abc")
    assert token_request({TOKEN_FILE_ENV: file, TOKEN_USER_ENV: "w-1"}) == (
        TokenRequest(TOKEN_DIR / "proxy_abc", "w-1")
    )
    with pytest.raises(RuntimeError, match="set together"):
        token_request({TOKEN_FILE_ENV: file})
    with pytest.raises(RuntimeError, match="set together"):
        token_request({TOKEN_USER_ENV: "w-1"})
    for outside in ["/tmp/proxy_abc", f"{TOKEN_DIR}/../proxy_abc", f"{TOKEN_DIR}/a/b"]:
        with pytest.raises(RuntimeError, match="not a plain name"):
            token_request({TOKEN_FILE_ENV: outside, TOKEN_USER_ENV: "w-1"})


async def test_on_listening_runs_once_the_listener_is_bound() -> None:
    server = AsyncHTTPServer(port=0)
    connected: list[bool] = []

    def on_listening() -> None:
        assert server.server is not None
        port = server.server.sockets[0].getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            connected.append(True)
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await server.start(on_listening=on_listening)
    assert connected == [True]


# ---------- requests to a served proxy ----------

GENERATION_ROUTES = [
    ("/v1/chat/completions", {"model": "inspect", "messages": []}),
    ("/v1/responses", {"model": "inspect", "input": "hello"}),
    ("/v1/messages", {"model": "inspect", "messages": [], "max_tokens": 1}),
    ("/v1beta/models/inspect:generateContent", {"contents": []}),
]
MCP_ROUTE = ("/mcp/tools", {"jsonrpc": "2.0", "id": 1, "method": "initialize"})


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _Proxy:
    def __init__(self, base_url: str, file: Path | None) -> None:
        self.base_url = base_url
        self.file = file
        self.service_headers: list[dict[str, str]] = []

    async def post(
        self, path: str, body: dict[str, Any], headers: dict[str, str]
    ) -> int:
        async with ClientSession() as session:
            async with session.post(
                f"{self.base_url}{path}", json=body, headers=headers
            ) as response:
                await response.read()
                return response.status


async def _serve(request: TokenRequest | None) -> AsyncIterator[_Proxy]:
    port = _free_port()
    proxy = _Proxy(f"http://127.0.0.1:{port}", request.file if request else None)

    async def call_model_service(_method: str, **params: Any) -> dict[str, Any]:
        proxy.service_headers.append(params.get("headers") or {})
        return {"id": "completion"}

    task = asyncio.create_task(serve_model_proxy(port, request, call_model_service))
    try:
        for _ in range(200):
            if task.done():
                task.result()
            ready = request.file.exists() if request else _accepts(port)
            if ready:
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("proxy did not start")
        yield proxy
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def _accepts(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture
async def scoped_proxy(request_in: TokenRequest) -> AsyncIterator[_Proxy]:
    async for proxy in _serve(request_in):
        yield proxy


@pytest.fixture
async def unscoped_proxy() -> AsyncIterator[_Proxy]:
    async for proxy in _serve(None):
        yield proxy


@pytest.mark.parametrize("route", [*GENERATION_ROUTES, MCP_ROUTE])
async def test_a_request_without_the_token_gets_401(
    scoped_proxy: _Proxy, route: tuple[str, dict[str, Any]]
) -> None:
    path, body = route
    wrong = new_token()
    for headers in [
        {},
        {"Authorization": f"Bearer {wrong}"},
        {"x-api-key": wrong},
        {"x-goog-api-key": wrong},
        {"Authorization": "Bearer sk-dummy"},
    ]:
        assert await scoped_proxy.post(path, body, headers) == 401
    assert scoped_proxy.service_headers == []


@pytest.mark.parametrize("route", [*GENERATION_ROUTES, MCP_ROUTE])
@pytest.mark.parametrize("header", ["authorization", "x-api-key", "x-goog-api-key"])
async def test_a_request_with_the_token_succeeds(
    scoped_proxy: _Proxy, route: tuple[str, dict[str, Any]], header: str
) -> None:
    path, body = route
    assert scoped_proxy.file is not None
    token = scoped_proxy.file.read_text()
    value = f"Bearer {token}" if header == "authorization" else token
    assert await scoped_proxy.post(path, body, {header: value}) == 200
    # the token is not passed on to the host
    for headers in scoped_proxy.service_headers:
        assert token not in str(headers)


async def test_the_token_file_is_removed_when_serving_ends(
    request_in: TokenRequest,
) -> None:
    async for _proxy in _serve(request_in):
        assert request_in.file.exists()
    assert not request_in.file.exists()


@pytest.mark.parametrize("route", [*GENERATION_ROUTES, MCP_ROUTE])
async def test_without_a_token_request_a_dummy_key_succeeds(
    unscoped_proxy: _Proxy, route: tuple[str, dict[str, Any]]
) -> None:
    path, body = route
    headers = {"Authorization": "Bearer sk-dummy", "x-api-key": "sk-dummy"}
    assert await unscoped_proxy.post(path, body, headers) == 200
