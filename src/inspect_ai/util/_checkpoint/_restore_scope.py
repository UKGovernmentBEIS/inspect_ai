"""Scope and structural checks for restoring a sandbox snapshot.

On resume a strategy materializes a committed snapshot into a fresh
sandbox as root. The snapshot came from the resume source — whatever
its last writer put there — so it is untrusted data: a crafted snapshot
can carry ``/etc/passwd``, a setuid shell at any path, or a replacement
for ``/bin/sh``, and restic and tar would write each node where the
snapshot says, with the mode and owner it says. Structural validation
before any byte enters the sandbox is the defense; the resume source
itself is not authenticated.

The trusted roots are this attempt's resolved capture set
(``SandboxBackupPaths.include``: the task's ``sandbox_paths`` entry, or
the default user's home dir resolved against the fresh sandbox) — never
anything read from the checkpoint dir. Each strategy lists its snapshot
on the host (``restic ls --json`` against the adopted repo; ``tarfile``
over the stored archive) and feeds every node to a :class:`RestoreWalk`
(``roots.walker(label=...)``), which applies :meth:`RestoreRoots.check_node`
to each, bounds the listing length, and on ``finish()`` requires every
root to have appeared:

- a node must sit at or under a root, or be a *directory* on the path
  above one (restic and tar both record a source path's ancestors);
- a node under a root must be a regular file, directory, symlink, or
  (tar) hard link whose target is also under a root — no device, fifo,
  or socket nodes;
- a regular file under a root carries no setuid, setgid, or sticky
  bit. Directories are exempt: their sticky and setgid bits (``/tmp``,
  a ``chmod g+s`` shared dir) carry no privilege, and a configured root
  that is itself such a directory must stay resumable.

The tar listing has a second concern: the host parses it with
``tarfile`` but the sandbox extracts it with whatever ``tar`` the image
ships, and the two must agree on where every member starts and what it
says. A PAX extended header (``x``/``g``) can move the boundary
(``size``) or rename a member (``path``), and busybox tar ignores PAX; a
GNU sparse member (``S``) carries out-of-band sparse maps; two chained
GNU long-link headers (``K``) give a hard link one target for
``tarfile`` (which keeps the first) and another for busybox and GNU tar
(which keep the last). An honest capture (``tar -c`` in the default gnu
format, or busybox) writes none of these, so :class:`TarHeaderScan`
refuses, on the raw header stream, a repeated long header and every
header type other than a regular file, directory, symlink, hard link or
long header (PAX, sparse, device, fifo, unknown — ``tarfile`` consumes
a PAX header without ever yielding it), :func:`tar_member_node` refuses
a member carrying PAX records and a directory, symlink or hard link
recorded with data, and the archive strategy also decodes the
compressed stream the way the sandbox does (every gzip member), requires
it to hold only zero padding after the last member ``tarfile`` could
parse, and runs :func:`find_special_nodes_command` in the sandbox after
extraction.

Symlink targets are not constrained: an agent legitimately keeps
symlinks in ``$HOME``. Neither tool follows a restored symlink while
writing later members (restic writes each node at its own tree path;
GNU tar defers absolute and ``..`` symlinks with a placeholder and
busybox tar defers all symlinks to the end, so ``l -> /etc`` followed
by ``l/x`` fails rather than writing ``/etc/x``). A symlink the *fresh
image* ships under a root is resolved, though: the listings judge
paths lexically, but the extracting tool writes through whatever
already exists, so a snapshot holding ``l/x`` and a hard link to
``l/passwd`` where the image has ``l -> /etc`` would plant ``/etc/x``
and alias ``/etc/passwd``. The core therefore runs
:func:`remove_existing_symlinks` in the sandbox on resume before the
strategy's ``setup`` — before anything at all is placed in the sandbox,
including the strategy's own tooling under ``/root/.cache/inspect``,
which sits under the root whenever the default user is root: every
symlink already under a root is deleted, and the snapshot — which holds
every link that was under the root at capture — recreates the ones it
has. Ancestors are exempt from the mode check (``/tmp`` is sticky)
because the strategies restore each root individually — ``restic
restore <id>:<parent> --include /<name>`` and ``tar -x <root>`` — so
nothing above a root is written or has its metadata restored. Extended
attributes are outside both listings; the restic restore reapplies only
``user.*`` (:data:`RESTORED_XATTRS`) and the archive never carries any.

Ownership is the residual: restic and tar restore recorded uid/gid when
running as root. For the auto-home case the core snapshots the home
dir's owner before restore and re-owns every node under it that differs
afterwards (:func:`home_owner_uid` / :func:`enforce_home_owner`); for
configured ``sandbox_paths`` recorded ownership is accepted (root-owned
files under a configured ``/data`` may be legitimate).
"""

from __future__ import annotations

import posixpath
import re
import shlex
import stat
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from inspect_ai.util._sandbox._privileged import privileged_exec, privileged_shell
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from ._layout.schemas import SnapshotDetails

_SPECIAL_MODE_BITS = 0o7000
"""setuid | setgid | sticky, in POSIX ``st_mode`` layout."""

_GO_MODE_SETUID = 1 << 23
_GO_MODE_SETGID = 1 << 22
_GO_MODE_STICKY = 1 << 20
"""Go ``os.FileMode`` special bits, the layout ``restic ls --json`` uses
for ``mode`` (the permission bits are the low 9 bits as usual)."""

_RESTORABLE_KINDS = frozenset({"file", "dir", "symlink", "hardlink"})

_TAR_MEMBER_KINDS: dict[bytes, str] = {
    tarfile.REGTYPE: "file",
    tarfile.AREGTYPE: "file",
    tarfile.DIRTYPE: "dir",
    tarfile.SYMTYPE: "symlink",
    tarfile.LNKTYPE: "hardlink",
}
"""The tar typeflags an honest ``tar -c`` writes for restorable nodes.

Deliberately not ``TarInfo.isreg()``: that also accepts GNU sparse
members (``S``), whose sparse maps ``tarfile`` and the extracting tar
may size differently, and contiguous files (``7``)."""

_LONG_HEADER_TYPES: dict[bytes, str] = {
    tarfile.GNUTYPE_LONGNAME: "long-name (L)",
    tarfile.GNUTYPE_LONGLINK: "long-link (K)",
}
"""The GNU headers that precede a member to carry its over-long name or
link target; an honest capture writes at most one of each per member."""

_TAR_DATA_TYPES = frozenset({tarfile.REGTYPE, tarfile.AREGTYPE, *_LONG_HEADER_TYPES})
"""Header types followed by ``size`` bytes of data (rounded up to blocks),
in ``tarfile``, busybox and GNU tar alike."""

_TAR_NO_DATA_TYPES = frozenset({tarfile.DIRTYPE, tarfile.SYMTYPE, tarfile.LNKTYPE})
"""Header types ``tarfile`` never reads data for. :func:`tar_member_node`
refuses them when ``size`` is non-zero, so every tar agrees the next
header follows immediately."""

_TAR_REFUSED_HEADER_TYPES: dict[bytes, str] = {
    tarfile.XHDTYPE: "PAX extended",
    tarfile.XGLTYPE: "PAX global",
    tarfile.SOLARIS_XHDTYPE: "Solaris PAX extended",
    tarfile.GNUTYPE_SPARSE: "GNU sparse file",
    tarfile.CHRTYPE: "character device",
    tarfile.BLKTYPE: "block device",
    tarfile.FIFOTYPE: "fifo",
    tarfile.CONTTYPE: "contiguous file",
}
"""Names for the header types :class:`TarHeaderScan` refuses outright
(any type outside :data:`_TAR_DATA_TYPES` and :data:`_TAR_NO_DATA_TYPES`
is refused; one not listed here is named by its typeflag)."""

_TAR_OCTAL_RE = re.compile(rb" *([0-7]*)[ \0]*")
"""The octal number forms ``tarfile`` parses that an honest header can
hold: digits, optionally space-led, then space or NUL padding. A strict
subset of ``tarfile``'s parser (which also takes signs, underscores and
other whitespace), so a field this refuses is refused, never re-read."""

MAX_RESTORE_NODES = 5_000_000
"""Most nodes a snapshot listing may hold before the restore is refused.

The listing is untrusted: restic trees form a DAG, so a small crafted
repo can reuse subtrees into an effectively unbounded listing, and a
tar stream can be padded with members indefinitely. A generous ceiling
(a large home dir with a couple of ``node_modules`` trees is a few
hundred thousand nodes) bounds the host work to a deterministic
failure instead of an open-ended walk."""

MAX_LONG_HEADER_BYTES = 64 * 1024
"""Ceiling on the ``size`` of a GNU long-name or long-link header.

``tarfile`` reads a long header's data into memory whole, so an
archive could claim gigabytes of name before the node count bounds
anything; no path a sandbox can hold comes near this (Linux
``PATH_MAX`` is 4096), and the egress side bounds its tar metadata
the same way."""

_RESTIC_GLOB_CHARS = "\\*?["

RESTORED_XATTRS = "user.*"
"""The only extended-attribute namespace a restic restore reapplies
(``restic restore --include-xattr``). Neither listing shows xattrs, and
restic as root would otherwise reapply a recorded ``security.capability``
(file capabilities: a setuid bit by another name) or a
``system.posix_acl_*`` grant. tar never stores xattrs without
``--xattrs``, which the capture does not pass."""


class RestoreScopeError(RuntimeError):
    """A snapshot to be restored into a sandbox failed a scope or structure check."""


@dataclass(frozen=True)
class RestoreNode:
    """One snapshot node, in the vocabulary :meth:`RestoreRoots.check_node` checks."""

    path: str
    """Absolute path the node would be restored at."""

    kind: str
    """``file``, ``dir``, ``symlink``, ``hardlink``; any other value is rejected."""

    mode: int
    """POSIX permission bits including the special bits (``st_mode & 0o7777``)."""

    link_target: str | None = None
    """A hard link's target path (absolute); ``None`` for every other kind."""


def normalize_absolute(path: str, *, label: str, what: str) -> str:
    """``path`` if it is already canonical, else a :class:`RestoreScopeError`.

    Requires a leading ``/`` and rejects empty (``//``, trailing ``/``),
    ``.`` and ``..`` components rather than resolving them: a snapshot
    node or capture root with such a component is never what an honest
    capture wrote, and lexical resolution would decide containment for
    a path the restoring tool may interpret differently.
    """
    if not path.startswith("/"):
        raise RestoreScopeError(f"{label}: {what} is not an absolute path: {path!r}")
    parts = path[1:].split("/") if len(path) > 1 else []
    if any(part in ("", ".", "..") for part in parts):
        raise RestoreScopeError(
            f"{label}: {what} has an empty, '.' or '..' component: {path!r}"
        )
    return path


@dataclass(frozen=True)
class RestoreRoots:
    """The absolute paths a restore may write at or under."""

    roots: tuple[str, ...]
    """Canonical absolute roots, sorted, deduplicated, none nested under
    another. Never contains ``/``."""

    @classmethod
    def from_include(cls, include: Sequence[str], *, label: str) -> RestoreRoots:
        """Roots from a capture include set (``SandboxBackupPaths.include``).

        A root nested under another (``/data`` and ``/data/sub``) is
        dropped: the outer root already covers it, and restoring both
        would write the nested tree twice. ``/`` is refused: a capture
        of the whole filesystem has no scope to enforce, and the
        per-root restore forms have no parent to anchor at.
        """
        roots: set[str] = set()
        for raw in include:
            root = normalize_absolute(
                posixpath.normpath(raw) if raw.startswith("/") else raw,
                label=label,
                what="capture root",
            )
            if root == "/":
                raise RestoreScopeError(
                    f"{label}: a capture root of '/' cannot be scoped for restore; "
                    f"configure sandbox_paths with specific directories"
                )
            roots.add(root)
        if not roots:
            raise RestoreScopeError(f"{label}: the capture include set is empty")
        outermost = [
            root
            for root in roots
            if not any(root.startswith(other + "/") for other in roots)
        ]
        return cls(tuple(sorted(outermost)))

    def containing_root(self, path: str) -> str | None:
        """The root ``path`` sits at or under, else ``None``."""
        for root in self.roots:
            if path == root or path.startswith(root + "/"):
                return root
        return None

    def is_ancestor(self, path: str) -> bool:
        """Whether ``path`` lies strictly above some root."""
        return any(root.startswith(path + "/") for root in self.roots)

    def check_node(self, node: RestoreNode, *, label: str) -> str | None:
        """Check one node; return the root it falls under (``None`` for an ancestor).

        Raises :class:`RestoreScopeError` naming the offending path when
        the node lies outside every root, is a non-directory ancestor,
        has a kind that is not restorable, is a hard link whose target
        lies outside every root, or is a regular file carrying a special
        mode bit. Setuid and setgid escalate only on executable regular
        files; on a directory they mean group inheritance, and sticky
        (``/tmp``) restricts deletion, so directory bits are accepted as
        recorded and Linux ignores sticky on files anyway. Symlink modes
        are always ``0777``.
        """
        path = normalize_absolute(node.path, label=label, what="snapshot node path")
        root = self.containing_root(path)
        if root is None:
            if not self.is_ancestor(path):
                raise RestoreScopeError(
                    f"{label}: snapshot node {path} lies outside every capture root "
                    f"{list(self.roots)}"
                )
            if node.kind != "dir":
                raise RestoreScopeError(
                    f"{label}: snapshot node {path} is a {node.kind} on the path "
                    f"above a capture root; only directories may appear there"
                )
            return None
        if node.kind not in _RESTORABLE_KINDS:
            raise RestoreScopeError(
                f"{label}: snapshot node {path} is a {node.kind}; only regular "
                f"files, directories, symlinks and in-scope hard links are restored"
            )
        if node.kind == "hardlink":
            target = normalize_absolute(
                node.link_target or "", label=label, what=f"hard link target of {path}"
            )
            if self.containing_root(target) is None:
                raise RestoreScopeError(
                    f"{label}: snapshot node {path} is a hard link to {target}, "
                    f"outside every capture root"
                )
        if node.kind == "file" and node.mode & _SPECIAL_MODE_BITS:
            raise RestoreScopeError(
                f"{label}: snapshot node {path} is a regular file with mode "
                f"{node.mode:04o}: a setuid, setgid or sticky bit is set"
            )
        return root

    def walker(self, *, label: str) -> RestoreWalk:
        """A fresh :class:`RestoreWalk` over one snapshot listing."""
        return RestoreWalk(roots=self, label=label)


@dataclass
class RestoreWalk:
    """One pass over a snapshot listing: :meth:`visit` each node, then :meth:`finish`.

    Holds the bookkeeping both strategies need so neither re-implements
    it: the node count against :data:`MAX_RESTORE_NODES`, and which
    roots have had a node checked under them. ``visit`` raises
    :class:`RestoreScopeError` for a rejected node (see
    :meth:`RestoreRoots.check_node`) or an over-long listing; ``finish``
    raises for a root that never appeared.
    """

    roots: RestoreRoots
    label: str
    _count: int = 0
    _seen: set[str] = field(default_factory=set)

    def visit(self, node: RestoreNode) -> None:
        """Check one listed node, in listing order."""
        self._count += 1
        if self._count > MAX_RESTORE_NODES:
            raise RestoreScopeError(
                f"{self.label}: snapshot lists more than {MAX_RESTORE_NODES} nodes"
            )
        root = self.roots.check_node(node, label=self.label)
        if root is not None:
            self._seen.add(root)

    def finish(self) -> None:
        """Every root must have had at least one node visited under it.

        An honest capture always records each root itself (restic and
        tar both emit the source path as a node), so a root with no
        node is a snapshot that does not match this attempt's capture
        set — refused rather than restored partially.
        """
        missing = set(self.roots.roots) - self._seen
        if missing:
            raise RestoreScopeError(
                f"{self.label}: snapshot has no node at capture root(s) "
                f"{sorted(missing)}"
            )


def restic_node(record: dict[str, Any], *, label: str) -> RestoreNode:
    """A :class:`RestoreNode` from one ``restic ls --json`` node record.

    Restic's ``mode`` is a Go ``os.FileMode``: permission bits low,
    special bits at Go's positions; mapped back to POSIX layout here.
    """
    path, kind, mode = record.get("path"), record.get("type"), record.get("mode", 0)
    if not isinstance(path, str) or not isinstance(kind, str):
        raise RestoreScopeError(f"{label}: malformed snapshot node record: {record}")
    if not isinstance(mode, int) or isinstance(mode, bool):
        raise RestoreScopeError(f"{label}: snapshot node {path} has a non-integer mode")
    posix_mode = mode & 0o777
    if mode & _GO_MODE_SETUID:
        posix_mode |= 0o4000
    if mode & _GO_MODE_SETGID:
        posix_mode |= 0o2000
    if mode & _GO_MODE_STICKY:
        posix_mode |= 0o1000
    return RestoreNode(path=path, kind=kind, mode=posix_mode)


def tar_member_node(member: tarfile.TarInfo, *, label: str) -> RestoreNode:
    """A :class:`RestoreNode` from one tar member.

    Member names must be relative and normalized (``home/user/x``), the
    form ``tar -c`` writes for an absolute source after stripping the
    leading ``/``; an absolute or ``.``/``..``-bearing name is refused
    outright rather than normalized, since the extracting tar decides
    its own interpretation of such a name.

    A member that came with PAX extended-header records is refused
    (:class:`RestoreScopeError`): ``tarfile`` has applied them — a
    ``size`` record moved the next member's boundary, a ``path`` record
    renamed this one — and the extracting tar may not (busybox ignores
    PAX), so the two would disagree on what the archive holds. Neither
    gnu-format GNU tar nor busybox writes PAX headers. A directory,
    symlink or hard link recorded with a non-zero size is refused for the
    same reason: ``tarfile`` reads no data for them whatever the size
    says, an honest capture writes zero, and a tar that skipped the
    recorded size would start the next header elsewhere.
    """
    path = _tar_member_path(member.name, label=label, what="archive member")
    if member.pax_headers:
        raise RestoreScopeError(
            f"{label}: archive member {path} carries PAX extended-header records "
            f"{sorted(member.pax_headers)}, which the extracting tar may interpret "
            f"differently from the host; an honest capture writes none"
        )
    link_target: str | None = None
    kind = _TAR_MEMBER_KINDS.get(member.type, f"tar type {member.type!r} entry")
    if member.type in _TAR_NO_DATA_TYPES and member.size:
        raise RestoreScopeError(
            f"{label}: archive member {path} is a {kind} recorded with "
            f"{member.size} bytes of data; the extracting tar may skip them and "
            f"read the following members differently from the host"
        )
    if kind == "hardlink":
        link_target = _tar_member_path(
            member.linkname, label=label, what=f"hard link target of {path}"
        )
    return RestoreNode(
        path=path, kind=kind, mode=member.mode & 0o7777, link_target=link_target
    )


def _tar_member_path(name: str, *, label: str, what: str) -> str:
    if not name or name.startswith("/"):
        raise RestoreScopeError(f"{label}: {what} is empty or absolute: {name!r}")
    return normalize_absolute("/" + name.rstrip("/"), label=label, what=what)


class TarHeaderScan:
    """Checks the raw header sequence of a tar stream for what ``tarfile`` does not expose.

    ``tarfile`` yields members, not headers. Of two chained GNU long-name
    (``L``) or long-link (``K``) headers it applies the first where
    busybox and GNU tar apply the last, so a hard link the walk saw
    pointing inside a root would be created pointing wherever the second
    ``K`` says — and nothing on the yielded member shows the second
    header. Fed every byte ``tarfile`` reads (:meth:`feed`, from a tee on
    the decompressed stream), the scan walks the 512-byte headers itself,
    skipping member data by the rule ``tarfile`` uses, and raises
    :class:`RestoreScopeError` at a repeated long header before the
    member it describes; ``L`` then ``K`` (a long-named hard link with a
    long target) stays accepted.

    The scan stays aligned with ``tarfile`` on every archive that is
    accepted: sizes are parsed as a strict subset of ``tarfile``'s forms
    (anything else is refused outright); the only members with data are
    regular files and long headers, which every tar skips identically
    (a long header's data is bounded by :data:`MAX_LONG_HEADER_BYTES`
    before ``tarfile`` reads it whole);
    directories, symlinks and hard links carry none (a non-zero size on
    them is refused by :func:`tar_member_node`); and a header of any
    other type — PAX, sparse, device, fifo, unknown — is refused
    outright. The scan may stop only where ``tarfile`` provably stops: a
    zero block, or a canonical-octal checksum that mismatches (the
    archive strategy refuses anything but zero padding after the last
    member ``tarfile`` parsed). Stopping anywhere else would leave the
    rest of the archive unscanned while the walk kept accepting members:
    ``tarfile`` consumes a PAX header (``x``, ``g``, ``X``) without ever
    yielding it — one with no records hands the next member empty
    ``pax_headers``, which :func:`tar_member_node` accepts — and reads
    base-256, signed and underscored checksums and carries on, so those
    are refused rather than treated as an end.
    """

    def __init__(self, *, label: str) -> None:
        self._label = label
        self._partial = bytearray()
        self._skip = 0
        self._long_seen: set[bytes] = set()
        self._done = False

    def feed(self, data: bytes) -> None:
        """Consume the next ``data`` of the decompressed tar stream, in order."""
        view = memoryview(data)
        while view and not self._done:
            if self._skip:
                taken = min(self._skip, len(view))
                self._skip -= taken
                view = view[taken:]
                continue
            take = view[: tarfile.BLOCKSIZE - len(self._partial)]
            self._partial += take
            view = view[len(take) :]
            if len(self._partial) == tarfile.BLOCKSIZE:
                header = bytes(self._partial)
                self._partial.clear()
                self._header(header)

    def _header(self, header: bytes) -> None:
        if header.count(0) == tarfile.BLOCKSIZE or not _tar_checksum_ok(
            header, label=self._label
        ):
            self._done = True
            return
        typeflag = header[156:157]
        long_kind = _LONG_HEADER_TYPES.get(typeflag)
        if long_kind is None:
            self._long_seen.clear()
        elif typeflag in self._long_seen:
            raise RestoreScopeError(
                f"{self._label}: an archive member is preceded by two GNU "
                f"{long_kind} headers; the host would apply the first and the "
                f"extracting tar the last, so the archive is refused"
            )
        else:
            self._long_seen.add(typeflag)
        if typeflag in _TAR_DATA_TYPES:
            size = _tar_octal(header[124:136], label=self._label, what="size")
            if long_kind is not None and size > MAX_LONG_HEADER_BYTES:
                raise RestoreScopeError(
                    f"{self._label}: archive holds a GNU {long_kind} header of "
                    f"{size} bytes; at most {MAX_LONG_HEADER_BYTES} bytes of name "
                    f"or link target are read"
                )
            self._skip = -(-size // tarfile.BLOCKSIZE) * tarfile.BLOCKSIZE
        elif typeflag not in _TAR_NO_DATA_TYPES:
            name = header[:100].split(b"\0", 1)[0].decode("utf-8", "replace")
            kind = _TAR_REFUSED_HEADER_TYPES.get(typeflag, f"tar type {typeflag!r}")
            raise RestoreScopeError(
                f"{self._label}: archive holds a {kind} header ({name!r}); only "
                f"regular files, directories, symlinks, hard links and GNU long "
                f"headers are accepted, since the host and the extracting tar may "
                f"read anything else differently"
            )


def _tar_octal(field: bytes, *, label: str, what: str) -> int:
    """A tar header number: GNU base-256 (``0x80`` lead byte) or canonical octal."""
    if field[0] == 0o200:
        return int.from_bytes(field[1:], "big")
    return _tar_canonical_octal(field, label=label, what=what)


def _tar_canonical_octal(field: bytes, *, label: str, what: str) -> int:
    """A tar header number in canonical octal only: digits padded with spaces or NULs.

    A strict subset of what ``tarfile`` reads — it also takes a base-256
    field and, via ``int(s, 8)``, a signed (``+12``), underscored
    (``1_000``) or tab-led value — so a field in any other form is
    refused rather than read: the scan must never guess at a value, or
    stop, where ``tarfile`` carries on. An honest capture writes none.
    """
    match = _TAR_OCTAL_RE.fullmatch(field)
    if match is None:
        raise RestoreScopeError(
            f"{label}: archive header holds a {what} field that is not octal: "
            f"{field!r}; the extracting tar may read it differently from the host"
        )
    return int(match.group(1) or b"0", 8)


def _tar_checksum_ok(header: bytes, *, label: str) -> bool:
    """Whether ``header``'s canonical-octal checksum matches its bytes, by ``tarfile``'s rule.

    The stored value may match the unsigned or the signed byte sum (with
    the checksum field itself counted as spaces), as ``tarfile`` accepts
    either; a mismatch ends its listing, which is the only checksum
    outcome the scan may stop on. A checksum field in any other form
    raises :class:`RestoreScopeError` (see :func:`_tar_canonical_octal`).
    """
    stored = _tar_canonical_octal(header[148:156], label=label, what="checksum")
    unsigned = 256 + sum(header[:148]) + sum(header[156:])
    signed = (
        256
        + sum(b - 256 if b > 127 else b for b in header[:148])
        + sum(b - 256 if b > 127 else b for b in header[156:])
    )
    return stored in (unsigned, signed)


def tar_member_argument(root: str) -> str:
    """The member name ``tar -x`` scopes extraction to for ``root``.

    tar strips the leading ``/`` from member names at creation, so the
    root ``/home/user`` selects the members ``home/user`` and below.
    Callers put ``--`` before the member arguments so a root name
    starting with ``-`` is never read as an option. GNU tar matches
    member arguments literally; busybox tar globs them, so a root name
    holding ``*``, ``?`` or ``[`` selects more than itself there — this
    is the second layer only, behind the host-side member walk that has
    already rejected every out-of-scope member.
    """
    return root.lstrip("/")


def remove_existing_symlinks_command(roots: Sequence[str]) -> str:
    """Shell lines deleting every symlink already under ``roots`` in the fresh sandbox.

    Run as root under ``set -e`` (see :func:`remove_existing_symlinks`)
    before the strategy places anything in the sandbox. The host walk
    judges paths lexically, but the restoring tool resolves them through
    what the fresh image already has: where the image ships ``l -> /etc``
    under a root, busybox tar writes a member ``l/x`` into ``/etc/x``
    (GNU tar refuses the open) and both tars create a hard link to
    ``l/passwd`` as an alias of ``/etc/passwd``; restic 0.18 replaces a
    node of the wrong type itself and is covered for the same invariant.
    Nothing is lost for an honest snapshot: it holds every symlink that
    was under the root at capture and recreates them; a link it lacks
    was deleted by the agent, or lives in an excluded cache dir and is
    recreated as an ordinary directory when next needed. A root that is
    itself a symlink is deleted too and comes back as the snapshot
    recorded it. ``-xdev`` keeps the pass off anything mounted under a
    root (a symlink inside a compose volume is shared state); a root the
    image never created is skipped rather than failed. Uses only
    predicates and actions busybox find shares with GNU find.
    """
    lines = []
    for root in roots:
        quoted = shlex.quote(root)
        lines.append(
            f"if [ -e {quoted} ] || [ -L {quoted} ]; then "
            f"find {quoted} -xdev -type l -exec rm -f -- {{}} +; fi"
        )
    return "\n".join(lines)


async def remove_existing_symlinks(
    env: SandboxEnvironment, roots: RestoreRoots, *, label: str
) -> None:
    """Run :func:`remove_existing_symlinks_command` over ``roots`` as root.

    The core calls this on resume before the strategy's ``setup``, so
    that the strategy's own state (the injected restic binary and repo,
    the staged archive — all under ``/root/.cache/inspect``, which is
    inside the root when the default user is root) is created as real
    directories rather than written through an image symlink that this
    pass then severs. Running it any later would leave that state
    unreachable at its path and fail the restore without naming the cause.
    """
    result = await privileged_shell(
        env, "set -e\n" + remove_existing_symlinks_command(roots.roots), user="root"
    )
    if not result.success:
        raise RuntimeError(
            f"{label}: removing the fresh sandbox's symlinks under "
            f"{list(roots.roots)} before restoring failed: {result.stderr.strip()}"
        )


def find_special_nodes_command(roots: Sequence[str]) -> str:
    """A ``find`` over ``roots`` printing the first node :meth:`RestoreRoots.check_node` would refuse.

    The in-sandbox check after a tar extraction, independent of how the
    extracting tar parsed the archive: a regular file with a setuid,
    setgid or sticky bit, or a fifo, character or block device node.
    Sockets are not looked for — no tar can create one from an archive.
    ``-xdev`` keeps it off anything mounted under a root. Uses only
    predicates GNU, busybox and BSD find share: ``-perm -MODE`` once per
    bit rather than ``-perm /MODE`` (BSD find, which the tests run this
    on, rejects the ``/`` form), ``-type``, and ``head`` rather than
    ``-quit``.
    Nodes that were under a root before the restore are examined too;
    an honest capture already includes them, so they have passed the
    host-side walk.
    """
    quoted = " ".join(shlex.quote(root) for root in roots)
    special = " -o ".join(
        f"-perm -{bit:o}" for bit in (stat.S_ISUID, stat.S_ISGID, stat.S_ISVTX)
    )
    return (
        f"find {quoted} -xdev "
        f"\\( \\( -type f \\( {special} \\) \\) -o -type p -o -type c "
        f"-o -type b \\) -print | head -n 1"
    )


class ResticRestoreArgs(NamedTuple):
    """Restic arguments restoring exactly one root."""

    snapshot_spec: str
    """``<id>:<parent of root>`` — the restored tree is rooted at the parent."""

    target: str
    """``--target``: the root's parent, so the restored tree lands in place."""

    include: str
    """``--include``: the root's name, anchored and glob-escaped."""


def restic_restore_args(snapshot_id: str, root: str) -> ResticRestoreArgs:
    """Arguments for ``restic restore <id>:<parent> --target <parent> --include /<name>``.

    The root's parent is the restored tree root, so its own metadata —
    and that of every directory above it — is never written: restic
    restores the metadata of any directory on the way to a selected
    node when restoring with ``--target /``, which would let a snapshot
    reset ``/usr``'s owner or mode. Glob metacharacters in the name are
    escaped so the include matches the name literally.
    """
    parent, name = posixpath.split(root)
    escaped = "".join(f"\\{c}" if c in _RESTIC_GLOB_CHARS else c for c in name)
    return ResticRestoreArgs(
        snapshot_spec=f"{snapshot_id}:{parent}", target=parent, include=f"/{escaped}"
    )


def recorded_roots(details: SnapshotDetails, *, label: str) -> list[str] | None:
    """The capture roots a snapshot recorded (``roots`` extra), if any.

    ``None`` for records written before roots were recorded. A present
    value that is not a list of strings is a malformed record and an
    error, not a missing one.
    """
    extra = details.model_extra or {}
    value = extra.get("roots")
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise RestoreScopeError(
            f"{label}: checkpoint record for {details.snapshot_id} has malformed "
            f"roots {value!r}"
        )
    return value


def check_recorded_roots(
    details: SnapshotDetails, roots: RestoreRoots, *, label: str
) -> None:
    """Fail if the snapshot recorded a capture set other than this attempt's.

    The recorded roots are diagnostics, never the source of trust (the
    checkpoint dir is what is being restored *from*); a mismatch means
    the capture set changed between attempts — a ``sandbox_paths`` edit,
    or an auto-included home dir moving because the image's default
    user changed — and is reported rather than restored under either
    set.
    """
    recorded = recorded_roots(details, label=label)
    if recorded is None:
        return
    recorded_set = set(RestoreRoots.from_include(recorded, label=label).roots)
    if recorded_set != set(roots.roots):
        raise RestoreScopeError(
            f"{label}: snapshot {details.snapshot_id} was captured from "
            f"{sorted(recorded_set)} but this attempt captures {list(roots.roots)}; "
            f"the sandbox_paths configuration or the image's default-user home "
            f"directory changed between attempts — resume with the configuration "
            f"and image the snapshot was captured under"
        )


async def home_owner_uid(env: SandboxEnvironment, home: str, *, label: str) -> int:
    """The uid that owns ``home`` in the fresh sandbox, read before any restore.

    Read beforehand because a restore that includes the home dir node
    itself (tar does; restic's per-root form does not) would otherwise
    hand back whatever owner the snapshot recorded. A home dir the image
    never created (the agent made it during the captured attempt) has no
    owner to read; the default user's own uid stands in for it. ``-L``
    follows a home dir that is itself an image symlink to its target's
    owner (the link itself is typically root's); a dangling link falls
    through to the ``test -e`` check, which follows links too.
    """
    result = await privileged_exec(env, ["stat", "-L", "-c", "%u", home], user="root")
    text = result.stdout.strip()
    if result.success and text.isdigit():
        return int(text)
    exists = await privileged_exec(env, ["test", "-e", home], user="root")
    if exists.success:
        raise RuntimeError(
            f"{label}: could not read the owner of home dir {home}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    whoami = await privileged_exec(env, ["id", "-u"], user=None)
    text = whoami.stdout.strip()
    if not whoami.success or not text.isdigit():
        raise RuntimeError(
            f"{label}: home dir {home} does not exist in the fresh sandbox and the "
            f"default user's uid could not be read: {whoami.stderr.strip()}"
        )
    return int(text)


async def enforce_home_owner(
    env: SandboxEnvironment, home: str, uid: int, *, label: str
) -> None:
    """Re-own every node under ``home`` (and ``home`` itself) not owned by ``uid``.

    Symlinks are re-owned themselves, never followed; ``-xdev`` keeps
    the pass off anything mounted under the home dir (a compose volume
    is shared state, not restored state). Files the capture excluded
    (the XDG cache dir) are traversed too; they are the fresh sandbox's
    own and already the user's. The predicate is ownership, not
    provenance: an image-provided root-owned file under the home dir is
    handed to the user as well. Group ownership is left as recorded.
    """
    script = f"find {shlex.quote(home)} -xdev ! -user {uid} -exec chown -h {uid} {{}} +"
    result = await privileged_shell(env, script, user="root")
    if not result.success:
        raise RuntimeError(
            f"{label}: re-owning restored files under {home} to uid {uid} failed: "
            f"{result.stderr.strip()}"
        )
