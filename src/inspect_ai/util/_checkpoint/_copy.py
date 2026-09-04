"""Bounded, chunked sandbox → host file copy.

The shared copy-out primitive for sandbox snapshot strategies (design
§8): a file produced inside the sandbox's root-only area is copied to
the host in fixed-size chunks (``dd`` per chunk + ``read_file``), so
host RAM is bounded by one chunk regardless of file size, and the host
enforces a hard cap on the bytes it will accept — the sandbox-reported
size is advisory, the cap is checked against bytes actually read and
the copy aborts mid-transfer once it is exceeded.

Lives at the ``_checkpoint`` level rather than under ``_snapshot/``
because ``_snapshot/__init__`` imports the strategies, which import
``_sandbox_restic``, which needs this module — placing it under
``_snapshot/`` would make that a cycle.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import NamedTuple

from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.limits import override_max_read_file_size

DEFAULT_COPY_CHUNK_SIZE = 8 * 1024 * 1024

DD_FULLBLOCK_PROBE = (
    "dd if=/dev/null of=/dev/null bs=1 count=0 iflag=fullblock >/dev/null 2>&1"
)
"""Shell probe for ``dd iflag=fullblock`` (GNU/busybox; absent on BSD dd)."""


class CopyOutResult(NamedTuple):
    """What ``copy_out`` verified about the bytes it landed on the host."""

    sha256: str
    """Digest of the bytes actually read from the sandbox."""

    size: int
    """Bytes actually read (equals the reported size on success)."""


def copy_out_partial_path(dest: Path) -> Path:
    """The in-flight file ``copy_out`` writes before renaming to ``dest``.

    ``<dir>/.<name>.partial`` — hidden, beside ``dest``. A ``dest`` whose
    name is already hidden gets no second leading dot, so residue from a
    hard kill (SIGKILL, OOM) stays hidden beside ``dest`` where a
    caller's sweep looks for it.
    """
    name = dest.name if dest.name.startswith(".") else f".{dest.name}"
    return dest.with_name(f"{name}.partial")


async def probe_dd_fullblock(env: SandboxEnvironment) -> bool:
    """Whether the sandbox's ``dd`` supports ``iflag=fullblock``.

    Without it a short read (fuse/9p-backed filesystems) desyncs the
    block-indexed ``skip`` from the bytes actually copied, dropping data
    — which the caller's digest or content checks then reject loudly,
    so the flag is an optimization for robustness, not a correctness
    requirement.
    """
    result = await env.exec(["sh", "-c", DD_FULLBLOCK_PROBE], user="root")
    return result.success


async def copy_out(
    env: SandboxEnvironment,
    *,
    src: str,
    chunk_path: str,
    size: int,
    dest: Path,
    max_bytes: int,
    label: str,
    chunk_size: int = DEFAULT_COPY_CHUNK_SIZE,
    dd_fullblock: bool = False,
    expected_sha256: str | None = None,
) -> CopyOutResult:
    """Copy the in-sandbox file ``src`` to the host path ``dest`` in chunks.

    ``size`` is the sandbox-reported byte count; it drives the chunk
    loop but is untrusted: the copy fails before the first read when
    ``size`` exceeds ``max_bytes``, and aborts mid-transfer if the bytes
    actually read would exceed either ``max_bytes`` or ``size``. Each
    chunk is produced by ``dd`` into ``chunk_path`` (inside the
    sandbox's root-only area) and read back with ``read_file``.

    Written to :func:`copy_out_partial_path` and renamed into place only
    after the copy completes (and, when ``expected_sha256`` is given,
    the digest of the bytes actually read matches it), so an
    interrupted, over-cap, or corrupted copy — including cancellation
    mid-transfer — never leaves a plausible-looking file at ``dest``.
    Only a hard kill can leave the partial file behind; callers that
    care sweep it by that name. ``label`` prefixes error messages.
    """
    if size < 0:
        raise RuntimeError(f"{label}: sandbox reported a negative size ({size})")
    if size > max_bytes:
        raise RuntimeError(
            f"{label}: sandbox-reported size {size} bytes exceeds the "
            f"max_sandbox_snapshot_bytes cap of {max_bytes} bytes"
        )
    digest = hashlib.sha256()
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = copy_out_partial_path(dest)
    try:
        with open(partial, "wb") as out:
            index = 0
            copied = 0
            while copied < size:
                script = (
                    f"rm -f {chunk_path} && dd if={src} of={chunk_path} "
                    f"bs={chunk_size} skip={index} count=1 "
                    f"{'iflag=fullblock ' if dd_fullblock else ''}"
                    f"2>/dev/null"
                )
                result = await env.exec(["sh", "-c", script], user="root")
                if not result.success:
                    raise RuntimeError(f"{label}: chunk copy failed: {result.stderr}")
                with override_max_read_file_size(chunk_size * 2):
                    data = await env.read_file(chunk_path, text=False)
                if not data:
                    raise RuntimeError(
                        f"{label}: unexpected EOF at chunk {index} "
                        f"({copied}/{size} bytes)"
                    )
                copied += len(data)
                if copied > max_bytes:
                    raise RuntimeError(
                        f"{label}: transfer exceeded the max_sandbox_snapshot_bytes "
                        f"cap of {max_bytes} bytes (aborted after {copied} bytes)"
                    )
                if copied > size:
                    raise RuntimeError(
                        f"{label}: read {copied} bytes but the sandbox reported {size}"
                    )
                out.write(data)
                digest.update(data)
                index += 1
        if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
            raise RuntimeError(
                f"{label}: corrupted in transit: in-sandbox sha256 "
                f"{expected_sha256} != host-read sha256 {digest.hexdigest()}"
            )
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    os.replace(partial, dest)
    return CopyOutResult(sha256=digest.hexdigest(), size=copied)
