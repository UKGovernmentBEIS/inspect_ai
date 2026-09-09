"""Run host-issued sandbox commands without consulting the image's ``PATH``.

Inspect issues commands inside sandboxes with authority the agent does not have:
as ``root`` (installing tools, snapshotting for checkpoints) or as the sandbox
default user, which is root in most images even when the agent's own tools run as
someone else. The provider resolves a bare command name (``sh``, ``rm``, ``tar``)
through the *image's* configured ``PATH`` before anything of ours runs, so an image
that puts a default-user-writable directory ahead of the system directories (a
``~/.local/bin`` set up for ``pip install --user``, say) lets the agent plant a
forged utility and have it executed with that authority on the next host command.

This module is the one place that knows how to avoid that. Every helper here:

- launches the shell by absolute path (:data:`SHELL_PATH`), because that is the
  only name the provider resolves itself;
- replaces ``PATH`` inside the shell with :data:`SYSTEM_PATH` before anything else
  runs, so every utility the script or wrapped command names is looked up only in
  the four base system directories (``/usr/local/{bin,sbin}`` are deliberately
  excluded: Dockerfiles routinely hand them to the non-root user), a utility
  missing from them fails rather than falling through to the inherited value, and
  an empty component (which resolves from the cwd) cannot appear;
- also passes ``PATH=SYSTEM_PATH`` through the provider's ``env``. Our own shell
  does not need it, but a provider that wraps every command in something of its
  own (``timeout``, ``runuser``, ``su``) and applies ``env`` before resolving that
  wrapper then resolves it safely too. A provider that ignores ``env`` loses
  nothing: the in-script pin still governs everything we run.

Providers remain responsible for the commands they insert themselves; see the
``exec`` contract on :class:`~inspect_ai.util.SandboxEnvironment`. The built-in
Docker provider launches its ``timeout`` wrapper by absolute path.

Image requirements: ``/bin/sh`` must exist, and every utility a host-issued command
names must live in one of the four system directories. Environment variables the
shell honours before its first line runs (``BASH_ENV`` when ``/bin/sh`` is bash,
``LD_PRELOAD``) are part of the image configuration like ``PATH`` is, but cannot be
neutralised from inside the shell and are out of scope here.

Use :func:`privileged_exec` for an argv and :func:`privileged_shell` for a script.
Use them for any command that runs as ``root`` or as the sandbox default user on
the framework's behalf; the agent's own commands (tool calls) are not in scope and
keep the image's ``PATH`` so the agent's environment behaves as the image intends.
Use :func:`image_path_lookup` for the one question that is *about* the image's
``PATH``: whether it offers a given program (``python3``, an installed tool). A
guard test (``tests/util/sandbox/test_privileged.py``) fails on any ``exec`` call
in ``src`` that passes a literal argv outside the agent-facing tools.
"""

from inspect_ai.util._subprocess import ExecResult

from .environment import SandboxEnvironment

SHELL_PATH = "/bin/sh"
"""Absolute path of the POSIX shell every helper here launches.

A bare ``sh`` would be resolved by the provider through the image's ``PATH``
before a script can pin its own, so an image with a default-user-writable
directory ahead of ``/bin`` would let the agent supply the shell that root runs.
"""

SYSTEM_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
"""The only directories a host-issued command resolves utilities from.

The helpers in this module read it at call time so a test can point it at a
directory of shims (the framework-directory script bakes it in at import).
"""

IMAGE_PATH_VARIABLE = "inspect_image_path"
"""Shell variable holding the ``PATH`` the shell inherited, saved before the pin.

For the rare script that must hand a program the image's own ``PATH`` after
resolving its launcher through the pinned one (the sample setup script,
:func:`image_path_lookup`). Only meaningful when the provider was not also given
:func:`pinned_env`, which would already have replaced the inherited value.
"""


def _pin() -> str:
    """Shell prologue that replaces the inherited ``PATH`` outright.

    ``CDPATH`` is cleared too so a ``cd`` in a wrapped script cannot be redirected
    by an inherited value.
    """
    return (
        f"{IMAGE_PATH_VARIABLE}=${{PATH-}}\n"
        f"PATH={SYSTEM_PATH}\nexport PATH\nunset CDPATH\n"
    )


def pinned_command(cmd: list[str]) -> list[str]:
    """The argv that runs ``cmd`` with its program resolved via :data:`SYSTEM_PATH`.

    ``cmd[0]`` is looked up in the system directories only (a name containing a
    slash is used as given). The shell ``exec``s the program, so the process the
    provider sees is ``cmd`` itself: its exit status, stdin, and signals (a
    provider's timeout) all reach it directly.

    Raises:
        ValueError: ``cmd`` is empty.
    """
    if not cmd:
        raise ValueError("cmd must not be empty")
    return [SHELL_PATH, "-c", _pin() + 'exec "$@"', "sh", *cmd]


def pinned_shell_command(script: str, *args: str) -> list[str]:
    """The argv that runs POSIX ``script`` under :data:`SHELL_PATH` with a pinned ``PATH``.

    ``args`` become ``$1``, ``$2``, ... (``$0`` is ``sh``). The pin is prepended to
    the script, so it holds from the first line the script itself runs.
    """
    return [SHELL_PATH, "-c", _pin() + script, "sh", *args]


def pinned_env(env: dict[str, str] | None) -> dict[str, str]:
    """``env`` with ``PATH`` set to :data:`SYSTEM_PATH` (see the module docstring)."""
    return {**(env or {}), "PATH": SYSTEM_PATH}


async def privileged_exec(
    sandbox: SandboxEnvironment,
    cmd: list[str],
    *,
    user: str | None,
    input: str | bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    timeout_retry: bool = True,
    concurrency: bool = True,
) -> ExecResult[str]:
    """Run ``cmd`` in ``sandbox`` as ``user`` with utilities resolved via :data:`SYSTEM_PATH`.

    A drop-in for ``sandbox.exec`` for commands issued with the framework's
    authority. ``cmd[0]`` never resolves through the image's ``PATH`` (see
    :func:`pinned_command`); ``PATH`` in the command's environment is
    :data:`SYSTEM_PATH` whatever ``env`` says.

    Args:
        sandbox: Sandbox to run in.
        cmd: Command and arguments.
        user: User to run as (as for ``sandbox.exec``); ``None`` is the sandbox
            default user. Required so the authority a call carries is explicit at
            the call site.
        input: Standard input (as for ``sandbox.exec``).
        cwd: Working directory (as for ``sandbox.exec``).
        env: Extra environment variables; ``PATH`` is overridden.
        timeout: Timeout in seconds (as for ``sandbox.exec``).
        timeout_retry: As for ``sandbox.exec``.
        concurrency: As for ``sandbox.exec``.

    Returns:
        The command's result. A failing command is returned, not raised.

    Raises:
        ValueError: ``cmd`` is empty.
        Everything ``sandbox.exec`` raises.
    """
    return await sandbox.exec(
        pinned_command(cmd),
        input=input,
        cwd=cwd,
        env=pinned_env(env),
        user=user,
        timeout=timeout,
        timeout_retry=timeout_retry,
        concurrency=concurrency,
    )


async def privileged_shell(
    sandbox: SandboxEnvironment,
    script: str,
    *args: str,
    user: str | None,
    input: str | bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    timeout_retry: bool = True,
    concurrency: bool = True,
) -> ExecResult[str]:
    """Run POSIX ``script`` in ``sandbox`` as ``user`` under :data:`SHELL_PATH` with a pinned ``PATH``.

    The replacement for ``sandbox.exec(["sh", "-c", script], ...)`` at any site
    that acts with the framework's authority. ``args`` are the script's positional
    parameters (see :func:`pinned_shell_command`); the remaining arguments are as
    for :func:`privileged_exec`.

    Returns:
        The script's result. A failing script is returned, not raised.

    Raises:
        Everything ``sandbox.exec`` raises.
    """
    return await sandbox.exec(
        pinned_shell_command(script, *args),
        input=input,
        cwd=cwd,
        env=pinned_env(env),
        user=user,
        timeout=timeout,
        timeout_retry=timeout_retry,
        concurrency=concurrency,
    )


async def image_path_lookup(
    sandbox: SandboxEnvironment,
    name: str,
    *,
    user: str | None,
    concurrency: bool = True,
) -> ExecResult[str]:
    """Look ``name`` up on the *image's* ``PATH`` with a ``which`` resolved via :data:`SYSTEM_PATH`.

    For the questions that are about what the image offers the sandbox user (does
    it ship ``python3``; is ``inspect-tool-support`` installed), whose answer often
    lives in ``/usr/local/bin`` or a venv/conda directory that :data:`SYSTEM_PATH`
    deliberately excludes. Only ``which`` itself is pinned; it searches the ``PATH``
    the shell inherited. The provider is deliberately not given :func:`pinned_env`,
    which would replace that value before the shell could save it.

    Args:
        sandbox: Sandbox to run in.
        name: Program name to look up.
        user: User to run as (as for ``sandbox.exec``); ``None`` is the sandbox
            default user.
        concurrency: As for ``sandbox.exec``.

    Returns:
        ``which``'s result: success when ``name`` is on the image's ``PATH``, with
        its location on stdout. Exit status 127 when ``which`` itself is missing
        from the system directories.

    Raises:
        Everything ``sandbox.exec`` raises.
    """
    return await sandbox.exec(
        pinned_shell_command(
            "which_bin=$(command -v which) || exit 127\n"
            f'PATH=${IMAGE_PATH_VARIABLE} exec "$which_bin" "$1"',
            name,
        ),
        user=user,
        concurrency=concurrency,
    )
