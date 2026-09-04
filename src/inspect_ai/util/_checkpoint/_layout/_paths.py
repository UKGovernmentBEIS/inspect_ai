"""Containment of external strings that become host path components.

Two kinds of externally supplied string end up joined onto host paths
by the checkpointing code:

- **Remote object keys** enumerated from a resume source (an S3 prefix
  the eval reads back on retry). ``iter_files`` yields them verbatim,
  so a key may carry ``..`` segments or a double slash (an absolute
  remainder makes ``Path`` discard the join root entirely).
- **Dataset-supplied sample ids**, interpolated into the per-sample
  checkpoints and staging dir names. An id containing ``/`` or ``..``
  would relocate the whole per-sample tree.

Every such site routes through the pure functions here so that a
hostile or corrupt string fails loudly (or is rewritten to a safe
single segment) instead of becoming a traversal.
"""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath

from inspect_ai._util.file import safe_filename

_MAX_PASSTHROUGH_BYTES = 200
"""Longest id (UTF-8 bytes) that passes through unchanged.

Callers append ``__<epoch>`` to the segment, and the common NAME_MAX is
255 bytes; a longer id is hashed rather than failing ``mkdir`` with
``ENAMETOOLONG``."""

_SAFE_PREFIX_LEN = 64
_HASH_LEN = 12
_HASH_JOINER = "~"
"""Joins the safe prefix to the hash digest in a rewritten segment.

Reserved: an id containing it never passes through, so the passthrough
and hashed namespaces are disjoint and an id that literally equals
another id's hashed form cannot pass through to the same dir.
Unreserved in URLs and valid in POSIX and Windows filenames; the segment
never starts with it, so no shell tilde expansion applies."""


def contained_component(name: str) -> str:
    """Validate ``name`` as one path component that stays inside its parent.

    Accepts a non-empty string that is not ``.`` or ``..`` and contains
    no path separator (forward slash, or backslash because a Windows host
    ``Path`` would honor it) and no NUL. Returns ``name`` unchanged.

    Raises:
        ValueError: naming the offending component.
    """
    if name == "":
        raise ValueError("path component is empty")
    if name in (".", ".."):
        raise ValueError(f"path component {name!r} is not allowed")
    if "/" in name or "\\" in name:
        raise ValueError(f"path component {name!r} contains a separator")
    if "\x00" in name:
        raise ValueError(f"path component {name!r} contains NUL")
    return name


def contained_relative(rel: str) -> PurePosixPath:
    """Validate ``rel`` as a relative path that cannot escape its join root.

    Accepts ``rel`` only if it is not absolute and every ``/``-separated
    component satisfies :func:`contained_component` (non-empty, not
    ``.`` or ``..``, no separator, no NUL). An empty component (from a
    leading, trailing or doubled slash) is rejected rather than
    normalized away: a doubled slash in a remote key is exactly the
    shape that turns the remainder absolute.

    Raises:
        ValueError: naming the offending component.
    """
    if rel == "":
        raise ValueError("path is empty")
    if rel.startswith("/"):
        raise ValueError(f"path {rel!r} is absolute")
    for component in rel.split("/"):
        try:
            contained_component(component)
        except ValueError as exc:
            raise ValueError(f"path {rel!r} is not contained: {exc}") from exc
    return PurePosixPath(rel)


def sample_dir_segment(sample_id: int | str) -> str:
    """Return the single directory-name segment for a sample id.

    An id whose ``str()`` is a single path component (per
    :func:`contained_component`), does not contain the reserved ``~``,
    and is at most 200 UTF-8 bytes passes through unchanged, so such an
    id keeps its name and its existing checkpoint dirs stay resumable.
    Anything else (an id with a slash, a backslash, NUL or ``~``, an
    empty id, ``.``/``..``, or an id over 200 bytes, even one that
    previously fit under NAME_MAX) becomes
    ``safe_filename(id)[:64] + "~" + sha256(id)[:12]``:
    deterministic, collision resistant, bounded in length, ASCII, and
    never a traversal. The ``~`` joiner is what keeps the two namespaces
    disjoint: a hashed segment can never equal the passthrough segment
    of some other id.

    Both the write path (``ensure_sample_checkpoints_dir``) and the
    resume lookup (``has_sample_checkpoint`` / ``sample_checkpoints_dir``)
    derive the dir name here, so they agree by construction.
    """
    text = str(sample_id)
    if _is_passthrough_segment(text):
        return text
    encoded = text.encode("utf-8", "surrogatepass")
    digest = hashlib.sha256(encoded).hexdigest()
    # The prefix exists only for readability: `safe_filename` keeps a
    # leading `-`/`_` and prepends `_` to a hidden name, so strip that
    # debris (e.g. `../../escape` reads `escape~<hash>`, not `_.._.._escape~...`).
    prefix = safe_filename(text).lstrip("._-")
    return f"{prefix[:_SAFE_PREFIX_LEN] or 'id'}{_HASH_JOINER}{digest[:_HASH_LEN]}"


def _is_passthrough_segment(text: str) -> bool:
    if _HASH_JOINER in text:
        return False
    if len(text.encode("utf-8", "surrogatepass")) > _MAX_PASSTHROUGH_BYTES:
        return False
    try:
        contained_component(text)
    except ValueError:
        return False
    return True
