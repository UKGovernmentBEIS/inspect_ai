"""LFS pointer file detection and parsing."""

import re
from dataclasses import dataclass
from pathlib import Path

LFS_POINTER_VERSION = "version https://git-lfs.github.com/spec/v1"
_OID_PATTERN = re.compile(r"^oid sha256:([0-9a-f]{64})$")


@dataclass(frozen=True)
class LFSPointer:
    """Parsed LFS pointer file."""

    oid: str
    """SHA-256 content hash (64 hex characters)."""

    size: int
    """File size in bytes."""


def is_lfs_pointer(file_path: Path) -> bool:
    """Check if a file is an LFS pointer.

    Reads only the first line to minimize I/O.
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            first_line = f.readline().rstrip("\n")
        return first_line == LFS_POINTER_VERSION
    except (OSError, UnicodeDecodeError):
        return False


def parse_lfs_pointer(file_path: Path) -> LFSPointer | None:
    """Parse an LFS pointer file.

    Returns:
        Parsed pointer, or None if the file is not a valid LFS pointer.
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    return _parse_pointer_text(text)


def _parse_pointer_text(text: str) -> LFSPointer | None:
    """Parse LFS pointer content from a string."""
    lines = text.strip().splitlines()
    if len(lines) < 3:
        return None

    if lines[0] != LFS_POINTER_VERSION:
        return None

    oid_match = _OID_PATTERN.match(lines[1])
    if not oid_match:
        return None

    size_prefix = "size "
    if not lines[2].startswith(size_prefix):
        return None

    try:
        size = int(lines[2][len(size_prefix) :])
    except ValueError:
        return None

    if size < 0:
        return None

    return LFSPointer(oid=oid_match.group(1), size=size)
