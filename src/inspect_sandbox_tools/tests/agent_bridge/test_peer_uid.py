"""The model proxy's check of the user that owns a client's socket."""

import asyncio
import errno
import json
import os
import pwd
import socket
import struct
import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from inspect_sandbox_tools._agent_bridge import peer_uid, proxy
from inspect_sandbox_tools._agent_bridge.peer_uid import (
    PeerCheck,
    PeerUser,
    check_connection,
    read_table,
    resolve_peer_user,
)
from inspect_sandbox_tools._agent_bridge.proxy import (
    LISTENING_PREFIX,
    AsyncHTTPServer,
    ProxyStartError,
)

linux_only = pytest.mark.skipif(
    sys.platform != "linux", reason="the peer check reads Linux's /proc/net/tcp"
)
little_endian = pytest.mark.skipif(
    sys.byteorder != "little", reason="the captured tables are little-endian"
)


def _has_ipv6_loopback() -> bool:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
            sock.bind(("::1", 0))
        return True
    except OSError:
        return False


ipv6_loopback = pytest.mark.skipif(not _has_ipv6_loopback(), reason="no IPv6 loopback")

# ============================================================================
# The row lookup, over captured tables
# ============================================================================

_HEADER = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when "
    "retrnsmt   uid  timeout inode\n"
)
# a client at 127.0.0.1:40000 connected to the proxy at 127.0.0.1:3001
_CLIENT4 = "0100007F:9C40"
_PROXY4 = "0100007F:0BB9"
# the same pair at ::1, in the kernel's word order on a little-endian host
_CLIENT6 = "00000000000000000000000001000000:9C40"
_PROXY6 = "00000000000000000000000001000000:0BB9"


def _row(local: str, remote: str, state: str, uid: int, inode: int) -> str:
    return (
        f"   0: {local} {remote} {state} 00000000:00000000 00:00000000 "
        f"00000000 {uid:>5}        0 {inode} 1 0000000000000000 20 4 30 10 -1\n"
    )


class _FakeSocket:
    """An accepted socket whose state and addresses the test sets."""

    def __init__(
        self,
        family: int = socket.AF_INET,
        local: tuple[Any, ...] = ("127.0.0.1", 3001),
        peer: tuple[Any, ...] = ("127.0.0.1", 40000),
        state: int = 1,
    ) -> None:
        self.family = family
        self.local = local
        self.peer = peer
        self.state = state
        self.on_lookup: Callable[[], None] = lambda: None

    def getsockname(self) -> tuple[Any, ...]:
        return self.local

    def getpeername(self) -> tuple[Any, ...]:
        if self.state == 7:
            raise OSError(errno.ENOTCONN, "Transport endpoint is not connected")
        return self.peer

    def getsockopt(self, level: int, option: int, buflen: int) -> bytes:
        assert level == socket.IPPROTO_TCP
        return bytes([self.state]) + bytes(buflen - 1)


class _Tables:
    """A table reader returning one captured table per read."""

    def __init__(self, *tables: str) -> None:
        self.tables = list(tables)
        self.reads: list[str] = []

    def __call__(self, path: str) -> str:
        self.reads.append(path)
        table = self.tables[min(len(self.reads), len(self.tables)) - 1]
        return _HEADER + table


_USER = PeerUser("w1", 1001)


@pytest.fixture(autouse=True)
def _tcp_info(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake sockets need no Linux; real ones run only there."""
    monkeypatch.setattr(peer_uid, "_TCP_INFO", getattr(socket, "TCP_INFO", 11))


def _check(sock: _FakeSocket, tables: _Tables) -> PeerCheck:
    return check_connection(sock, _USER, tables)


@little_endian
@pytest.mark.parametrize(
    "family,client,server,table",
    [
        (socket.AF_INET, _CLIENT4, _PROXY4, "/proc/net/tcp"),
        (socket.AF_INET6, _CLIENT6, _PROXY6, "/proc/net/tcp6"),
    ],
)
def test_one_live_socket_of_the_user_is_served(
    family: int, client: str, server: str, table: str
) -> None:
    host = "127.0.0.1" if family == socket.AF_INET else "::1"
    sock = _FakeSocket(family, (host, 3001), (host, 40000))
    rows = _row(client, server, "01", 1001, 77) + _row(server, client, "01", 0, 78)
    tables = _Tables(rows)
    assert _check(sock, tables) == PeerCheck("serve")
    assert tables.reads == [table]


@little_endian
def test_a_row_repeated_with_its_inode_is_one_socket() -> None:
    row = _row(_CLIENT4, _PROXY4, "01", 1001, 77)
    assert _check(_FakeSocket(), _Tables(row + row)) == PeerCheck("serve")


@little_endian
@pytest.mark.parametrize("uid", [1002, 0])
def test_another_uid_is_refused_without_a_reread(uid: int) -> None:
    tables = _Tables(_row(_CLIENT4, _PROXY4, "01", uid, 77))
    check = _check(_FakeSocket(), tables)
    assert check == PeerCheck(
        "refuse",
        "This model proxy serves only user 'w1' (uid 1001); this connection's "
        f"socket belongs to uid {uid}.",
    )
    assert len(tables.reads) == 1


@little_endian
@pytest.mark.parametrize(
    "rows",
    [
        "",
        _row(_CLIENT4, _PROXY4, "01", 1001, 77)
        + _row(_CLIENT4, _PROXY4, "01", 1001, 78),
    ],
    ids=["no-row", "two-sockets"],
)
def test_no_single_socket_is_refused_after_three_reads(rows: str) -> None:
    tables = _Tables(rows)
    check = _check(_FakeSocket(), tables)
    assert check == PeerCheck(
        "refuse",
        "This model proxy serves only user 'w1' (uid 1001); no single socket in "
        "/proc/net/tcp matched this connection (connect to localhost, 127.0.0.1 "
        "or ::1 from a socket of the same family).",
    )
    assert len(tables.reads) == 3


@little_endian
def test_a_row_found_on_a_reread_is_served() -> None:
    tables = _Tables("", _row(_CLIENT4, _PROXY4, "01", 1001, 77))
    assert _check(_FakeSocket(), tables) == PeerCheck("serve")
    assert len(tables.reads) == 2


@little_endian
@pytest.mark.parametrize("state", ["02", "06"], ids=["SYN_SENT", "TIME_WAIT"])
@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6])
def test_a_row_not_of_an_accepted_client_is_ignored(state: str, family: int) -> None:
    v6 = family == socket.AF_INET6
    client, server = (_CLIENT6, _PROXY6) if v6 else (_CLIENT4, _PROXY4)
    host = "::1" if v6 else "127.0.0.1"
    sock = _FakeSocket(family, (host, 3001), (host, 40000))
    stale = _row(client, server, state, 1001, 0 if state == "06" else 70)
    alone = _check(sock, _Tables(stale))
    assert alone.action == "refuse" and "no single socket" in (alone.reason or "")
    live = _row(client, server, "01", 1001, 77)
    other = _row(client, server, state, 1002, 0 if state == "06" else 71)
    assert _check(sock, _Tables(stale + other + live)) == PeerCheck("serve")


@little_endian
@pytest.mark.parametrize("state", ["04", "05"], ids=["FIN_WAIT1", "FIN_WAIT2"])
def test_a_client_that_shut_down_its_write_side_is_served(state: str) -> None:
    sock = _FakeSocket(state=8)  # the proxy's end is in CLOSE_WAIT
    assert _check(sock, _Tables(_row(_CLIENT4, _PROXY4, state, 1001, 77))) == (
        PeerCheck("serve")
    )


@little_endian
def test_the_lookup_uses_the_sockets_own_addresses() -> None:
    """Not the addresses asyncio cached at accept."""
    sock = _FakeSocket(peer=("127.0.0.1", 40001))
    rows = _row(_CLIENT4, _PROXY4, "01", 1001, 77)
    rows += _row("0100007F:9C41", _PROXY4, "01", 1002, 78)
    check = _check(sock, _Tables(rows))
    assert check.action == "refuse" and "belongs to uid 1002" in (check.reason or "")


@little_endian
@pytest.mark.parametrize(
    "change",
    ["closed", "moved"],
)
def test_a_connection_that_ended_during_the_lookup_is_closed_unread(
    change: str,
) -> None:
    sock = _FakeSocket()

    def end_connection(path: str) -> str:
        if change == "closed":
            sock.state = 7  # TCP_CLOSE: the client reset it
        else:
            sock.peer = ("127.0.0.1", 40001)
        return _HEADER + _row(_CLIENT4, _PROXY4, "01", 1001, 77)

    check = check_connection(sock, _USER, end_connection)
    assert check.action == "close"


def test_a_socket_whose_addresses_cannot_be_read_is_closed_unread() -> None:
    sock = _FakeSocket(state=7)
    check = _check(sock, _Tables(""))
    assert check.action == "close"


# ============================================================================
# Resolving the user at startup
# ============================================================================


def test_a_user_resolves_by_name_or_uid() -> None:
    entry = pwd.getpwuid(os.getuid())
    if entry.pw_uid in (0, 65534):
        pytest.skip("runs as a user the check refuses")
    assert resolve_peer_user(entry.pw_name) == PeerUser(entry.pw_name, entry.pw_uid)
    assert resolve_peer_user("61001") == PeerUser("61001", 61001)


@pytest.mark.parametrize(
    "user,message",
    [
        ("no-such-user-x", "does not exist"),
        ("0", "uid 0"),
        (pwd.getpwuid(0).pw_name, "uid 0"),
        ("65534", "uid 65534"),
        ("4294967295", "not a valid uid"),
    ],
)
def test_a_user_the_check_cannot_attribute_is_refused(user: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_peer_user(user)


# ============================================================================
# The proxy, with real sockets (Linux)
# ============================================================================

_OTHER = PeerUser("w2", os.getuid() + 1)
_OWN = PeerUser("me", os.getuid())


class _Recorded:
    def __init__(self) -> None:
        self.requests: list[str] = []


@asynccontextmanager
async def _proxy(
    user: PeerUser | None,
    read: Callable[[str], str] = read_table,
    port: int = 0,
) -> AsyncIterator[tuple[AsyncHTTPServer, _Recorded]]:
    """A proxy with stub routes that record the requests they get."""
    server = AsyncHTTPServer(port=port, peer_user=user, read_table=read)
    recorded = _Recorded()

    async def route(request: dict[str, Any]) -> dict[str, Any]:
        tag = request["json"]["tag"] if request["json"] else request["query"]["tag"][0]
        recorded.requests.append(tag)
        return {"status": 200, "body": {"ok": True}}

    server.add_route("/v1/chat/completions", route, method="POST")
    server.add_route("/mcp/*", route, method="POST")
    server.add_route("/v1/models", route, method="GET")
    task = asyncio.create_task(server.start())
    for _ in range(200):
        listening = server.servers if user is not None else [server.server]
        if all(s is not None and s.is_serving() for s in listening) and listening:
            break
        if task.done():
            task.result()
        await asyncio.sleep(0.01)
    if user is None and server.server is not None:
        server.port = server.server.sockets[0].getsockname()[1]
    try:
        yield server, recorded
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await server.stop()


def _get_bytes(tag: str) -> bytes:
    """A request with no body: asyncio serves one even from a reset connection."""
    return f"GET /v1/models?tag={tag} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()


def _request_bytes(tag: str, path: str = "/v1/chat/completions") -> bytes:
    body = json.dumps({"tag": tag}).encode()
    head = (
        f"POST {path} HTTP/1.1\r\nHost: localhost\r\n"
        f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
    )
    return head.encode() + body


def _parse(response: bytes) -> tuple[int, Any]:
    head, _, body = response.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1]) if head else 0
    return status, json.loads(body) if body else None


async def _post(
    host: str,
    port: int,
    tag: str,
    path: str = "/v1/chat/completions",
    family: int = 0,
) -> tuple[int, Any]:
    reader, writer = await asyncio.open_connection(host, port, family=family)
    try:
        writer.write(_request_bytes(tag, path))
        await writer.drain()
        return _parse(await reader.read())
    finally:
        writer.close()


async def _receive_all(sock: socket.socket) -> bytes:
    loop = asyncio.get_running_loop()
    sock.setblocking(False)
    data = b""
    while chunk := await loop.sock_recv(sock, 65536):
        data += chunk
    return data


@linux_only
@ipv6_loopback
async def test_the_proxy_serves_its_user_at_both_loopback_addresses() -> None:
    async with _proxy(_OWN) as (server, recorded):
        for host in ("127.0.0.1", "::1", "localhost"):
            assert await _post(host, server.port, host) == (200, {"ok": True})
        assert await _post("::1", server.port, "mcp", "/mcp/tools") == (
            200,
            {"ok": True},
        )
    assert recorded.requests == ["127.0.0.1", "::1", "localhost", "mcp"]


@linux_only
@ipv6_loopback
async def test_the_proxy_refuses_another_users_socket_on_every_route() -> None:
    async with _proxy(_OTHER) as (server, recorded):
        for host in ("127.0.0.1", "::1"):
            for path in ("/v1/chat/completions", "/mcp/tools"):
                status, body = await _post(host, server.port, "x", path)
                assert status == 403
                assert body == {
                    "error": {
                        "type": "permission_error",
                        "code": 403,
                        "message": (
                            f"This model proxy serves only user 'w2' (uid "
                            f"{_OTHER.uid}); this connection's socket belongs "
                            f"to uid {os.getuid()}."
                        ),
                    }
                }
        # an IPv6 socket reaching the IPv4 listener is listed in the other table
        status, body = await _post(
            "::ffff:127.0.0.1", server.port, "x", family=socket.AF_INET6
        )
        assert status == 403
        assert "no single socket in /proc/net/tcp matched" in body["error"]["message"]
    assert recorded.requests == []


@linux_only
async def test_a_proxy_given_no_user_serves_any_client_on_ipv4_only() -> None:
    async with _proxy(None) as (server, recorded):
        assert server.servers == []
        assert await _post("127.0.0.1", server.port, "any") == (200, {"ok": True})
        with pytest.raises(OSError):
            await _post("::1", server.port, "v6", family=socket.AF_INET6)
    assert recorded.requests == ["any"]


@linux_only
@pytest.mark.parametrize(
    "family,host",
    [
        (socket.AF_INET, "127.0.0.1"),
        pytest.param(socket.AF_INET6, "::1", marks=ipv6_loopback),
    ],
)
async def test_a_retired_connection_is_closed_unanswered(
    family: int, host: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A request whose client reset its connection is not served as a later one's.

    The table reader, on its first read, resets the first client's connection
    and connects again from the same address pair, so the row it then reads
    belongs to the second connection, which this test's uid also owns. The
    proxy must close the first connection without reading it: whether its
    request could still be read after the reset depends on the kernel.
    """
    first = socket.socket(family, socket.SOCK_STREAM)
    second: list[socket.socket] = []

    def reset_and_reconnect(path: str) -> str:
        if not second:
            address = first.getsockname()[:2]
            first.setsockopt(
                socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
            )
            first.close()
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(address)
            sock.connect((host, port))
            sock.sendall(_get_bytes("second"))
            second.append(sock)
        return read_table(path)

    async with _proxy(_OWN, reset_and_reconnect) as (server, recorded):
        port = server.port
        first.bind((host, 0))
        first.connect((host, port))
        first.sendall(_get_bytes("first"))
        response = await asyncio.wait_for(_receive_all_when(second), timeout=10)
        assert _parse(response) == (200, {"ok": True})
    assert recorded.requests == ["second"]
    closed = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("connection closed unread: the connection ended")
    ]
    assert len(closed) == 1


async def _receive_all_when(second: list[socket.socket]) -> bytes:
    while not second:
        await asyncio.sleep(0.01)
    try:
        return await _receive_all(second[0])
    finally:
        second[0].close()


@linux_only
async def test_a_client_that_shuts_down_its_write_side_is_answered() -> None:
    async with _proxy(_OWN) as (server, recorded):
        sock = socket.create_connection(("127.0.0.1", server.port))
        sock.sendall(_request_bytes("half-closed"))
        sock.shutdown(socket.SHUT_WR)
        try:
            response = await asyncio.wait_for(_receive_all(sock), timeout=10)
        finally:
            sock.close()
    assert _parse(response) == (200, {"ok": True})
    assert recorded.requests == ["half-closed"]


class _Stdout:
    """Records each write, and whether both loopback ports were then held."""

    def __init__(self, port: Callable[[], int]) -> None:
        self.port = port
        self.lines: list[tuple[str, bool]] = []
        self.flushed = False

    def write(self, text: str) -> int:
        if text.strip():
            self.lines.append(
                (text, _held("127.0.0.1", self.port()) and _held("::1", self.port()))
            )
        return len(text)

    def flush(self) -> None:
        self.flushed = bool(self.lines)


def _held(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as ex:
            return ex.errno == errno.EADDRINUSE
        return False


@linux_only
@ipv6_loopback
async def test_the_listening_line_follows_both_binds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder: list[AsyncHTTPServer] = []
    stdout = _Stdout(lambda: holder[0].port)
    monkeypatch.setattr(sys, "stdout", stdout)
    server = AsyncHTTPServer(port=0, peer_user=_OWN)
    holder.append(server)
    task = asyncio.create_task(server.start())
    try:
        while not stdout.lines:
            await asyncio.sleep(0.01)
        reuseport = [
            s.sockets[0].getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT)
            for s in server.servers
        ]
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await server.stop()
    line, both_held = stdout.lines[0]
    assert line == (
        f"{LISTENING_PREFIX}127.0.0.1:{server.port} and [::1]:{server.port} "
        f"for uid {_OWN.uid}"
    )
    assert both_held and stdout.flushed
    assert reuseport == [0, 0]


@linux_only
@pytest.mark.parametrize(
    "held",
    ["127.0.0.1", pytest.param("::1", marks=ipv6_loopback)],
)
async def test_a_taken_loopback_address_stops_the_proxy(held: str) -> None:
    family = socket.AF_INET6 if held == "::1" else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as other:
        other.bind((held, 0))
        other.listen()
        port = other.getsockname()[1]
        server = AsyncHTTPServer(port=port, peer_user=_OWN)
        with pytest.raises(ProxyStartError) as excinfo:
            await server.start()
    display = f"[{held}]:{port}" if family == socket.AF_INET6 else f"{held}:{port}"
    assert excinfo.value.errno == errno.EADDRINUSE
    assert f"cannot listen on {display}" in str(excinfo.value)


@linux_only
@pytest.mark.parametrize(
    "code", [errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT, errno.EACCES]
)
async def test_an_unavailable_ipv6_loopback_leaves_ipv4(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    listen = proxy._listen

    def no_ipv6(family: socket.AddressFamily, host: str, port: int) -> socket.socket:
        if family == socket.AF_INET6:
            raise ProxyStartError(code, f"cannot listen on [::1]:{port}: injected")
        return listen(family, host, port)

    monkeypatch.setattr(proxy, "_listen", no_ipv6)
    lines: list[str] = []
    monkeypatch.setattr(
        proxy, "print", lambda line, **kwargs: lines.append(line), raising=False
    )
    if code == errno.EACCES:
        with pytest.raises(ProxyStartError, match="injected"):
            await AsyncHTTPServer(port=0, peer_user=_OWN).start()
        return
    async with _proxy(_OWN) as (server, recorded):
        assert len(server.servers) == 1
        assert await _post("127.0.0.1", server.port, "v4") == (200, {"ok": True})
    assert lines[0] == (
        f"{LISTENING_PREFIX}127.0.0.1:{server.port}, no IPv6 loopback, "
        f"for uid {_OWN.uid}"
    )


_RUN_PROXY = (
    "import asyncio\n"
    "from inspect_sandbox_tools._agent_bridge.proxy import run_model_proxy_server\n"
    "asyncio.run(run_model_proxy_server())\n"
)


def _run_proxy(port: int, user: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "BRIDGE_MODEL_SERVICE_PORT": str(port),
        "BRIDGE_MODEL_SERVICE_PEER_USER": user,
    }
    return subprocess.run(
        [sys.executable, "-c", _RUN_PROXY],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@linux_only
@pytest.mark.parametrize("user", ["no-such-user-x", "0", "65534"])
def test_the_proxy_exits_before_binding_for_a_user_it_cannot_serve(user: str) -> None:
    result = _run_proxy(_free_port(), user)
    assert result.returncode == 1
    assert result.stderr.startswith("model_proxy: ")
    assert LISTENING_PREFIX not in result.stdout


@linux_only
@ipv6_loopback
def test_the_proxy_exits_naming_a_taken_address() -> None:
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as other:
        other.bind(("::1", 0))
        other.listen()
        port = other.getsockname()[1]
        result = _run_proxy(port, str(os.getuid()))
    assert result.returncode == 1
    assert f"cannot listen on [::1]:{port}" in result.stderr
    assert LISTENING_PREFIX not in result.stdout
