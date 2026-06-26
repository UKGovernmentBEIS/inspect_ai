from __future__ import annotations

import os
import posixpath
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
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


@dataclass(frozen=True)
class PathScope:
    """Canonical filesystem or remote-object capability."""

    kind: PathScopeKind
    _local: Path | None
    _remote: _RemotePath | None

    @classmethod
    def parse(cls, kind: PathScopeKind, location: str) -> "PathScope":
        local = _canonical_local_path(location)
        remote = None if local is not None else _canonical_remote_path(location)
        if local is None and remote is None:
            raise ValueError(f"Invalid viewer path scope: {location}")
        if kind == "directory" and remote and remote.scheme in ("http", "https"):
            raise ValueError(f"Unsupported viewer directory scheme: {remote.scheme}")
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
            return remote_candidate.path == self._remote.path
        return remote_candidate.path.is_relative_to(self._remote.path)


def _canonical_local_path(location: str) -> Path | None:
    if not location:
        return None
    if os.name == "nt" and _WINDOWS_DRIVE_PATH.match(location):
        protocol = None
    else:
        protocol, _ = split_protocol(location)

    if protocol is None:
        path = location
    elif protocol.lower() == "file":
        try:
            parsed = urllib.parse.urlsplit(location)
        except ValueError:
            return None
        if (
            parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
            or parsed.netloc.lower() not in ("", "localhost")
        ):
            return None
        path = urllib.parse.unquote(parsed.path)
        if (
            os.name == "nt"
            and path.startswith("/")
            and len(path) > 3
            and path[2] == ":"
        ):
            path = path[1:]
    else:
        return None

    try:
        return Path(path).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


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
        or parsed.query
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
    )
