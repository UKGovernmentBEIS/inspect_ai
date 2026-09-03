"""Post-restore validation of a restic-restored tree.

A restic repo the host restores from is untrusted input: the resume
source is whatever its last writer put there, and a repo that opens
cleanly says nothing about who wrote it (the password is a restic
requirement, not an authenticity check). Restic faithfully recreates
whatever the snapshot holds — symlinks included — so a restored tree
must be validated before anything walks or opens it with
symlink-following primitives.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import NamedTuple


class RestoredTreeError(RuntimeError):
    """A restored tree violates the regular-files-only contract."""


class TreeStats(NamedTuple):
    """Counts observed by :func:`verify_regular_tree`."""

    files: int
    bytes: int


def verify_regular_tree(
    root: str | Path, *, max_files: int, max_bytes: int
) -> TreeStats:
    """Verify ``root`` holds only regular files and directories, within bounds.

    Walks with ``os.scandir`` and ``lstat`` — never following symlinks —
    and rejects the first entry that is not a regular file or directory
    (symlink, FIFO, socket, device), any entry whose real path falls
    outside ``root``, more than ``max_files`` entries (files and
    directories together, so a forest of empty directories is bounded
    too), or more than ``max_bytes`` of file content in total. A
    directory is descended only after its own ``lstat`` reports a real
    directory, so a directory symlink is rejected rather than traversed;
    the real-path containment check is belt-and-braces over that.

    Returns the file and byte counts seen (a legitimate restore has at
    least one file — callers decide whether zero is an error).

    Raises:
        RestoredTreeError: on any violation, naming the offending path.
    """
    root_path = Path(root)
    if not stat.S_ISDIR(os.lstat(root_path).st_mode):
        raise RestoredTreeError(f"restored tree root is not a directory: {root_path}")
    root_real = os.path.realpath(root_path)

    entries = 0
    files = 0
    total = 0
    pending = [root_path]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as scan:
            for entry in scan:
                st = entry.stat(follow_symlinks=False)
                mode = st.st_mode
                if stat.S_ISLNK(mode):
                    raise RestoredTreeError(
                        f"restored tree contains a symlink: {entry.path}"
                    )
                if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    raise RestoredTreeError(
                        f"restored tree contains a non-regular entry "
                        f"({stat.filemode(mode)}): {entry.path}"
                    )
                real = os.path.realpath(entry.path)
                if os.path.commonpath([root_real, real]) != root_real:
                    raise RestoredTreeError(
                        f"restored tree entry escapes {root_path}: {entry.path}"
                    )
                entries += 1
                if entries > max_files:
                    raise RestoredTreeError(
                        f"restored tree exceeds {max_files} entries under {root_path}"
                    )
                if stat.S_ISDIR(mode):
                    pending.append(Path(entry.path))
                    continue
                files += 1
                total += st.st_size
                if total > max_bytes:
                    raise RestoredTreeError(
                        f"restored tree exceeds {max_bytes} bytes under {root_path}"
                    )
    return TreeStats(files=files, bytes=total)
