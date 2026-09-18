"""The root-only in-sandbox work area the checkpoint strategies share.

Both strategies keep what they later trust inside the sandbox under one
root-only directory (``/root/.cache/inspect`` by default): the injected
restic binary and the in-sandbox repo, egress staging, and the archive
strategy's tar staging. This module is the one place that prepares it.
"""

from __future__ import annotations

from inspect_ai.util._sandbox._framework_directory import ensure_framework_directory
from inspect_ai.util._sandbox.environment import SandboxEnvironment


async def ensure_root_sandbox_dir(env: SandboxEnvironment, path: str) -> None:
    """Create or adopt ``path`` as root's private (mode 0700) directory in ``env``.

    A bare ``install -d -m 0700`` adopts whatever entry already sits at
    ``path`` (a symlink, a directory another user planted) and the caller
    then trusts it. This goes through :func:`ensure_framework_directory`
    instead: the directory is created, or an existing entry is accepted
    only if it is a real directory owned by uid 0 in mode 0700 under a
    parent no other principal can modify. Anything else fails the setup
    or restore that needed the directory, since checkpointing has no
    rootless mode to fall back to: a contract violation raises
    ``FrameworkDirectoryError``, a check that could not be performed
    (no ``stat`` or ``id`` in the image) ``FrameworkDirectoryUnavailableError``,
    and a script that ran as another uid ``FrameworkDirectoryUserError``,
    all ``RuntimeError`` subclasses. ``expected_uid=0`` makes a provider
    that ignores ``user="root"`` fail that way rather than stage
    root-trusted content in a directory the default user owns.

    Only the immediate parent is checked, so ``path`` must sit under
    root-owned ancestors that others cannot write to. The default
    ``/root/.cache/inspect`` qualifies; a caller that points a strategy at
    another ``sandbox_dir`` takes on that requirement.
    """
    await ensure_framework_directory(env, path, user="root", expected_uid=0)
