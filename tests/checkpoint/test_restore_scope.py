"""Unit tests for the restore scope/structure checks (``_restore_scope``).

Pure checks over node descriptions — no restic, tar, or sandbox: which
paths a restore may write, which node kinds and modes are refused, how
restic's Go-layout modes and tar members map onto nodes, and the
per-root restic restore arguments.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from inspect_ai.util._checkpoint import _restore_scope as restore_scope
from inspect_ai.util._checkpoint._layout.schemas import SnapshotDetails
from inspect_ai.util._checkpoint._restore_scope import (
    MAX_LONG_HEADER_BYTES,
    MAX_RESTORE_NODES,
    RestoreNode,
    RestoreRoots,
    RestoreScopeError,
    TarHeaderScan,
    check_recorded_roots,
    find_special_nodes_command,
    recorded_roots,
    remove_existing_symlinks,
    remove_existing_symlinks_command,
    restic_node,
    restic_restore_args,
    tar_member_argument,
    tar_member_node,
)
from inspect_ai.util._sandbox._privileged import pinned_shell_command

LABEL = "test restore"
HOME = RestoreRoots.from_include(["/home/user"], label=LABEL)


def _node(path: str, kind: str = "file", mode: int = 0o644) -> RestoreNode:
    return RestoreNode(path=path, kind=kind, mode=mode)


# --- roots -----------------------------------------------------------------


def test_roots_normalize_and_dedupe() -> None:
    roots = RestoreRoots.from_include(
        ["/data/", "/home//user", "/data", "/opt/./x"], label=LABEL
    )
    assert roots.roots == ("/data", "/home/user", "/opt/x")


def test_nested_roots_collapse_to_the_outermost() -> None:
    """``/data`` covers ``/data/sub``; every node under it is credited to ``/data``."""
    roots = RestoreRoots.from_include(["/data/sub", "/data", "/datax"], label=LABEL)
    assert roots.roots == ("/data", "/datax")
    walk = roots.walker(label=LABEL)
    for p in ("/data", "/data/sub/x", "/datax/y"):
        walk.visit(_node(p))
    walk.finish()


def test_walk_node_count_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(restore_scope, "MAX_RESTORE_NODES", 3)
    walk = HOME.walker(label=LABEL)
    for i in range(3):
        walk.visit(_node(f"/home/user/{i}"))
    with pytest.raises(RestoreScopeError, match="more than 3 nodes"):
        walk.visit(_node("/home/user/3"))
    assert MAX_RESTORE_NODES > 3  # the real cap is generous


@pytest.mark.parametrize(
    "include,match",
    [
        (["/"], "cannot be scoped"),
        (["/data", "/"], "cannot be scoped"),
        (["relative/path"], "not an absolute path"),
        ([], "include set is empty"),
    ],
)
def test_roots_refuse_unscopable_include(include: list[str], match: str) -> None:
    with pytest.raises(RestoreScopeError, match=match):
        RestoreRoots.from_include(include, label=LABEL)


# --- node checks -----------------------------------------------------------


def test_nodes_under_a_root_pass_and_report_their_root() -> None:
    roots = RestoreRoots.from_include(["/home/user", "/data"], label=LABEL)
    assert roots.check_node(_node("/home/user"), label=LABEL) == "/home/user"
    assert roots.check_node(_node("/home/user/a/b.txt"), label=LABEL) == "/home/user"
    assert roots.check_node(_node("/data/db", "dir", 0o755), label=LABEL) == "/data"
    assert (
        roots.check_node(_node("/home/user/link", "symlink", 0o777), label=LABEL)
        == "/home/user"
    )


def test_ancestor_directories_pass_without_mode_check() -> None:
    """``/`` and ``/tmp``-style ancestors are listed by every tool; sticky is fine there."""
    roots = RestoreRoots.from_include(["/tmp/work"], label=LABEL)
    assert roots.check_node(_node("/tmp", "dir", 0o1777), label=LABEL) is None
    assert HOME.check_node(_node("/home", "dir", 0o755), label=LABEL) is None


def test_ancestor_that_is_not_a_directory_is_refused() -> None:
    with pytest.raises(RestoreScopeError, match="/home is a file on the path above"):
        HOME.check_node(_node("/home", "file"), label=LABEL)
    with pytest.raises(RestoreScopeError, match="/home is a symlink on the path"):
        HOME.check_node(_node("/home", "symlink", 0o777), label=LABEL)


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "/home/user2/x", "/home/userx", "/root", "/bin/sh"],
)
def test_node_outside_every_root_is_refused_naming_it(path: str) -> None:
    with pytest.raises(RestoreScopeError, match=f"{path} lies outside every"):
        HOME.check_node(_node(path), label=LABEL)


@pytest.mark.parametrize("kind", ["fifo", "chardev", "dev", "socket", "irregular"])
def test_special_node_kinds_are_refused(kind: str) -> None:
    with pytest.raises(RestoreScopeError, match=f"/home/user/x is a {kind}"):
        HOME.check_node(_node("/home/user/x", kind), label=LABEL)


@pytest.mark.parametrize("mode", [0o4755, 0o2755, 0o1777, 0o6777, 0o7777])
def test_special_mode_bits_on_regular_files_are_refused(mode: int) -> None:
    with pytest.raises(RestoreScopeError, match="setuid, setgid or sticky"):
        HOME.check_node(_node("/home/user/bin/sh", mode=mode), label=LABEL)


@pytest.mark.parametrize("mode", [0o1777, 0o2775, 0o3777])
def test_special_mode_bits_on_directories_are_accepted(mode: int) -> None:
    """Sticky and setgid on a directory carry no privilege: ``/tmp`` can be a root."""
    assert HOME.check_node(_node("/home/user/shared", "dir", mode), label=LABEL)
    tmp = RestoreRoots.from_include(["/tmp"], label=LABEL)
    assert tmp.check_node(_node("/tmp", "dir", mode), label=LABEL) == "/tmp"
    walk = tmp.walker(label=LABEL)
    walk.visit(_node("/tmp", "dir", 0o1777))
    walk.visit(_node("/tmp/f"))
    walk.finish()


def test_hard_link_target_must_be_under_a_root() -> None:
    inside = RestoreNode("/home/user/b", "hardlink", 0o644, link_target="/home/user/a")
    assert HOME.check_node(inside, label=LABEL) == "/home/user"
    outside = RestoreNode("/home/user/pw", "hardlink", 0o644, link_target="/etc/passwd")
    with pytest.raises(RestoreScopeError, match="hard link to /etc/passwd"):
        HOME.check_node(outside, label=LABEL)
    with pytest.raises(RestoreScopeError, match="hard link target"):
        HOME.check_node(
            RestoreNode("/home/user/pw", "hardlink", 0o644, link_target=None),
            label=LABEL,
        )


@pytest.mark.parametrize(
    "path", ["home/user/x", "/home/user/../../etc/passwd", "/home/user/./x", "//x"]
)
def test_unnormalized_node_paths_are_refused_not_resolved(path: str) -> None:
    with pytest.raises(RestoreScopeError, match="snapshot node path"):
        HOME.check_node(_node(path), label=LABEL)


def test_walk_requires_every_root_present() -> None:
    roots = RestoreRoots.from_include(["/home/user", "/data"], label=LABEL)
    walk = roots.walker(label=LABEL)
    walk.visit(_node("/home", "dir", 0o755))  # ancestor: credits no root
    walk.visit(_node("/home/user", "dir", 0o755))
    walk.visit(_node("/data/x"))  # a node under a root counts for it
    walk.finish()
    partial = roots.walker(label=LABEL)
    partial.visit(_node("/home/user/x"))
    with pytest.raises(
        RestoreScopeError, match=r"no node at capture root\(s\) \['/data'\]"
    ):
        partial.finish()


def test_walk_rejects_a_node_in_listing_order() -> None:
    # The first offending node raises; nothing after it is consulted.
    walk = HOME.walker(label=LABEL)
    walk.visit(_node("/home/user"))
    with pytest.raises(RestoreScopeError, match="/etc/passwd"):
        walk.visit(_node("/etc/passwd"))


# --- restic node records ---------------------------------------------------


def test_restic_node_maps_go_mode_bits_to_posix() -> None:
    """``restic ls --json`` encodes special bits at Go's ``os.FileMode`` positions."""
    node = restic_node(
        {"type": "file", "path": "/home/user/suid", "mode": (1 << 23) | 0o755},
        label=LABEL,
    )
    assert node.mode == 0o4755
    assert (
        restic_node(
            {"type": "file", "path": "/x", "mode": (1 << 22) | 0o755}, label=LABEL
        ).mode
        == 0o2755
    )
    assert (
        restic_node(
            {"type": "dir", "path": "/tmp", "mode": (1 << 31) | (1 << 20) | 0o777},
            label=LABEL,
        ).mode
        == 0o1777
    )
    plain = restic_node({"type": "file", "path": "/x", "mode": 0o644}, label=LABEL)
    assert (plain.kind, plain.mode, plain.link_target) == ("file", 0o644, None)


@pytest.mark.parametrize(
    "record",
    [
        {"type": "file"},
        {"path": "/x"},
        {"type": "file", "path": "/x", "mode": "0644"},
        {"type": "file", "path": "/x", "mode": True},
    ],
)
def test_restic_node_rejects_malformed_record(record: dict[str, object]) -> None:
    with pytest.raises(RestoreScopeError):
        restic_node(record, label=LABEL)


# --- tar members -----------------------------------------------------------


def _member(
    name: str, type: bytes = tarfile.REGTYPE, **attrs: object
) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = type
    for key, value in attrs.items():
        setattr(info, key, value)
    return info


def test_tar_member_node_kinds_and_modes() -> None:
    assert tar_member_node(
        _member("home/user/f", mode=0o4755), label=LABEL
    ) == RestoreNode("/home/user/f", "file", 0o4755)
    assert tar_member_node(
        _member("home/user/d/", tarfile.DIRTYPE, mode=0o755), label=LABEL
    ) == (RestoreNode("/home/user/d", "dir", 0o755))
    assert tar_member_node(
        _member("home/user/l", tarfile.SYMTYPE, linkname="/etc/passwd", mode=0o777),
        label=LABEL,
    ) == RestoreNode("/home/user/l", "symlink", 0o777)
    assert tar_member_node(
        _member("home/user/h", tarfile.LNKTYPE, linkname="home/user/f", mode=0o644),
        label=LABEL,
    ) == RestoreNode("/home/user/h", "hardlink", 0o644, link_target="/home/user/f")
    fifo = tar_member_node(_member("home/user/p", tarfile.FIFOTYPE), label=LABEL)
    with pytest.raises(RestoreScopeError, match="/home/user/p is a tar type"):
        HOME.check_node(fifo, label=LABEL)
    for type in (tarfile.CHRTYPE, tarfile.BLKTYPE):
        with pytest.raises(RestoreScopeError, match="tar type"):
            HOME.check_node(
                tar_member_node(_member("home/user/dev", type), label=LABEL),
                label=LABEL,
            )


@pytest.mark.parametrize("type", [tarfile.GNUTYPE_SPARSE, tarfile.CONTTYPE])
def test_tar_member_node_refuses_regular_file_variants(type: bytes) -> None:
    """``S`` and ``7`` count as regular to ``TarInfo.isreg()`` but not here."""
    node = tar_member_node(_member("home/user/f", type), label=LABEL)
    with pytest.raises(RestoreScopeError, match=f"/home/user/f is a tar type {type!r}"):
        HOME.check_node(node, label=LABEL)


@pytest.mark.parametrize("records", [{"size": "512"}, {"path": "home/user/f"}])
def test_tar_member_node_refuses_pax_records(records: dict[str, str]) -> None:
    """A member ``tarfile`` patched from PAX records is refused before any scope check.

    The extracting tar may not apply the same records (busybox ignores
    PAX), so the two would disagree on the member's name or on where the
    next one starts.
    """
    member = _member("home/user/f", pax_headers=records)
    with pytest.raises(RestoreScopeError, match="carries PAX extended-header"):
        tar_member_node(member, label=LABEL)


def _long_header(type: bytes, value: str) -> bytes:
    """A raw GNU long-name (``L``) or long-link (``K``) header carrying ``value``."""
    info = tarfile.TarInfo("././@LongLink")
    info.type = type
    data = value.encode() + b"\0"
    info.size = len(data)
    return (
        info.tobuf(tarfile.USTAR_FORMAT)
        + data
        + b"\0" * (-len(data) % tarfile.BLOCKSIZE)
    )


_LONG_NAME = "home/user/" + "n" * 120
_LONG_LINK = "home/user/" + "t" * 120


@pytest.mark.parametrize(
    "chain, refused",
    [
        pytest.param([tarfile.GNUTYPE_LONGLINK], False, id="K"),
        pytest.param([tarfile.GNUTYPE_LONGNAME], False, id="L"),
        pytest.param(
            [tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK], False, id="LK"
        ),
        pytest.param(
            [tarfile.GNUTYPE_LONGLINK, tarfile.GNUTYPE_LONGLINK], True, id="KK"
        ),
        pytest.param(
            [tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGNAME], True, id="LL"
        ),
    ],
)
@pytest.mark.parametrize("chunk", [1, 511, 512, 700, 1 << 20])
def test_tar_header_scan_refuses_a_repeated_long_header(
    chain: list[bytes], refused: bool, chunk: int
) -> None:
    """Of two chained ``K`` (or ``L``) headers ``tarfile`` applies the first, busybox and GNU tar the last.

    One header of each kind per member is what an honest capture writes
    and stays accepted; the tracking resets at each real member, so two
    members each preceded by the same chain scan cleanly. The stream is
    fed in every chunk size from single bytes to one read, since headers
    arrive split however the decompressor delivers them; a regular file
    with data sits between the two members so its blocks are skipped.
    """
    values = {
        tarfile.GNUTYPE_LONGNAME: _LONG_NAME,
        tarfile.GNUTYPE_LONGLINK: _LONG_LINK,
    }
    member = b"".join(_long_header(t, values[t]) for t in chain) + _member(
        "home/user/short", tarfile.LNKTYPE, linkname="home/user/x"
    ).tobuf(tarfile.USTAR_FORMAT)
    data = b"\1" * 700
    with_data = _member("home/user/f", size=len(data)).tobuf(tarfile.USTAR_FORMAT)
    with_data += data + b"\0" * (-len(data) % tarfile.BLOCKSIZE)
    raw = member + with_data + member + b"\0" * (2 * tarfile.BLOCKSIZE)

    def scan() -> None:
        scanner = TarHeaderScan(label=LABEL)
        for start in range(0, len(raw), chunk):
            scanner.feed(raw[start : start + chunk])

    if refused:
        with pytest.raises(RestoreScopeError, match="two GNU long-(name|link)"):
            scan()
    else:
        scan()
        # And tarfile, given the same bytes, lists what the scan accepted.
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r|") as tar:
            names = [m.name for m in tar]
        name = _LONG_NAME if tarfile.GNUTYPE_LONGNAME in chain else "home/user/short"
        assert names == [name, "home/user/f", name]


def test_tar_header_scan_ends_where_tarfile_does() -> None:
    """A zero block or a mismatching canonical checksum ends the scan, and nothing else does.

    ``tarfile`` ends its listing at exactly those two points, and the
    archive strategy refuses anything but zero padding after them, so a
    chain there is not the scan's to judge: two ``K`` headers behind an
    end-of-archive marker or a bad checksum raise nothing here.
    """
    two_k = _long_header(tarfile.GNUTYPE_LONGLINK, _LONG_LINK) * 2
    hardlink = _member("home/user/pw", tarfile.LNKTYPE).tobuf(tarfile.USTAR_FORMAT)
    bad = bytearray(_member("home/user/x").tobuf(tarfile.USTAR_FORMAT))
    bad[148:156] = b"0000000\0"
    for prefix in (b"\0" * tarfile.BLOCKSIZE, bytes(bad)):
        TarHeaderScan(label=LABEL).feed(prefix + two_k + hardlink)
    with pytest.raises(RestoreScopeError, match="two GNU long-link"):
        TarHeaderScan(label=LABEL).feed(two_k + hardlink)


@pytest.mark.parametrize(
    "type, kind",
    [
        pytest.param(tarfile.XHDTYPE, "PAX extended", id="x"),
        pytest.param(tarfile.XGLTYPE, "PAX global", id="g"),
        pytest.param(tarfile.SOLARIS_XHDTYPE, "Solaris PAX extended", id="X"),
    ],
)
def test_tar_header_scan_refuses_an_empty_pax_header_tarfile_lists_past(
    type: bytes, kind: str
) -> None:
    """A PAX header with no records is refused, not a stopping point.

    ``tarfile`` consumes ``x``/``g``/``X`` headers without yielding them;
    one with an empty payload hands the next member empty ``pax_headers``,
    which :func:`tar_member_node` accepts, and the listing carries on —
    asserted here, since a scan that stopped at the header would leave a
    ``K K`` chain behind it unjudged while the walk accepted the link.
    """
    pax = _member("././@PaxHeader", type).tobuf(tarfile.USTAR_FORMAT)
    two_k = _long_header(tarfile.GNUTYPE_LONGLINK, "home/user/a")
    two_k += _long_header(tarfile.GNUTYPE_LONGLINK, "etc/passwd")
    hardlink = _member("home/user/pw", tarfile.LNKTYPE).tobuf(tarfile.USTAR_FORMAT)
    raw = pax + two_k + hardlink + b"\0" * (2 * tarfile.BLOCKSIZE)

    with tarfile.open(fileobj=io.BytesIO(raw), mode="r|") as tar:
        listed = [(m.name, m.linkname, m.pax_headers) for m in tar]
    assert listed == [("home/user/pw", "home/user/a", {})]

    with pytest.raises(
        RestoreScopeError, match=rf"holds a {kind} header \('\./\./@PaxHeader'\)"
    ):
        TarHeaderScan(label=LABEL).feed(raw)


@pytest.mark.parametrize(
    "type, kind",
    [
        pytest.param(tarfile.GNUTYPE_SPARSE, "GNU sparse file", id="S"),
        pytest.param(tarfile.CHRTYPE, "character device", id="3"),
        pytest.param(tarfile.BLKTYPE, "block device", id="4"),
        pytest.param(tarfile.FIFOTYPE, "fifo", id="6"),
        pytest.param(tarfile.CONTTYPE, "contiguous file", id="7"),
        pytest.param(b"Z", "tar type b'Z'", id="unknown"),
    ],
)
def test_tar_header_scan_refuses_header_types_the_walk_would_refuse(
    type: bytes, kind: str
) -> None:
    """Every header type that is not a member or a long header is refused, naming the member.

    The walk would refuse these members when ``tarfile`` yields them, so
    refusing at the header is equivalent and keeps the scan's rule simple:
    it stops only where ``tarfile`` provably stops.
    """
    header = _member("home/user/odd", type).tobuf(tarfile.USTAR_FORMAT)
    with pytest.raises(
        RestoreScopeError,
        match=rf"holds a {re.escape(kind)} header \('home/user/odd'\)",
    ):
        TarHeaderScan(label=LABEL).feed(header)


@pytest.mark.parametrize("field", [b"1_000\0      ", b"+12\0        ", b"\xff" * 12])
def test_tar_header_scan_refuses_size_fields_tarfile_would_reinterpret(
    field: bytes,
) -> None:
    """Only canonical octal (or GNU base-256) sizes are scanned; ``int()`` forms are not."""
    with pytest.raises(RestoreScopeError, match="size field that is not octal"):
        TarHeaderScan(label=LABEL).feed(_header_with_size_field("home/user/f", field))


def _header_with_size_field(name: str, field: bytes) -> bytes:
    """A regular-file header with a raw ``size`` field and a recomputed checksum."""
    header = bytearray(_member(name).tobuf(tarfile.USTAR_FORMAT))
    header[124:136] = field
    header[148:156] = b"        "
    header[148:156] = f"{sum(header):06o}\0 ".encode()
    return bytes(header)


_CHECKSUM_FORMS = ["base256", "signed", "underscored", "tab_led", "prefixed"]


def _checksum_field(total: int, form: str) -> bytes:
    """``total`` spelled as an 8-byte checksum field in ``form``, each of which ``tarfile.nti`` reads."""
    if form == "base256":
        return b"\x80" + total.to_bytes(7, "big")
    octal = f"{total:06o}"
    text = {
        "signed": f"+{octal}",
        "underscored": f"{octal[0]}_{octal[1:]}",
        "tab_led": f"\t{octal}",
        "prefixed": f"0o{total:o}",
    }[form]
    field = f"{text}\0".encode().ljust(8, b"\0")
    assert len(field) == 8
    return field


def _header_with_checksum_form(name: str, form: str) -> bytes:
    """A regular-file header whose numerically correct checksum is spelled in ``form``."""
    header = bytearray(_member(name).tobuf(tarfile.USTAR_FORMAT))
    header[148:156] = b"        "
    header[148:156] = _checksum_field(sum(header), form)
    return bytes(header)


@pytest.mark.parametrize("form", sorted(_CHECKSUM_FORMS))
def test_tar_header_scan_refuses_checksum_fields_tarfile_would_read(form: str) -> None:
    """A checksum ``tarfile`` reads but the scan cannot is refused, not a stopping point.

    ``tarfile`` accepts a base-256 checksum and every ``int(s, 8)`` form
    and lists on; had the scan merely stopped there, a ``K K`` chain
    behind such a header would retarget a hard link unseen while the
    walk kept accepting members. The header carries its true byte sum,
    so ``tarfile`` continues through it — asserted, since that is the
    whole reason stopping would be wrong.
    """
    header = _header_with_checksum_form("home/user/a", form)
    two_k = _long_header(tarfile.GNUTYPE_LONGLINK, "home/user/a")
    two_k += _long_header(tarfile.GNUTYPE_LONGLINK, "etc/passwd")
    hardlink = _member("home/user/pw", tarfile.LNKTYPE).tobuf(tarfile.USTAR_FORMAT)
    raw = header + two_k + hardlink + b"\0" * (2 * tarfile.BLOCKSIZE)

    with tarfile.open(fileobj=io.BytesIO(raw), mode="r|") as tar:
        listed = [(m.name, m.linkname) for m in tar]
    assert listed == [("home/user/a", ""), ("home/user/pw", "home/user/a")]

    with pytest.raises(RestoreScopeError, match="checksum field that is not octal"):
        TarHeaderScan(label=LABEL).feed(raw)


def test_tar_header_scan_reads_base256_sizes_like_tarfile() -> None:
    """A GNU base-256 size skips exactly the data ``tarfile`` skips, then judges the next header."""
    header = _header_with_size_field(
        "home/user/big", b"\x80" + (1024).to_bytes(11, "big")
    )
    two_k = _long_header(tarfile.GNUTYPE_LONGLINK, _LONG_LINK) * 2
    hardlink = _member("home/user/pw", tarfile.LNKTYPE).tobuf(tarfile.USTAR_FORMAT)
    with pytest.raises(RestoreScopeError, match="two GNU long-link"):
        TarHeaderScan(label=LABEL).feed(header + b"\1" * 1024 + two_k + hardlink)


@pytest.mark.parametrize(
    "type",
    [
        pytest.param(tarfile.GNUTYPE_LONGNAME, id="L"),
        pytest.param(tarfile.GNUTYPE_LONGLINK, id="K"),
    ],
)
def test_tar_header_scan_refuses_an_oversized_long_header_on_its_header_alone(
    type: bytes,
) -> None:
    """A long header claiming more than ``MAX_LONG_HEADER_BYTES`` is refused before its data.

    ``tarfile`` reads a long header's data into memory whole, so the
    refusal must come from the 512-byte header, with none of the declared
    bytes read; a header at the limit is skipped like any other.
    """
    over = _member("././@LongLink", type, size=MAX_LONG_HEADER_BYTES + 1).tobuf(
        tarfile.USTAR_FORMAT
    )
    with pytest.raises(
        RestoreScopeError,
        match=rf"long-(name|link) \([LK]\) header of {MAX_LONG_HEADER_BYTES + 1} bytes",
    ):
        TarHeaderScan(label=LABEL).feed(over)

    at_limit = _member("././@LongLink", type, size=MAX_LONG_HEADER_BYTES).tobuf(
        tarfile.USTAR_FORMAT
    )
    member = _member("home/user/x", tarfile.LNKTYPE, linkname="home/user/y")
    scanner = TarHeaderScan(label=LABEL)
    scanner.feed(at_limit + b"n" * MAX_LONG_HEADER_BYTES)
    scanner.feed(member.tobuf(tarfile.USTAR_FORMAT) + b"\0" * (2 * tarfile.BLOCKSIZE))


@pytest.mark.parametrize("type", [tarfile.DIRTYPE, tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_tar_member_node_refuses_data_on_a_directory_symlink_or_hard_link(
    type: bytes,
) -> None:
    """``tarfile`` skips no data for these whatever ``size`` says; an honest capture writes 0."""
    member = _member("home/user/x", type, size=512, linkname="home/user/y")
    with pytest.raises(RestoreScopeError, match="recorded with 512 bytes of data"):
        tar_member_node(member, label=LABEL)
    assert tar_member_node(
        _member("home/user/x", type, linkname="home/user/y"), label=LABEL
    )


@pytest.mark.parametrize(
    "find", [["find"], pytest.param(["busybox", "find"], id="busybox")]
)
def test_find_special_nodes_command_matches_what_check_node_refuses(
    tmp_path: Path, find: list[str]
) -> None:
    """The in-sandbox ``find`` names a setuid file or fifo, never a sticky/setgid dir."""
    if shutil.which(find[0]) is None:
        pytest.skip(f"{find[0]} not installed")
    root = tmp_path / "root"
    root.mkdir()
    (root / "sticky").mkdir()
    (root / "sticky").chmod(0o1777)
    (root / "shared").mkdir()
    (root / "shared").chmod(0o2775)
    (root / "plain").write_text("ok")
    (root / "link").symlink_to("plain")
    command = find_special_nodes_command([str(root)])
    assert command.startswith("find ")
    command = " ".join(find) + command[len("find") :]

    def run() -> str:
        return subprocess.run(
            ["sh", "-c", command], capture_output=True, text=True, check=True
        ).stdout.strip()

    assert run() == ""
    (root / "sticky" / "sh").write_text("#!/bin/sh\n")
    (root / "sticky" / "sh").chmod(0o4755)
    assert run() == str(root / "sticky" / "sh")
    (root / "sticky" / "sh").chmod(0o755)
    os.mkfifo(root / "pipe")
    assert run() == str(root / "pipe")


@pytest.mark.parametrize(
    "find", [["find"], pytest.param(["busybox", "find"], id="busybox")]
)
def test_remove_existing_symlinks_command_deletes_only_symlinks_under_roots(
    tmp_path: Path, find: list[str]
) -> None:
    """The pre-restore pass deletes every symlink under a root and nothing else.

    A link pointing outside the root, one pointing inside it, one nested
    in a subdirectory and a root that is itself a dangling symlink go;
    the files and directories beside them, the link targets, a symlink
    beside the root and a root the image never created are left alone.
    """
    if shutil.which(find[0]) is None:
        pytest.skip(f"{find[0]} not installed")
    outside = tmp_path / "etc"
    outside.mkdir()
    (outside / "passwd").write_text("root:x:0:0\n")
    root = tmp_path / "home" / "us er's"
    (root / "sub").mkdir(parents=True)
    (root / "plain").write_text("ok")
    (root / "sub" / "deep").write_text("deep")
    (root / "l").symlink_to("../../etc")
    (root / "inner").symlink_to("plain")
    (root / "sub" / "nested").symlink_to("/nonexistent")
    sibling = tmp_path / "home" / "other"
    sibling.symlink_to("../etc")
    link_root = tmp_path / "data"
    link_root.symlink_to("nowhere")
    missing = tmp_path / "never-created"

    command = remove_existing_symlinks_command(
        [str(root), str(link_root), str(missing)]
    )
    assert command.count("then find ") == 3 and command.count("-xdev") == 3
    command = command.replace("then find ", "then " + " ".join(find) + " ")
    subprocess.run(["sh", "-c", "set -e\n" + command], check=True, capture_output=True)

    for gone in (root / "l", root / "inner", root / "sub" / "nested", link_root):
        assert not gone.is_symlink() and not gone.exists()
    assert (root / "plain").read_text() == "ok"
    assert (root / "sub" / "deep").read_text() == "deep"
    assert (outside / "passwd").read_text() == "root:x:0:0\n"
    assert os.readlink(sibling) == "../etc"
    assert not missing.exists()


async def test_remove_existing_symlinks_runs_as_root_and_reports_failure() -> None:
    """The pass runs the command as root under ``set -e`` and a failure names the roots."""
    from test_helpers.local_shell_sandbox import LocalShellSandbox

    from inspect_ai.util._subprocess import ExecResult

    class _Recording(LocalShellSandbox):
        def __init__(self, success: bool) -> None:
            super().__init__()
            self.success = success
            self.calls: list[tuple[list[str], str | None]] = []

        async def exec(
            self,
            cmd: list[str],
            input: str | bytes | None = None,
            cwd: str | None = None,
            env: dict[str, str] | None = None,
            user: str | None = None,
            timeout: int | None = None,
            timeout_retry: bool = True,
            concurrency: bool = True,
        ) -> ExecResult[str]:
            self.calls.append((cmd, user))
            return ExecResult(
                success=self.success,
                returncode=0 if self.success else 1,
                stdout="",
                stderr="" if self.success else "find: permission denied\n",
            )

    ok = _Recording(success=True)
    await remove_existing_symlinks(ok, HOME, label=LABEL)
    (cmd, user), *rest = ok.calls
    assert not rest and user == "root"
    assert cmd == pinned_shell_command(
        "set -e\n" + remove_existing_symlinks_command(HOME.roots)
    )

    failing = _Recording(success=False)
    with pytest.raises(RuntimeError, match=re.escape("['/home/user']")) as exc_info:
        await remove_existing_symlinks(failing, HOME, label=LABEL)
    assert "permission denied" in str(exc_info.value)


@pytest.mark.parametrize(
    "name", ["/home/user/x", "./home/user/x", "home/user/../x", "", "home//user/x"]
)
def test_tar_member_names_must_be_relative_and_normalized(name: str) -> None:
    with pytest.raises(RestoreScopeError, match="archive member"):
        tar_member_node(_member(name), label=LABEL)


def test_tar_member_argument_strips_leading_slash() -> None:
    assert tar_member_argument("/home/user") == "home/user"


def test_tar_listing_round_trip_through_tarfile() -> None:
    """A real in-memory tar: members as ``tar -c`` writes them list and check."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.addfile(_member("home/", tarfile.DIRTYPE, mode=0o755))
        tar.addfile(_member("home/user/", tarfile.DIRTYPE, mode=0o700))
        info = _member("home/user/notes.txt", mode=0o644, size=5)
        tar.addfile(info, io.BytesIO(b"hello"))
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r|") as tar:
        seen = {
            HOME.check_node(tar_member_node(m, label=LABEL), label=LABEL) for m in tar
        }
    assert seen == {None, "/home/user"}


# --- restic restore arguments ----------------------------------------------


def test_restic_restore_args_anchor_at_the_parent() -> None:
    args = restic_restore_args("abc123", "/home/user")
    assert args == ("abc123:/home", "/home", "/user")
    assert restic_restore_args("abc123", "/data") == ("abc123:/", "/", "/data")


def test_restic_restore_args_escape_glob_metacharacters() -> None:
    """Backslash, ``*``, ``?`` and ``[`` are escaped; a lone ``]`` is already literal."""
    args = restic_restore_args("abc123", "/srv/da[t]a*?\\x")
    assert args.include == "/da\\[t]a\\*\\?\\\\x"
    assert args.target == "/srv"


# --- recorded roots ---------------------------------------------------------


def _details(**extra: object) -> SnapshotDetails:
    return SnapshotDetails.model_validate(
        dict(snapshot_id="abc", size_bytes=1, duration_ms=1, **extra)
    )


def test_recorded_roots_absent_is_none_and_accepted() -> None:
    assert recorded_roots(_details(), label=LABEL) is None
    check_recorded_roots(_details(), HOME, label=LABEL)


def test_recorded_roots_matching_current_set_pass() -> None:
    check_recorded_roots(_details(roots=["/home/user/"]), HOME, label=LABEL)


def test_recorded_roots_mismatch_names_both_sets() -> None:
    # The remedy names both causes: a `sandbox_paths` edit, or an
    # auto-included home that moved because the image's default user
    # changed — there is no configuration to restore in the latter case.
    with pytest.raises(
        RestoreScopeError,
        match=r"\['/data'\].*\['/home/user'\].*configuration or the image",
    ):
        check_recorded_roots(_details(roots=["/data"]), HOME, label=LABEL)


@pytest.mark.parametrize("roots", ["/home/user", [1, 2], {"a": 1}])
def test_recorded_roots_malformed_is_an_error(roots: object) -> None:
    with pytest.raises(RestoreScopeError, match="malformed roots"):
        recorded_roots(_details(roots=roots), label=LABEL)
