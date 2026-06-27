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


def canonical_path_location(location: str) -> str | None:
    """Resolve a local or remote location to the value used for filesystem I/O."""
    opaque_http = _parse_opaque_http_file(location)
    if opaque_http is not None:
        return opaque_http.location
    local = _canonical_local_path(location)
    if local is not None:
        return str(local)
    remote = _canonical_remote_path(location)
    return remote.location() if remote is not None else None


@dataclass(frozen=True)
class _RemotePath:
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
    scheme: str
    authority: str
    location: str


@dataclass(frozen=True)
class PathScope:
    """Canonical filesystem or remote-object capability."""

    kind: PathScopeKind
    _local: Path | None
    _remote: _RemotePath | None
    _opaque_http: _OpaqueHttpFile | None

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
        opaque_http = _parse_opaque_http_file(location) if kind == "file" else None
        local = _canonical_local_path(location, canonical=canonical_local)
        remote = (
            None
            if local is not None or opaque_http is not None
            else _canonical_remote_path(location)
        )
        if local is None and remote is None and opaque_http is None:
            raise ValueError(f"Invalid viewer path scope: {location}")
        if kind == "directory" and remote:
            if remote.scheme in ("http", "https"):
                raise ValueError(
                    f"Unsupported viewer directory scheme: {remote.scheme}"
                )
            if remote.query:
                raise ValueError("Viewer directory scopes cannot contain a query")
        return cls(
            kind=kind,
            _local=local,
            _remote=remote,
            _opaque_http=opaque_http,
        )

    def resolve(self, location: str) -> str | None:
        """Resolve an allowed location to the exact URI used for I/O."""
        if self._opaque_http is not None:
            opaque_candidate = _parse_opaque_http_file(location)
            return (
                self._opaque_http.location
                if opaque_candidate is not None
                and opaque_candidate.location == self._opaque_http.location
                else None
            )

        if self._local is not None:
            local_candidate = _canonical_local_path(location)
            if local_candidate is None:
                return None
            if self.kind == "file":
                return str(local_candidate) if local_candidate == self._local else None
            return (
                str(local_candidate)
                if local_candidate.is_relative_to(self._local)
                else None
            )

        remote_candidate = _canonical_remote_path(location)
        if remote_candidate is None or self._remote is None:
            return None
        if (
            remote_candidate.scheme != self._remote.scheme
            or remote_candidate.authority != self._remote.authority
        ):
            return None
        if self.kind == "file":
            allowed = (
                remote_candidate.path == self._remote.path
                and remote_candidate.query == self._remote.query
            )
            return remote_candidate.location() if allowed else None
        if remote_candidate.query:
            return None
        return (
            remote_candidate.location()
            if remote_candidate.path.is_relative_to(self._remote.path)
            else None
        )

    def allows(self, location: str) -> bool:
        return self.resolve(location) is not None


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
    if (
        "\\" in decoded_path
        or "?" in decoded_path
        or "#" in decoded_path
        or ".." in PurePosixPath(decoded_path).parts
    ):
        return None
    path = posixpath.normpath("/" + decoded_path.lstrip("/"))
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
    for field in query.split("&"):
        if "=" in field:
            name, value = field.split("=", 1)
            fields.append(f"{encode(name)}={encode(value)}")
        else:
            fields.append(encode(field))
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
        scheme=parsed.scheme.lower(),
        authority=parsed.netloc.lower(),
        location=location,
    )
