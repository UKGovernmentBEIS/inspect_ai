"""Scopes and canonical locations for the Inspect view server.

A scope is a set of roots with per-root permissions (design: section 2 of
``design/viewer-scoped-authorization.md``). ``PathScope.resolve`` decides
whether a caller-supplied location falls under a root and, when it does,
returns the canonical ``Location`` the server must use for I/O. There is one
canonicalizer and it is applied to roots and candidates alike, so a check and
the I/O it authorizes always agree on which object they name.

Decode-once rule: the server percent-decodes a request location exactly once
(``normalize_uri`` for path-segment routes, ``urllib.parse.unquote`` for
query-string routes) before it reaches this module. Nothing here decodes
again: every remaining character, including ``%``, ``?`` and ``#``, is part of
the name. Root URIs in a token are not decoded at all: a root is the exact,
unencoded spelling of the location (``file:///w/my logs``, not
``file:///w/my%20logs``), and an ``http(s)`` root is the exact signed URL.
"""

from __future__ import annotations

import os
import posixpath
import re
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, cast, get_args

SCOPE_CLAIM = "inspect_view_scope"
"""Name of the JWT claim carrying the scope."""

SCOPE_VERSION = 1

Permission = Literal["read", "list", "write", "delete"]
PERMISSIONS: frozenset[str] = frozenset(get_args(Permission))

RootKind = Literal["dir", "file"]
ROOT_KINDS: frozenset[str] = frozenset(get_args(RootKind))

_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:$")


# ---------------------------------------------------------------------------
# Canonical forms
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LocalPath:
    """A local filesystem path, fully resolved (symlinks, ``..``, cwd)."""

    path: Path

    def location(self) -> str:
        return str(self.path)


@dataclass(frozen=True)
class _RemotePath:
    """An object-store style location: scheme, authority, normalized path, query."""

    scheme: str
    authority: str
    path: PurePosixPath
    query: str

    def location(self) -> str:
        return urllib.parse.urlunsplit(
            (self.scheme, self.authority, self.path.as_posix(), self.query, "")
        )


@dataclass(frozen=True)
class _OpaqueHttpFile:
    """An ``http(s)`` file held as the exact URL it was given (signed URLs)."""

    scheme: str
    authority: str
    raw: str

    def location(self) -> str:
        return self.raw


_Canonical = _LocalPath | _RemotePath | _OpaqueHttpFile


def _split_protocol(location: str) -> tuple[str | None, str]:
    """Split ``scheme://rest``; a one-letter scheme is a Windows drive, not a scheme."""
    if "://" in location:
        protocol, rest = location.split("://", 1)
        if len(protocol) > 1:
            return protocol, rest
    return None, location


def _canonicalize(location: str, *, windows: bool | None = None) -> _Canonical | None:
    windows = os.name == "nt" if windows is None else windows
    protocol, _ = _split_protocol(location)
    if protocol is not None and protocol.lower() in ("http", "https"):
        return _parse_opaque_http_file(location)
    local = _canonical_local_path(location, windows=windows)
    if local is not None:
        return local
    return _canonical_remote_path(location)


def _canonical_local_path(location: str, *, windows: bool) -> _LocalPath | None:
    if not location or "\x00" in location:
        return None
    if windows and _WINDOWS_DRIVE_PATH.match(location):
        path = location
    else:
        protocol, _ = _split_protocol(location)
        if protocol is None:
            path = location
        elif protocol.lower() == "file":
            file_path = _local_path_from_file_uri(location, windows=windows)
            if file_path is None:
                return None
            path = file_path
        else:
            return None
    try:
        resolved = Path(path).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if windows:
        resolved = _fold_windows_drive(resolved)
    return _LocalPath(resolved)


def _fold_windows_drive(path: Path) -> Path:
    drive = path.drive
    if _WINDOWS_DRIVE.match(drive) and drive != drive.upper():
        return Path(drive.upper() + str(path)[len(drive) :])
    return path


def _local_path_from_file_uri(location: str, *, windows: bool) -> str | None:
    """Extract the path from a once-decoded ``file:`` URI, literally.

    No further percent-decoding and no URL re-parsing: ``?`` and ``#`` are
    file-name characters here. The authority must be empty or ``localhost``;
    on Windows a drive letter authority (the ``file://C:/...`` spelling
    ``normalize_uri`` emits) or a UNC host is also accepted. Anything else,
    including userinfo or a port, makes the URI not a local path.
    """
    _, rest = location.split("://", 1)
    if "\\" in rest:
        return None
    authority, sep, tail = rest.partition("/")
    path = f"{sep}{tail}"
    if authority == "" or authority.lower() == "localhost":
        if not path:
            return None
        if windows and len(path) > 3 and path[2] == ":" and path[0] == "/":
            return path[1:]
        return path
    if windows and _WINDOWS_DRIVE.match(authority):
        return f"{authority}{path}"
    if windows and path.startswith("/"):
        if len(PurePosixPath(path).parts) < 2:
            return None
        return str(PureWindowsPath(f"//{authority}{path}"))
    return None


def _canonical_remote_path(location: str) -> _RemotePath | None:
    protocol, _ = _split_protocol(location)
    if protocol is None or protocol.lower() == "file":
        return None
    try:
        parsed = urllib.parse.urlsplit(location)
        _ = parsed.port
    except ValueError:
        return None
    if (
        not parsed.netloc
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or "\\" in parsed.path
    ):
        return None
    if ".." in PurePosixPath(parsed.path).parts:
        return None
    path = posixpath.normpath("/" + parsed.path.lstrip("/"))
    return _RemotePath(
        scheme=protocol.lower(),
        authority=parsed.netloc.lower(),
        path=PurePosixPath(path),
        query=_canonical_query(parsed.query),
    )


def _canonical_query(query: str) -> str:
    if not query:
        return ""

    def encode(value: str) -> str:
        return urllib.parse.quote(urllib.parse.unquote(value), safe="-._~")

    fields: list[str] = []
    for item in query.split("&"):
        if "=" in item:
            name, value = item.split("=", 1)
            fields.append(f"{encode(name)}={encode(value)}")
        else:
            fields.append(encode(item))
    return "&".join(fields)


def _parse_opaque_http_file(location: str) -> _OpaqueHttpFile | None:
    try:
        parsed = urllib.parse.urlsplit(location)
        _ = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() not in ("http", "https")
        or not parsed.netloc
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or "\\" in parsed.path
    ):
        return None
    return _OpaqueHttpFile(
        scheme=parsed.scheme.lower(), authority=parsed.netloc.lower(), raw=location
    )


# ---------------------------------------------------------------------------
# Public model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScopeRoot:
    """One root of a scope: a directory or file and the permissions granted on it."""

    uri: str
    """The root as spelled in the claim (informational; matching uses the canonical form)."""

    kind: RootKind
    permissions: frozenset[str]
    _canonical: _Canonical = field(repr=False, compare=False)

    @classmethod
    def parse(
        cls,
        uri: object,
        kind: object,
        permissions: object,
        *,
        windows: bool | None = None,
    ) -> ScopeRoot:
        """Build a root from claim fields; raises ``ValueError`` on a malformed root."""
        if not isinstance(kind, str) or kind not in ROOT_KINDS:
            raise ValueError(f"Unknown scope root kind: {kind!r}")
        if not isinstance(uri, str) or not uri:
            raise ValueError("Scope root uri must be a non-empty string")
        if not isinstance(permissions, list) or not all(
            isinstance(p, str) for p in permissions
        ):
            raise ValueError("Scope root permissions must be a list of strings")
        canonical = _canonicalize(uri, windows=windows)
        if canonical is None:
            raise ValueError(f"Invalid scope root: {uri}")
        if isinstance(canonical, _OpaqueHttpFile) and kind != "file":
            raise ValueError("http(s) scope roots must be files")
        if isinstance(canonical, _RemotePath) and kind == "dir" and canonical.query:
            raise ValueError("Directory scope roots cannot carry a query")
        return cls(
            uri=uri,
            kind=cast(RootKind, kind),
            permissions=frozenset(p for p in permissions if p in PERMISSIONS),
            _canonical=canonical,
        )


@dataclass(frozen=True)
class Location:
    """A canonical location, and (when resolved against a scope) what authorized it.

    ``io_path`` is the string handed to the filesystem layer. Compare
    ``Location`` values, never raw strings, when asking whether two spellings
    name the same object.
    """

    io_path: str
    root: ScopeRoot | None = None
    permission: Permission | None = None
    _canonical: _Canonical = field(kw_only=True, repr=False)

    def same_object(self, other: Location) -> bool:
        return self._canonical == other._canonical


@dataclass(frozen=True)
class PathScope:
    """The resolver over a scope's roots."""

    roots: tuple[ScopeRoot, ...]

    def resolve(
        self,
        location: str,
        permission: Permission,
        *,
        windows: bool | None = None,
    ) -> Location | None:
        """Resolve a once-decoded location under the roots, or return ``None``.

        A ``file`` root admits exactly itself. A ``dir`` root admits strict
        descendants for every permission and, for ``list`` only, itself as
        well (listing the root is the ordinary case; reading a directory is
        not a thing). ``http(s)`` roots match byte-for-byte.
        """
        candidate = _canonicalize(location, windows=windows)
        if candidate is None:
            return None
        for root in self.roots:
            if permission in root.permissions and _contains(
                root, candidate, permission
            ):
                return Location(
                    io_path=candidate.location(),
                    root=root,
                    permission=permission,
                    _canonical=candidate,
                )
        return None

    def default_location(self, permission: Permission) -> Location | None:
        """The location an absent request location binds to.

        Only a scope with exactly one root has a default: that root. With zero
        or several roots there is no default and the caller must refuse.
        """
        if len(self.roots) != 1:
            return None
        root = self.roots[0]
        if permission not in root.permissions:
            return None
        return Location(
            io_path=root._canonical.location(),
            root=root,
            permission=permission,
            _canonical=root._canonical,
        )


def _contains(root: ScopeRoot, candidate: _Canonical, permission: Permission) -> bool:
    anchor = root._canonical
    if isinstance(anchor, _OpaqueHttpFile):
        return isinstance(candidate, _OpaqueHttpFile) and candidate.raw == anchor.raw
    if isinstance(anchor, _LocalPath):
        if not isinstance(candidate, _LocalPath):
            return False
        if root.kind == "file":
            return candidate.path == anchor.path
        return _dir_contains(
            anchor.path, candidate.path, allow_self=permission == "list"
        )
    if not isinstance(candidate, _RemotePath):
        return False
    if candidate.scheme != anchor.scheme or candidate.authority != anchor.authority:
        return False
    if root.kind == "file":
        return candidate.path == anchor.path and candidate.query == anchor.query
    if candidate.query:
        return False
    return _dir_contains(anchor.path, candidate.path, allow_self=permission == "list")


def _dir_contains(
    root: Path | PurePosixPath, candidate: Path | PurePosixPath, *, allow_self: bool
) -> bool:
    if candidate == root:
        return allow_self
    return candidate.is_relative_to(root)


@dataclass(frozen=True)
class ViewScope:
    """The validated ``inspect_view_scope`` claim of a verified token."""

    roots: tuple[ScopeRoot, ...]

    @property
    def path_scope(self) -> PathScope:
        return PathScope(self.roots)


def canonical_location(
    location: str, *, windows: bool | None = None
) -> Location | None:
    """Canonicalize a once-decoded location with no scope; ``None`` if unparseable."""
    canonical = _canonicalize(location, windows=windows)
    if canonical is None:
        return None
    return Location(io_path=canonical.location(), _canonical=canonical)


def resolve_child(base: str, child: str) -> str:
    """Join a caller-supplied child directory onto ``base`` for ``/eval-set`` and ``/flow``.

    The child may not contain a backslash or a ``..`` segment (``ValueError``);
    a leading ``/`` is tolerated and dropped, as the routes always did. The
    joined string is what the access policy is then asked about, so this runs
    before any policy and is the same for plain and resolving policies.
    """
    if "\\" in child:
        raise ValueError("Directory may not contain a backslash")
    if ".." in child.split("/"):
        raise ValueError("Directory may not contain a parent reference")
    child = child.lstrip("/")
    return f"{base}/{child}" if base else child


def scope_from_claims(
    claims: Mapping[str, Any], *, windows: bool | None = None
) -> ViewScope:
    """Build a ``ViewScope`` from the claims of an already-verified JWT.

    Applies the validation rules of design section 2: ``v`` must be 1;
    ``roots`` must be a list of ``{uri, kind, permissions}`` objects with a
    known ``kind``; unknown permission strings are ignored and never grant;
    unknown fields are ignored. The reserved fields ``transcripts``,
    ``project`` and ``actions`` (appendix) are shape-checked and otherwise
    ignored; ``roots`` may be empty only when ``project`` is present. Raises
    ``ValueError`` for anything malformed, which the middleware turns into 401.
    """
    claim = claims.get(SCOPE_CLAIM)
    if not isinstance(claim, Mapping):
        raise ValueError(f"Missing or malformed {SCOPE_CLAIM} claim")
    version = claim.get("v")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != SCOPE_VERSION
    ):
        raise ValueError(f"Unsupported {SCOPE_CLAIM} version: {version!r}")

    raw_roots = claim.get("roots")
    if not isinstance(raw_roots, list):
        raise ValueError("Scope roots must be a list")
    roots = tuple(_parse_root(item, windows=windows) for item in raw_roots)

    project = claim.get("project")
    if project is not None:
        if not isinstance(project, Mapping):
            raise ValueError("Scope project must be an object with a uri")
        _check_wire_uri(project.get("uri"), windows=windows)
        _check_permissions(project.get("permissions", []))
    if not roots and project is None:
        raise ValueError("Scope has no roots")

    transcripts = claim.get("transcripts")
    if transcripts is not None:
        if not isinstance(transcripts, list):
            raise ValueError("Scope transcripts must be a list")
        for item in transcripts:
            if not isinstance(item, Mapping):
                raise ValueError("Scope transcript entries must be objects with a uri")
            _check_wire_uri(item.get("uri"), windows=windows)
            if item.get("kind", "dir") not in ROOT_KINDS:
                raise ValueError("Unknown scope transcript kind")

    actions = claim.get("actions")
    if actions is not None and (
        not isinstance(actions, list) or not all(isinstance(a, str) for a in actions)
    ):
        raise ValueError("Scope actions must be a list of strings")

    return ViewScope(roots=roots)


WIRE_SCHEMES: frozenset[str] = frozenset({"file", "s3", "gs", "az", "http", "https"})
"""URI schemes a claim may name a root with (design section 2)."""


def _check_wire_uri(uri: object, *, windows: bool | None = None) -> str:
    """Enforce the claim schema: an absolute URI with one of ``WIRE_SCHEMES``.

    Applied to every location in a claim before canonicalization. Bare paths
    (which ``ScopeRoot.parse`` accepts for the server's own ``log_dir``) and
    other schemes are refused so a malformed claim never binds to the
    server's working directory or an unexpected filesystem.
    """
    if not isinstance(uri, str) or not uri:
        raise ValueError("Scope uri must be a non-empty string")
    scheme, _ = _split_protocol(uri)
    if scheme is None or scheme.lower() not in WIRE_SCHEMES:
        raise ValueError(
            f"Scope uri must be an absolute file, s3, gs, az or http(s) URI: {uri}"
        )
    scheme = scheme.lower()
    windows = os.name == "nt" if windows is None else windows
    if scheme == "file":
        path = _local_path_from_file_uri(uri, windows=windows)
        if path is None or not (
            PureWindowsPath(path).is_absolute()
            if windows
            else PurePosixPath(path).is_absolute()
        ):
            raise ValueError(f"Scope file URI must name an absolute path: {uri}")
    elif scheme in ("http", "https"):
        if _parse_opaque_http_file(uri) is None:
            raise ValueError(f"Invalid scope http(s) URI: {uri}")
    elif _canonical_remote_path(uri) is None:
        raise ValueError(f"Invalid scope {scheme} URI: {uri}")
    return uri


def _parse_root(item: Any, *, windows: bool | None) -> ScopeRoot:
    if not isinstance(item, Mapping):
        raise ValueError("Scope root must be an object")
    uri = _check_wire_uri(item.get("uri"), windows=windows)
    return ScopeRoot.parse(
        uri, item.get("kind"), item.get("permissions", []), windows=windows
    )


def _check_permissions(permissions: Any) -> None:
    if not isinstance(permissions, list) or not all(
        isinstance(p, str) for p in permissions
    ):
        raise ValueError("Scope permissions must be a list of strings")
