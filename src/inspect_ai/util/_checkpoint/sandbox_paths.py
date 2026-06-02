"""Resolve the effective per-sandbox backup paths for a sample.

``sandbox_paths`` in the checkpoint config is an explicit, opt-in map of
sandbox name → absolute paths to capture. This module layers a default on
top: any sandbox *without* an entry has its default-user home directory
captured automatically. An explicit empty-list entry opts a sandbox out.
"""

from logging import getLogger

from inspect_ai.util._sandbox.context import sandbox_environments_context_var
from inspect_ai.util._sandbox.environment import SandboxEnvironment

logger = getLogger(__name__)


async def resolve_sandbox_backup_paths(
    config_paths: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Effective per-sandbox backup paths for the current sample.

    For each live sandbox:

    - name with a non-empty ``config_paths`` entry → those paths verbatim.
    - name with an empty-list entry → excluded (explicit opt-out).
    - name with no entry → the default user's home directory.

    A sandbox whose home dir can't be resolved (and has no entry) is
    skipped with a warning rather than failing the checkpoint.
    """
    envs = sandbox_environments_context_var.get(None) or {}
    resolved: dict[str, list[str]] = {}
    for name, env in envs.items():
        if name in config_paths:
            paths = config_paths[name]
            if paths:
                resolved[name] = paths
            # empty list → explicit opt-out → skip
        else:
            home = await _resolve_default_home(env)
            if home:
                resolved[name] = [home]
            else:
                logger.warning(
                    f"checkpoint: could not resolve home dir for sandbox "
                    f"{name!r}; skipping sandbox backup for it"
                )
    return resolved


async def _resolve_default_home(env: SandboxEnvironment) -> str | None:
    """Default user's home dir inside ``env`` (``None`` if unresolvable).

    Runs as the sandbox's default user (``user=None``). Prefers
    ``getent passwd`` (works even when ``$HOME`` is unset in a non-login
    shell), falling back to ``$HOME``.
    """
    result = await env.exec(
        [
            "sh",
            "-c",
            'h=$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f6); '
            '[ -n "$h" ] || h="$HOME"; printf %s "$h"',
        ]
    )
    home = result.stdout.strip() if result.success else ""
    return home or None
