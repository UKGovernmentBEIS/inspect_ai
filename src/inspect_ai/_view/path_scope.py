from __future__ import annotations

import os
import posixpath
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from fsspec.core import split_protocol  # type: ignore

VIEW_SCOPE_HEADER = "X-Inspect-View-Scope"
VIEW_SCOPE_KIND_HEADER = "X-Inspect-View-Scope-Kind"

PathScopeKind = Literal["directory", "file"]

_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class _RemotePath:
    scheme: str
    authority: str
    path: PurePosixPath
    query: str


@dataclass(frozen=True)
class PathScope:
    """Canonical filesystem or remote-object capability."""

    kind: PathScopeKind
    _local: Path | None
    _remote: _RemotePath | None

    @classmethod
    def parse(cls, kind: PathScopeKind, location: str) -> "PathScope":
        return cls._parse(kind, location, canonical_local=False)

    @classmethod
    def parse_canonical(cls, kind: PathScopeKind, location: str) -> "PathScope":
        """Parse a scope already canonicalized by a trusted host."""
        return cls._parse(kind, location, canonical_local=True)

    @classmethod
    def _parse(
        cls,
        kind: PathScopeKind,
        location: str,
        *,
        canonical_local: bool,
    ) -> "PathScope":
        local = _canonical_local_path(location, canonical=canonical_local)
        remote = None if local is not None else _canonical_remote_path(location)
        if local is None and remote is None:
            raise ValueError(f"Invalid viewer path scope: {location}")
        if kind == "directory" and remote:
            if remote.scheme in ("http", "https"):
                raise ValueError(
                    f"Unsupported viewer directory scheme: {remote.scheme}"
                )
            if remote.query:
                raise ValueError("Viewer directory scopes cannot contain a query")
        return cls(kind=kind, _local=local, _remote=remote)

    def allows(self, location: str) -> bool:
        if self._local is not None:
            candidate = _canonical_local_path(location)
            if candidate is None:
                return False
            if self.kind == "file":
                return candidate == self._local
            return candidate.is_relative_to(self._local)

        remote_candidate = _canonical_remote_path(location)
        if remote_candidate is None or self._remote is None:
            return False
        if (
            remote_candidate.scheme != self._remote.scheme
            or remote_candidate.authority != self._remote.authority
        ):
            return False
        if self.kind == "file":
            return (
                remote_candidate.path == self._remote.path
                and remote_candidate.query == self._remote.query
            )
        if remote_candidate.query:
            return False
        return remote_candidate.path.is_relative_to(self._remote.path)


def _canonical_local_path(
    location: str,
    *,
    canonical: bool = False,
) -> Path | None:
    if not location:
        return None
    if os.name == "nt" and _WINDOWS_DRIVE_PATH.match(location):
        protocol = None
    else:
        protocol, _ = split_protocol(location)

    if protocol is None:
        path = location
    elif protocol.lower() == "file":
        file_path = _local_path_from_file_uri(location)
        if file_path is None:
            return None
        path = file_path
    else:
        return None

    try:
        local = Path(path)
        if not canonical:
            return local.resolve()
        if not local.is_absolute() or ".." in local.parts:
            return None
        normalized = Path(os.path.normpath(path))
        if normalized != local or local.resolve() != local:
            return None
        return local
    except (OSError, RuntimeError, ValueError):
        return None


def _local_path_from_file_uri(
    location: str,
    *,
    windows: bool | None = None,
) -> str | None:
    windows = os.name == "nt" if windows is None else windows
    try:
        parsed = urllib.parse.urlsplit(location)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        return None

    decoded_path = urllib.parse.unquote(parsed.path)
    if "\\" in decoded_path:
        return None

    authority = parsed.hostname or ""
    if authority and authority.lower() != "localhost":
        if not windows or not decoded_path.startswith("/"):
            return None
        if len(PurePosixPath(decoded_path).parts) < 2:
            return None
        return str(PureWindowsPath(f"//{authority}{decoded_path}"))

    if (
        windows
        and decoded_path.startswith("/")
        and len(decoded_path) > 3
        and decoded_path[2] == ":"
    ):
        return decoded_path[1:]
    return decoded_path


def _canonical_remote_path(location: str) -> _RemotePath | None:
    protocol, _ = split_protocol(location)
    if protocol is None or protocol.lower() == "file":
        return None

    try:
        parsed = urllib.parse.urlsplit(location)
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

    decoded_path = urllib.parse.unquote(parsed.path)
    if "\\" in decoded_path or ".." in PurePosixPath(decoded_path).parts:
        return None
    path = posixpath.normpath("/" + decoded_path.lstrip("/"))
    return _RemotePath(
        scheme=protocol.lower(),
        authority=parsed.netloc.lower(),
        path=PurePosixPath(path),
        query=parsed.query,
    )
