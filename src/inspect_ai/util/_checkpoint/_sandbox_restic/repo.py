"""Restic in a sandbox: inject the binary, init the repo, run backups.

Couples ``inspect_ai``'s :class:`SandboxEnvironment` abstraction to the
generic :mod:`.._restic` operations: the binary is shipped into a
root-only path inside the sandbox so the agent (running as non-root)
cannot see, stat, or execute it.

Layout under ``/opt/inspect-restic/`` (root-only, mode 0700):
- ``./restic`` — the binary itself
- ``./repo`` — the in-sandbox restic repo

The egress protocol that ships repo data back to the host lives in
:mod:`.egress` and shares this layout.
"""

from __future__ import annotations

from inspect_ai.util._restic import Platform, ResticBackupSummary, resolve_restic
from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.recon import Architecture, detect_sandbox_os

_SANDBOX_RESTIC_DIR = "/opt/inspect-restic"
_SANDBOX_RESTIC_PATH = f"{_SANDBOX_RESTIC_DIR}/restic"
_SANDBOX_RESTIC_REPO = f"{_SANDBOX_RESTIC_DIR}/repo"

_ARCH_TO_PLATFORM: dict[Architecture, Platform] = {
    "amd64": "linux_amd64",
    "arm64": "linux_arm64",
}


async def inject_restic(env: SandboxEnvironment) -> None:
    """Inject a linux restic binary into the sandbox at the root-only path.

    Streams the binary bytes via stdin to a root ``sh`` invocation so
    the binary never lands at a non-root-readable temp path; the agent
    can't observe it in flight or after. The parent directory is mode
    0700 so the file is invisible to non-root processes (stronger than
    file-level ``chmod 0700`` alone, since the file would otherwise still
    appear in ``ls`` of a world-readable parent).
    """
    info = await detect_sandbox_os(env)
    platform = _ARCH_TO_PLATFORM[info["architecture"]]
    binary_path = await resolve_restic(platform)
    binary_bytes = binary_path.read_bytes()

    script = (
        "set -e; "
        f"install -d -m 0700 {_SANDBOX_RESTIC_DIR}; "
        f"cat > {_SANDBOX_RESTIC_PATH}; "
        f"chmod 0700 {_SANDBOX_RESTIC_PATH}"
    )
    result = await env.exec(["sh", "-c", script], input=binary_bytes, user="root")
    if not result.success:
        raise RuntimeError(f"Failed to inject restic into sandbox: {result.stderr}")


async def init_sandbox_repo(env: SandboxEnvironment, password: str) -> None:
    """Initialize a restic repo inside the sandbox (idempotent).

    Runs as root against the injected binary. Skip if the repo is
    already initialized.
    """
    check = await env.exec(
        ["test", "-e", f"{_SANDBOX_RESTIC_REPO}/config"], user="root"
    )
    if check.success:
        return
    result = await env.exec(
        [_SANDBOX_RESTIC_PATH, "-r", _SANDBOX_RESTIC_REPO, "init"],
        env={"RESTIC_PASSWORD": password},
        user="root",
    )
    if not result.success:
        raise RuntimeError(f"Failed to init sandbox restic repo: {result.stderr}")


async def run_sandbox_backup(
    env: SandboxEnvironment,
    password: str,
    paths: list[str],
    tag: str,
    exclude: list[str] | None = None,
) -> ResticBackupSummary:
    """Run ``restic backup`` inside the sandbox; return the parsed summary.

    ``--compression max`` (zstd level 22) for parity with the host
    backup. Mixed sandbox content (text, configs, sometimes binaries)
    benefits less than pure JSON, but the per-cycle CPU cost is small
    relative to the network/IO savings on the egress path. ``exclude``
    paths become ``--exclude`` patterns (used to drop the XDG cache dir
    in auto-home mode); a pattern matching nothing is a harmless no-op.
    """
    cmd = [
        _SANDBOX_RESTIC_PATH,
        "-r",
        _SANDBOX_RESTIC_REPO,
        "backup",
        *paths,
        *[arg for path in (exclude or []) for arg in ("--exclude", path)],
        "--compression",
        "max",
        "--tag",
        tag,
        "--json",
    ]
    result = await env.exec(cmd, env={"RESTIC_PASSWORD": password}, user="root")
    if not result.success:
        raise RuntimeError(f"sandbox restic backup failed: {result.stderr}")
    return ResticBackupSummary.from_stdout(result.stdout)
