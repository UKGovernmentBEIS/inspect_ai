"""Phase 8 tests for the ACP JSON-RPC transport server.

Covers the :func:`acp_server` async context manager + the
:class:`_AcpServer` lifecycle: bind, accept, dispatch (empty router),
discovery file management, stale cleanup, and the AF_UNIX-on-old-Win
guardrail.
"""

import asyncio
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp._discovery import (
    _cleanup_stale_discovery_files,
    _parse_host_port,
    _pid_alive,
)
from inspect_ai.agent._acp._server import acp_server


def _read_discovery(path: Path) -> dict[str, object]:
    return dict(json.loads(path.read_text()))


@pytest.fixture
def short_data_dir(monkeypatch):
    """A short data directory under /tmp so AF_UNIX paths fit in 104 chars.

    macOS pytest tmp_path is buried in ``/private/var/folders/...`` which
    blows past the AF_UNIX path limit (104 on macOS, 108 on Linux). Use
    ``/tmp/<short>`` instead and clean up at teardown.
    """
    dirpath = Path(tempfile.mkdtemp(prefix="acp_", dir="/tmp"))

    def _stub_data_dir(subdir: str | None) -> Path:
        # Mirror the real ``inspect_data_dir`` contract: create the
        # subdirectory on demand and return its resolved path.
        path = (dirpath / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(
        "inspect_ai.agent._acp._discovery.inspect_data_dir",
        _stub_data_dir,
    )
    try:
        yield dirpath
    finally:
        # Best-effort cleanup; servers normally remove their own files
        # but leave the dir for inspection on failure.
        for p in dirpath.rglob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            for sub in sorted(dirpath.rglob("*"), reverse=True):
                if sub.is_dir():
                    sub.rmdir()
            dirpath.rmdir()
        except OSError:
            pass


def _free_port() -> int:
    """Pick a free TCP port by binding to 0 then closing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Disabled / no-op
# ---------------------------------------------------------------------------


async def test_disabled_transport_yields_none() -> None:
    """``acp_server(transport=None)`` is a no-op — yields None, binds nothing."""
    async with acp_server(eval_id="t1", transport=None) as server:
        assert server is None


@pytest.mark.parametrize("falsy", [False, 0, ""])
async def test_falsy_transport_yields_none(falsy: bool | int | str) -> None:
    """Any falsy transport (False, 0, '') skips binding entirely."""
    async with acp_server(eval_id="t1", transport=falsy) as server:
        assert server is None


# ---------------------------------------------------------------------------
# AF_UNIX binding
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "start_unix_server"),
    reason="AF_UNIX sockets not available on this Windows build.",
)
async def test_unix_default_socket_path(short_data_dir: Path) -> None:
    """``transport=True`` binds AF_UNIX at <data>/acp/<eval_id>.sock.

    Both the socket file and the discovery JSON exist while the context
    is open; both are removed on exit.
    """
    eval_id = "evt-abc"
    expected_socket = (short_data_dir / "acp" / f"{eval_id}.sock").resolve()
    async with acp_server(eval_id=eval_id, transport=True) as server:
        assert server is not None
        assert server.socket_path == expected_socket
        assert server.port is None
        assert server.socket_path.exists()
        assert server.discovery_path is not None
        assert server.discovery_path.exists()
        data = _read_discovery(server.discovery_path)
        assert data["eval_id"] == eval_id
        assert data["pid"] == os.getpid()
        assert data["socket_path"] == str(server.socket_path)
        assert data["port"] is None
        assert data["host"] is None
    # After exit: both removed.
    assert not expected_socket.exists()
    assert not (short_data_dir / "acp" / f"{os.getpid()}.json").exists()


@skip_if_trio
@pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "start_unix_server"),
    reason="AF_UNIX sockets not available on this Windows build.",
)
async def test_unix_custom_socket_path(short_data_dir: Path) -> None:
    """A string transport is taken as a literal AF_UNIX path."""
    custom = short_data_dir / "custom.sock"
    async with acp_server(eval_id="evt-2", transport=str(custom)) as server:
        assert server is not None
        assert server.socket_path == custom
        assert custom.exists()


@skip_if_trio
@pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "start_unix_server"),
    reason="AF_UNIX sockets not available on this Windows build.",
)
async def test_unix_bind_refuses_to_clobber_non_socket(
    short_data_dir: Path,
) -> None:
    """If the user's custom path exists and is a regular file, refuse to bind.

    Guards against data loss when ``--acp-server=/important/file`` is
    typed by mistake. The server should error rather than unlink the
    existing file as part of stale-socket cleanup.
    """
    target = short_data_dir / "not_a_socket.txt"
    target.write_text("precious user data")
    with pytest.raises(RuntimeError, match="not a socket"):
        async with acp_server(eval_id="evt-clobber", transport=str(target)):
            pass
    assert target.exists()
    assert target.read_text() == "precious user data"


# ---------------------------------------------------------------------------
# TCP binding
# ---------------------------------------------------------------------------


@skip_if_trio
async def test_tcp_loopback_bind(short_data_dir: Path) -> None:
    """``transport=<int>`` binds TCP on 127.0.0.1; no socket file is left behind."""
    port = _free_port()
    async with acp_server(eval_id="evt-tcp", transport=port) as server:
        assert server is not None
        assert server.socket_path is None
        assert server.port == port
        assert server.host == "127.0.0.1"
        assert server.discovery_path is not None
        data = _read_discovery(server.discovery_path)
        assert data["port"] == port
        assert data["host"] == "127.0.0.1"
        assert data["socket_path"] is None
        # Verify a real connect succeeds.
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


@skip_if_trio
async def test_tcp_host_port_bind(short_data_dir: Path) -> None:
    """``transport='host:port'`` binds TCP on the supplied interface.

    Uses ``0.0.0.0:<port>`` to verify the host parameter is honored;
    the actual interface bound is reflected in ``server.host`` and the
    discovery JSON, so clients enumerating discovery files know which
    address to dial.
    """
    port = _free_port()
    target = f"0.0.0.0:{port}"
    async with acp_server(eval_id="evt-host-port", transport=target) as server:
        assert server is not None
        assert server.socket_path is None
        assert server.port == port
        assert server.host == "0.0.0.0"
        data = _read_discovery(server.discovery_path)  # type: ignore[arg-type]
        assert data["host"] == "0.0.0.0"
        assert data["port"] == port
        # Bound on 0.0.0.0 so localhost connect succeeds.
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0.0.0.0:4444", ("0.0.0.0", 4444)),
        ("127.0.0.1:8000", ("127.0.0.1", 8000)),
        ("localhost:8080", ("localhost", 8080)),
        ("[::1]:4444", ("::1", 4444)),
        ("[2001:db8::1]:9999", ("2001:db8::1", 9999)),
    ],
)
def test_parse_host_port_valid(value: str, expected: tuple[str, int]) -> None:
    """Valid ``host:port`` shapes parse cleanly, including IPv6 brackets."""
    assert _parse_host_port(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        # Plain socket paths.
        "/tmp/foo.sock",
        "./relative/path",
        "C:\\windows\\path",
        # Path-like with colon: still a path, not a network address.
        "/var/run/app:foo.sock",
        # Malformed network addresses.
        "no_colon_at_all",
        ":4444",  # missing host
        "host:",  # missing port
        "host:not_a_number",
        "[unclosed_bracket",
        "[empty]:not_a_port",
        # Empty / falsy.
        "",
    ],
)
def test_parse_host_port_not_a_network_address(value: str) -> None:
    """Anything that doesn't unambiguously look like host:port returns None.

    The caller then falls back to treating the value as a UNIX socket
    path. Ambiguous inputs intentionally err on the side of UNIX so a
    user-supplied path with a colon isn't silently misrouted to TCP.
    """
    assert _parse_host_port(value) is None


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "start_unix_server"),
    reason="AF_UNIX sockets not available on this Windows build.",
)
async def test_unknown_method_returns_method_not_found(
    short_data_dir: Path,
) -> None:
    """A method outside the ACP surface returns JSON-RPC `method not found`.

    Phase 9 implements the picker handlers (initialize, session/new,
    session/load, session/prompt, session/cancel); everything else
    (including unimplemented ACP methods like session/fork and
    completely-bogus methods) still surfaces ``method not found`` so
    the transport contract holds.
    """
    async with acp_server(eval_id="evt-conn", transport=True) as server:
        assert server is not None and server.socket_path is not None
        reader, writer = await asyncio.open_unix_connection(str(server.socket_path))
        try:
            request = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "definitely/not/a/method",
                        "params": {},
                    }
                ).encode("utf-8")
                + b"\n"
            )
            writer.write(request)
            await writer.drain()
            response_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            response = json.loads(response_line)
            assert response["id"] == 1
            assert "error" in response
            # JSON-RPC 2.0 method-not-found code is -32601.
            assert response["error"]["code"] == -32601
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Discovery cleanup
# ---------------------------------------------------------------------------


def test_pid_alive_for_current_process() -> None:
    """The current PID is always alive."""
    assert _pid_alive(os.getpid()) is True


def test_pid_alive_for_invalid_pid() -> None:
    """A PID we know to be invalid returns False."""
    assert _pid_alive(0) is False
    assert _pid_alive(-1) is False


def test_cleanup_stale_discovery_files(short_data_dir: Path) -> None:
    """A discovery file with a dead PID is removed; orphan socket too."""
    acp_dir = short_data_dir / "acp"
    acp_dir.mkdir(parents=True, exist_ok=True)
    # Stale entry: PID guaranteed-dead (1 might be init on POSIX, use a
    # huge sentinel that is essentially never assigned).
    stale_sock = acp_dir / "stale.sock"
    stale_sock.touch()
    stale_discovery = acp_dir / "999999.json"
    stale_discovery.write_text(
        json.dumps(
            {
                "pid": 999999,
                "eval_id": "old",
                "socket_path": str(stale_sock),
                "port": None,
                "started_at": 0,
            }
        )
    )
    # Live entry: our own PID; must NOT be removed.
    live_discovery = acp_dir / f"{os.getpid()}.json"
    live_discovery.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "eval_id": "live",
                "socket_path": None,
                "port": 12345,
                "started_at": 0,
            }
        )
    )

    _cleanup_stale_discovery_files()

    assert not stale_discovery.exists()
    assert not stale_sock.exists()
    assert live_discovery.exists()


def test_cleanup_tolerates_malformed_files(short_data_dir: Path) -> None:
    """Bogus or unreadable discovery files are skipped silently."""
    acp_dir = short_data_dir / "acp"
    acp_dir.mkdir(parents=True, exist_ok=True)
    (acp_dir / "garbage.json").write_text("{not valid json")
    (acp_dir / "missing-pid.json").write_text(json.dumps({"socket_path": "/foo"}))
    # Should not raise.
    _cleanup_stale_discovery_files()
    # Malformed files left alone (best-effort policy — we only delete
    # entries we can positively identify as stale).
    assert (acp_dir / "garbage.json").exists()
    assert (acp_dir / "missing-pid.json").exists()


@skip_if_trio
@pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "start_unix_server"),
    reason="AF_UNIX sockets not available on this Windows build.",
)
async def test_start_cleans_up_stale_before_binding(
    short_data_dir: Path,
) -> None:
    """``_AcpServer.start`` clears stale discovery files before writing its own."""
    acp_dir = short_data_dir / "acp"
    acp_dir.mkdir(parents=True, exist_ok=True)
    stale = acp_dir / "888888.json"
    stale.write_text(
        json.dumps({"pid": 888888, "eval_id": "old", "socket_path": None, "port": None})
    )
    async with acp_server(eval_id="evt-c", transport=True):
        # While our server is running the stale entry should be gone.
        assert not stale.exists()


# ---------------------------------------------------------------------------
# Multi-connection isolation
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "start_unix_server"),
    reason="AF_UNIX sockets not available on this Windows build.",
)
async def test_multi_connection_isolation(short_data_dir: Path) -> None:
    """Two simultaneous connections each get their own dispatch cycle."""
    async with acp_server(eval_id="evt-multi", transport=True) as server:
        assert server is not None and server.socket_path is not None
        r1, w1 = await asyncio.open_unix_connection(str(server.socket_path))
        r2, w2 = await asyncio.open_unix_connection(str(server.socket_path))
        try:
            for i, w in [(1, w1), (2, w2)]:
                req = (
                    json.dumps(
                        {"jsonrpc": "2.0", "id": i, "method": "foo", "params": None}
                    ).encode("utf-8")
                    + b"\n"
                )
                w.write(req)
                await w.drain()
            resp1 = json.loads(await asyncio.wait_for(r1.readline(), 5.0))
            resp2 = json.loads(await asyncio.wait_for(r2.readline(), 5.0))
            # Each connection sees its own response id (not the other's).
            assert resp1["id"] == 1
            assert resp2["id"] == 2
            assert "error" in resp1 and "error" in resp2
        finally:
            for w in (w1, w2):
                w.close()
                try:
                    await w.wait_closed()
                except Exception:
                    pass
