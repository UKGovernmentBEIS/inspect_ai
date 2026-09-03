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

Every such site routes through the two pure functions here so that a
hostile or corrupt string fails loudly (or is rewritten to a safe
single segment) instead of becoming a traversal.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath

from inspect_ai._util.file import safe_filename

_PASSTHROUGH_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
"""Sample ids that are already a safe single dir segment.

Requiring a leading alphanumeric excludes ``.``, ``..``, hidden names
and dash-leading names (which read as flags to CLI tools)."""

_LEADING_NON_ALNUM_RE = re.compile(r"^[^A-Za-z0-9]+")
"""``safe_filename`` keeps a leading ``-``; the rewritten segment must
satisfy the same leading-alphanumeric rule as the passthrough set."""

_SAFE_PREFIX_LEN = 64
_HASH_LEN = 12


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

    An id whose ``str()`` matches ``^[A-Za-z0-9][A-Za-z0-9._-]*$`` (every
    non-negative int, and plain-filename strings) passes through
    unchanged so existing checkpoint dirs for such ids keep their names
    and stay resumable. Anything else, including a negative int, becomes
    ``safe_filename(id)[:64] + "-" + sha256(id)[:12]`` (with any leading
    non-alphanumerics dropped from the prefix): deterministic, collision
    resistant, bounded in length, and never a traversal.

    Both the write path (``ensure_sample_checkpoints_dir``) and the
    resume lookup (``has_sample_checkpoint`` / ``sample_checkpoints_dir``)
    derive the dir name here, so they agree by construction.
    """
    text = str(sample_id)
    if _PASSTHROUGH_ID_RE.fullmatch(text):
        return text
    digest = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
    prefix = _LEADING_NON_ALNUM_RE.sub("", safe_filename(text))
    return f"{prefix[:_SAFE_PREFIX_LEN] or 'id'}-{digest[:_HASH_LEN]}"
