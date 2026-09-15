"""Resolve the effective per-sandbox backup paths for a sample.

Every live sandbox has its default-user home directory captured by
default. ``sandbox_paths`` in the checkpoint config overrides that default
per sandbox name: a non-empty entry replaces the home dir with the listed
paths, and an explicit empty-list entry opts a sandbox out entirely.

Cache directories are never backed up: every sandbox's backup excludes the
default user's XDG cache dir (``$XDG_CACHE_HOME`` or ``$HOME/.cache``) and
any ``.cache`` directory anywhere in the tree (``**/.cache``) — even when
the include paths are user-specified. The user controls only what's
*included*; caches are always dropped so they don't bloat the backup.

The include set is also what a resume is allowed to write (see
``_restore_scope``), so it is checked here — at sample provisioning,
before the first checkpoint — against the same rules the restore applies:
every root must be an absolute path other than ``/``. A capture whose
roots can never be restored would otherwise succeed at every checkpoint
and fail only when a retry tries to resume. An auto-included home that
fails the check is skipped, and reported separately
(:attr:`ResolvedBackupPaths.unscopable`) so the resume-time strategy pin
check can tell a permanently unscopable home from a transient resolution
failure.
"""

from dataclasses import dataclass, field
from logging import getLogger
from typing import NamedTuple

from inspect_ai.util._sandbox._privileged import privileged_shell
from inspect_ai.util._sandbox.context import sandbox_environments_context_var
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from ._restore_scope import RestoreRoots, RestoreScopeError

logger = getLogger(__name__)

_CACHE_GLOB = "**/.cache"
"""restic exclude pattern matching any ``.cache`` directory at any depth."""


@dataclass(frozen=True)
class SandboxBackupPaths:
    """Effective backup paths for one sandbox: what to capture, what to skip."""

    include: list[str]
    """Absolute source paths passed to ``restic backup``."""

    exclude: list[str] = field(default_factory=list)
    """Absolute paths passed as ``restic backup --exclude`` (the default
    user's XDG cache dir and ``**/.cache``)."""

    home: str | None = None
    """The default user's home dir when it *is* the include set (no
    ``sandbox_paths`` entry for this sandbox); ``None`` when ``include``
    was configured explicitly. On resume the core re-owns everything
    restored under an auto-included home to the home dir's owner."""


class ResolvedBackupPaths(NamedTuple):
    """Result of :func:`resolve_sandbox_backup_paths`."""

    paths: dict[str, SandboxBackupPaths]
    """Sandbox name → effective backup paths, for every backed-up sandbox."""

    unscopable: dict[str, str]
    """Sandbox name → reason, for each auto-home sandbox skipped because
    its home dir cannot be scoped for restore (an image with ``HOME=/``).
    Unlike an unresolvable home this is a property of the image, not a
    transient failure, so a resume that finds such a sandbox pinned
    reports it with its own remedy."""


async def resolve_sandbox_backup_paths(
    config_paths: dict[str, list[str]],
) -> ResolvedBackupPaths:
    """Effective per-sandbox backup paths for the current sample.

    Include set, for each live sandbox:

    - name with a non-empty ``config_paths`` entry → those paths verbatim.
    - name with an empty-list entry → excluded (explicit opt-out, no repo).
    - name with no entry → the default user's home directory.

    Exclude set (applied to every backed-up sandbox, configured or not):
    the default user's XDG cache dir and ``**/.cache`` — caches are never
    backed up regardless of the include set.

    Every include set must be restorable (``RestoreRoots.from_include``):
    absolute paths, none of them ``/``. A configured entry that is not
    raises :class:`RestoreScopeError` — a configuration error, surfaced
    before any checkpoint is taken. An auto-home sandbox whose home dir
    can't be resolved, or resolves to a path that can't be scoped (an
    image with ``HOME=/``), is skipped with a warning rather than failing
    the checkpoint; the latter is also returned in ``unscopable``.
    """
    envs = sandbox_environments_context_var.get(None) or {}
    resolved: dict[str, SandboxBackupPaths] = {}
    unscopable: dict[str, str] = {}
    for name, env in envs.items():
        configured = config_paths.get(name)
        if configured is not None and not configured:
            continue  # explicit opt-out → no sandbox repo

        # Resolve home/cache for every backed-up sandbox: home for the
        # auto-include default, the cache dir for the always-on exclude.
        home, cache = await _resolve_home_and_cache(env)
        if configured:
            include = configured
            RestoreRoots.from_include(
                include, label=f"checkpoint: sandbox_paths for sandbox {name!r}"
            )
        elif home:
            include = [home]
            try:
                RestoreRoots.from_include(
                    include, label=f"checkpoint: home dir of sandbox {name!r}"
                )
            except RestoreScopeError as exc:
                logger.warning(f"{exc}; skipping sandbox backup for it")
                unscopable[name] = str(exc)
                continue
        else:
            logger.warning(
                f"checkpoint: could not resolve home dir for sandbox "
                f"{name!r}; skipping sandbox backup for it"
            )
            continue

        exclude = ([cache] if cache else []) + [_CACHE_GLOB]
        resolved[name] = SandboxBackupPaths(
            include=include, exclude=exclude, home=None if configured else home
        )
    return ResolvedBackupPaths(paths=resolved, unscopable=unscopable)


async def _resolve_home_and_cache(
    env: SandboxEnvironment,
) -> tuple[str | None, str | None]:
    """Default user's home dir and XDG cache dir inside ``env``.

    Runs as the sandbox's default user (``user=None``). Prefers
    ``getent passwd`` for the home (works even when ``$HOME`` is unset in a
    non-login shell), falling back to ``$HOME``; the cache dir is
    ``$XDG_CACHE_HOME`` or ``<home>/.cache`` per the XDG Base Directory
    spec. Returns ``(None, None)`` if the home can't be resolved.
    """
    result = await privileged_shell(
        env,
        'h=$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f6); '
        '[ -n "$h" ] || h="$HOME"; '
        'echo "$h"; printf %s "${XDG_CACHE_HOME:-$h/.cache}"',
        user=None,
    )
    lines = result.stdout.split("\n") if result.success else []
    home = lines[0].strip() if lines else ""
    cache = lines[1].strip() if len(lines) > 1 else ""
    if not home:
        return None, None
    return home, (cache or None)
