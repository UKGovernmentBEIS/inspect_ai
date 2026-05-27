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
