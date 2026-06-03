"""Unit tests for :mod:`inspect_ai._util.sockets`."""

import sys

import pytest

from inspect_ai._util.sockets import has_unix_sockets, parse_host_port

# ---------------------------------------------------------------------------
# has_unix_sockets
# ---------------------------------------------------------------------------


def test_has_unix_sockets_on_posix_returns_true() -> None:
    """Every supported POSIX platform exposes AF_UNIX."""
    if sys.platform == "win32":
        pytest.skip("POSIX-only assertion")
    assert has_unix_sockets() is True


def test_has_unix_sockets_returns_bool() -> None:
    """Whatever platform we're on, the return is a bool."""
    assert isinstance(has_unix_sockets(), bool)


# ---------------------------------------------------------------------------
# parse_host_port — valid host:port shapes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0.0.0.0:4444", ("0.0.0.0", 4444)),
        ("127.0.0.1:8000", ("127.0.0.1", 8000)),
        ("localhost:8080", ("localhost", 8080)),
        ("example.com:80", ("example.com", 80)),
        ("[::1]:4444", ("::1", 4444)),
        ("[2001:db8::1]:9999", ("2001:db8::1", 9999)),
        ("host:0", ("host", 0)),  # 0 is technically in-range
        ("host:65535", ("host", 65535)),  # upper boundary
    ],
)
def test_parse_host_port_valid(value: str, expected: tuple[str, int]) -> None:
    """Valid ``host:port`` shapes parse cleanly, including IPv6 brackets."""
    assert parse_host_port(value) == expected


# ---------------------------------------------------------------------------
# parse_host_port — not a network address (returns None for path fallback)
# ---------------------------------------------------------------------------


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

    The caller falls back to treating the value as a UNIX socket path.
    Ambiguous inputs intentionally err on the side of UNIX so a
    user-supplied path with a colon isn't silently misrouted to TCP.
    """
    assert parse_host_port(value) is None


# ---------------------------------------------------------------------------
# parse_host_port — port out of range raises
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "127.0.0.1:65536",  # one past upper bound
        "127.0.0.1:99999",
        "127.0.0.1:-1",  # negative
        "[::1]:65536",  # IPv6 too
    ],
)
def test_parse_host_port_out_of_range_raises(value: str) -> None:
    """Syntactically host:port but port outside ``[0, 65535]`` raises ValueError.

    Falling through to UNIX-path interpretation in that case would
    silently bind/connect to a literal path like ``"127.0.0.1:99999"``
    — misleading and harder to diagnose than a clean error.
    """
    with pytest.raises(ValueError, match="port out of range"):
        parse_host_port(value)


# ---------------------------------------------------------------------------
# prepare_socket_path / lock_socket_file
# ---------------------------------------------------------------------------


def test_prepare_socket_path_creates_parent(tmp_path) -> None:
    from inspect_ai._util.sockets import prepare_socket_path

    path = tmp_path / "a" / "b" / "ctl.sock"
    prepare_socket_path(path)
    assert path.parent.is_dir()


def test_prepare_socket_path_unlinks_stale_socket(tmp_path) -> None:
    import socket

    from inspect_ai._util.sockets import prepare_socket_path

    path = tmp_path / "stale.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(path))
        assert path.exists()
        prepare_socket_path(path)  # leftover socket node -> removed
        assert not path.exists()
    finally:
        sock.close()


def test_prepare_socket_path_refuses_non_socket(tmp_path) -> None:
    from inspect_ai._util.sockets import prepare_socket_path

    path = tmp_path / "important.txt"
    path.write_text("do not delete me")
    with pytest.raises(RuntimeError, match="not a socket"):
        prepare_socket_path(path)
    assert path.read_text() == "do not delete me"  # untouched


def test_lock_socket_file_sets_owner_only_mode(tmp_path) -> None:
    import stat

    from inspect_ai._util.sockets import SOCKET_FILE_MODE, lock_socket_file

    path = tmp_path / "f.sock"
    path.write_bytes(b"")
    path.chmod(0o644)
    lock_socket_file(path)
    assert stat.S_IMODE(path.stat().st_mode) == SOCKET_FILE_MODE


def test_lock_socket_file_missing_path_is_noop(tmp_path) -> None:
    from inspect_ai._util.sockets import lock_socket_file

    # best-effort: a missing path must not raise
    lock_socket_file(tmp_path / "nope.sock")
