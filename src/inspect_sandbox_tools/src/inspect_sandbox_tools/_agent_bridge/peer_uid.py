"""Which user owns the client end of a connection to the model proxy.

Inside a sandbox identity scope the model proxy serves only connections whose
client socket the scope's user owns. The kernel lists every TCP socket with its
owner's uid in `/proc/net/tcp` (IPv4) and `/proc/net/tcp6` (IPv6), and no
unprivileged process can create a socket owned by another uid. Linux only.
"""

import pwd
import re
import socket
import struct
from typing import Any, Callable, Literal, NamedTuple

PEER_USER_ENV = "BRIDGE_MODEL_SERVICE_PEER_USER"
"""Variable naming the user the proxy serves (inspect_ai's bridge sets it)."""

TableReader = Callable[[str], str]
"""Reads a socket table, given its path."""

TCP_TABLES = {socket.AF_INET: "/proc/net/tcp", socket.AF_INET6: "/proc/net/tcp6"}

_UNATTRIBUTED_UIDS = frozenset({0, 65534})
"""Uids the socket table reports for sockets whose owner it cannot attribute."""

_MAX_UID = 0xFFFFFFFE
_UID = re.compile(r"[0-9]+")

_CLIENT_STATES = frozenset({"01", "04", "05"})
"""ESTABLISHED, FIN_WAIT1 and FIN_WAIT2: a client end whose connection was accepted."""

_READS = 3
"""Reads of the table before a connection with no single matching socket is refused."""

_TCP_INFO: int | None = getattr(socket, "TCP_INFO", None)
_TCP_ESTABLISHED = 1
_TCP_CLOSE_WAIT = 8


class PeerUser(NamedTuple):
    """The user the proxy serves."""

    name: str
    uid: int


class PeerCheck(NamedTuple):
    """What to do with a connection."""

    action: Literal["serve", "refuse", "close"]
    """Serve it; answer it with HTTP 403; or close it unread, with no response."""

    reason: str | None = None
    """The 403 message, or why the connection was closed."""


def resolve_peer_user(user: str) -> PeerUser:
    """Resolve the user the proxy serves, before the proxy binds.

    A name is looked up in the sandbox's passwd database; an all-digit user is
    that uid. Uids 0 and 65534 are refused: the socket table reports them for
    sockets whose owner it cannot attribute.

    Raises:
        ValueError: The user does not resolve, is uid 0 or 65534, or the
            platform has no TCP socket table.
    """
    if _TCP_INFO is None:
        raise ValueError("The model proxy's peer check needs Linux.")
    if _UID.fullmatch(user):
        uid = int(user)
        if uid > _MAX_UID:
            raise ValueError(f"The model proxy's user '{user}' is not a valid uid.")
    else:
        try:
            uid = pwd.getpwnam(user).pw_uid
        except KeyError:
            raise ValueError(
                f"The model proxy's user '{user}' does not exist."
            ) from None
    if uid in _UNATTRIBUTED_UIDS:
        raise ValueError(
            f"The model proxy cannot serve only user '{user}' (uid {uid}): the "
            f"socket table reports uid {uid} for sockets it cannot attribute."
        )
    return PeerUser(user, uid)


def read_table(path: str) -> str:
    """Read a socket table."""
    with open(path) as file:
        return file.read()


def check_connection(
    sock: Any, user: PeerUser, read: TableReader = read_table
) -> PeerCheck:
    """Decide whether to serve an accepted connection, before reading from it.

    The connection's addresses are queried from the accepted socket itself, not
    taken from those cached at accept. The socket table of its family must then
    list exactly one live client socket from the connection's peer address to
    its local address, owned by `user`. Finally the socket is queried again:
    a connection the client has already reset can leave its address pair to a
    later connection, whose row would then be the one looked up. It must still
    be connected (`ESTABLISHED`, or `CLOSE_WAIT` after the client shut down its
    write side) at the same addresses; a closed connection never reconnects,
    so the row matched was its own client's.

    Args:
        sock: The accepted socket (`socket.socket` or asyncio's wrapper).
        user: The user the proxy serves.
        read: Reads a socket table, given its path.
    """
    try:
        local = sock.getsockname()
        peer = sock.getpeername()
    except OSError as ex:
        return PeerCheck("close", f"cannot read the connection's addresses: {ex}")

    table = TCP_TABLES[sock.family]
    uid = _lookup_uid(
        read, table, _row_address(sock.family, peer), _row_address(sock.family, local)
    )
    if uid is None:
        return PeerCheck(
            "refuse",
            f"{_serves_only(user)}; no single socket in {table} matched this "
            "connection (connect to localhost, 127.0.0.1 or ::1 from a socket "
            "of the same family).",
        )
    if uid != user.uid:
        return PeerCheck(
            "refuse",
            f"{_serves_only(user)}; this connection's socket belongs to uid {uid}.",
        )

    assert _TCP_INFO is not None
    try:
        state = sock.getsockopt(socket.IPPROTO_TCP, _TCP_INFO, 8)[0]
        same = sock.getsockname() == local and sock.getpeername() == peer
    except OSError as ex:
        return PeerCheck("close", f"the connection ended during the check: {ex}")
    if state not in (_TCP_ESTABLISHED, _TCP_CLOSE_WAIT) or not same:
        return PeerCheck(
            "close", f"the connection ended during the check (state {state})"
        )
    return PeerCheck("serve")


def _lookup_uid(read: TableReader, table: str, client: str, server: str) -> int | None:
    """The uid of the one live client socket from `client` to `server`, if any.

    The kernel writes the table without a snapshot, so a live row can be
    skipped or repeated while other sockets open and close: no row, or more
    than one socket, is read again before giving up. Rows with the same inode
    are one socket.
    """
    for _ in range(_READS):
        sockets: dict[str, int] = {}
        for line in read(table).splitlines()[1:]:
            fields = line.split()
            if (
                len(fields) >= 10
                and fields[1].upper() == client
                and fields[2].upper() == server
                and fields[3] in _CLIENT_STATES
            ):
                sockets[fields[9]] = int(fields[7])
        if len(sockets) == 1:
            return next(iter(sockets.values()))
    return None


def _row_address(family: int, address: tuple[Any, ...]) -> str:
    """An address as the socket table prints it.

    Each 32-bit word of the address in the host's byte order, as 8 hex digits,
    then the port as 4: `0100007F:0BB9` is `127.0.0.1:3001` on a little-endian
    host.
    """
    packed = socket.inet_pton(family, address[0])
    words = struct.unpack(f"={len(packed) // 4}I", packed)
    return "".join(f"{word:08X}" for word in words) + f":{address[1]:04X}"


def _serves_only(user: PeerUser) -> str:
    return f"This model proxy serves only user '{user.name}' (uid {user.uid})"
