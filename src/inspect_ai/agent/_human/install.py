"""Install the human agent's ``task`` command into a sandbox.

The installation consists of ``task.py`` (the CLI the human runs) in
``HUMAN_AGENT_DIR`` and an alias for it appended to the login user's ``.bashrc``.
The human logs in as an unprivileged user in a sandbox that user may already have
been able to prepare, so nothing here trusts a pathname the sandbox user could have
planted:

- ``HUMAN_AGENT_DIR`` is created or adopted through the verified framework-directory
  helper as root, in mode ``0755``: root stays the only principal who can add or
  replace entries, and every user can read and run ``task.py``. A pre-existing entry
  that is a symlink, not a directory, not root-owned, or in another mode aborts the
  installation with the helper's message rather than being adopted, re-owned, or
  repaired. The helper also requires the parent (``/opt``) to be root-owned and not
  writable by others, as it is in standard images.
- "Already installed" means the verified directory holds ``task.py`` as a regular
  file. A directory that fails the contract is an error, never a reason to skip.
- ``task.py`` is written by root directly into the verified directory (the write
  runs with that directory object as its cwd) under a temporary name, made
  world-readable and executable, and then linked into place, so ``task.py`` only
  ever exists complete and in its final mode. Nothing is staged in, or executed
  from, a directory the sandbox user can write to.
- The ``.bashrc`` append runs as the login user with the content on stdin, inside
  that user's home directory, and refuses a ``.bashrc`` that is a symbolic link or
  anything other than a regular file. It is idempotent (a ``.bashrc`` that already
  carries the human agent block is left alone), so a failed installation can be
  retried without duplicating the block.

Rootless sandboxes (the provider cannot run commands as root, or silently runs them
as the default user) install with the default user as the owner of
``HUMAN_AGENT_DIR``. The directory contract still holds for that uid, but there is
no boundary between the human agent's files and the sandbox user, because they are
the same user. When that user is not root and ``/opt`` is the usual root-owned
``0755``, creating the directory fails and the installation reports that error
(earlier releases silently skipped installing, leaving no ``task`` command).
Unlike the sandbox tools, a directory in the wrong mode is refused
here even in that case: no earlier release left a rootless installation behind to
repair, and the fallback may in fact be running as root (a provider that refused
``user="root"`` while its default user is root), where repairing a root-owned
world-writable directory would adopt whatever the sandbox user put in it.
"""

import inspect
import stat
from logging import getLogger
from textwrap import dedent

from inspect_ai._util.trace import trace_message
from inspect_ai.util import SandboxEnvironment, sandbox
from inspect_ai.util._sandbox._framework_directory import (
    _SHELL,
    FrameworkDirectoryError,
    FrameworkDirectoryUnavailableError,
    FrameworkDirectoryUserError,
    ensure_framework_directory,
    exec_in_framework_directory,
)

from .commands.command import HumanAgentCommand

logger = getLogger(__name__)

TRACE_HUMAN_AGENT = "Human Agent"

HUMAN_AGENT_DIR = "/opt/human_agent"
HUMAN_AGENT_DIR_MODE = 0o755
"""Root-owned, traversable by every user so the login user can run ``task.py``."""
TASK_PY = "task.py"
BASHRC = ".bashrc"
BASHRC_MARKER = (
    "### Inspect Human Agent Setup #########################################="
)
"""First line of the block appended to ``.bashrc``; a line equal to it means installed."""
WELCOME_FILE = "welcome.txt"
WELCOME_LOGIN_FILE = "welcome_login.txt"
INSTRUCTIONS_FILE = "instructions.txt"
RECORD_SESSION_DIR = "/var/tmp/user-sessions"


async def install_human_agent(
    user: str | None,
    commands: list[HumanAgentCommand],
    bashrc_content: str | None,
    record_session: bool,
    sandbox_env: SandboxEnvironment | None = None,
) -> None:
    """Install ``task.py`` and the login user's ``.bashrc`` hook (see module docs).

    The ``.bashrc`` append runs before ``task.py`` is published, so a completed
    installation is exactly one whose ``task.py`` exists: a later call on the same
    sandbox sees it and does nothing, and a call after a failure resumes without
    duplicating the ``.bashrc`` block.

    Args:
        user: User the human logs in as; ``None`` for the sandbox default user.
        commands: Commands the ``task`` CLI exposes.
        bashrc_content: Extra content for the login user's ``.bashrc``.
        record_session: Whether the ``.bashrc`` hook records the session.
        sandbox_env: Sandbox to install into (defaults to the sample's default
            sandbox).

    Raises:
        FrameworkDirectoryError: ``HUMAN_AGENT_DIR`` exists but cannot be trusted,
            or could not be created.
        FrameworkDirectoryUnavailableError: The directory could not be verified
            (the sandbox lacks ``stat`` or ``id`` on its system path, or ``/opt``
            cannot be entered).
        RuntimeError: ``task.py`` exists but is not a regular file, its presence
            could not be determined, the ``.bashrc`` append was refused or failed,
            ``task.py`` could not be written, or (in a rootless sandbox) the
            helper could not run as the default user either.
    """
    sb = sandbox_env or sandbox()
    owner = await _ensure_human_agent_dir(sb)
    if await _task_py_installed(sb, owner):
        return

    bash_rc = human_agent_bashrc(commands, bashrc_content, record_session)
    await append_bashrc(sb, user, bash_rc)

    task_py = human_agent_commands(commands)
    await _write_task_py(sb, owner, task_py)


def _expected_uid(owner: str | None) -> int | None:
    """The uid the helper must actually run as for ``owner`` (only root's is known)."""
    return 0 if owner == "root" else None


async def _ensure_human_agent_dir(sb: SandboxEnvironment) -> str | None:
    """Create or adopt ``HUMAN_AGENT_DIR``; return its owner (``None`` = default user).

    Root is tried first and must really be uid 0, so a provider that ignores
    ``user`` cannot pass off the default user's directory as root's. A contract
    violation reported by the helper propagates rather than selecting the rootless
    install: falling back there would let whoever planted the entry decide which
    user owns the human agent's files. The fallback never repairs a wrong-mode
    directory (see the module docstring).
    """
    try:
        await ensure_framework_directory(
            sb,
            HUMAN_AGENT_DIR,
            user="root",
            expected_uid=0,
            mode=HUMAN_AGENT_DIR_MODE,
        )
        return "root"
    except (FrameworkDirectoryError, FrameworkDirectoryUnavailableError):
        raise
    except FrameworkDirectoryUserError as ex:
        trace_message(
            logger,
            TRACE_HUMAN_AGENT,
            f"sandbox does not run commands as root; using default user: {ex}",
        )
    except Exception as ex:
        # Broad catch is deliberate: providers signal "cannot exec as root" by
        # raising provider-specific exception types (or a failing exit status), so
        # no narrower type is available.
        trace_message(
            logger,
            TRACE_HUMAN_AGENT,
            f"root human agent dir probe failed; falling back to default user: {ex}",
        )

    await ensure_framework_directory(
        sb, HUMAN_AGENT_DIR, user=None, mode=HUMAN_AGENT_DIR_MODE
    )
    return None


# Prints the raw st_mode of $1 (as `stat -c %f` does, without following a symlink)
# or the word "missing" when nothing is there, so absence and a stat failure are told
# apart by the host.
_TASK_PY_PROBE = (
    'if [ -e "$1" ] || [ -L "$1" ]; then stat -c %f "$1"; else echo missing; fi'
)


async def _task_py_installed(sb: SandboxEnvironment, owner: str | None) -> bool:
    """Whether the verified ``HUMAN_AGENT_DIR`` already holds ``task.py``.

    Only a regular file counts as installed. Any other kind of entry, or a probe
    that fails outright, is an error rather than a reason to install over it.
    """
    result = await exec_in_framework_directory(
        sb,
        HUMAN_AGENT_DIR,
        ["sh", "-c", _TASK_PY_PROBE, "sh", TASK_PY],
        user=owner,
        expected_uid=_expected_uid(owner),
        mode=HUMAN_AGENT_DIR_MODE,
    )
    if not result.success:
        raise RuntimeError(
            f"Cannot check for {HUMAN_AGENT_DIR}/{TASK_PY}: {result.stderr.strip()}"
        )
    output = result.stdout.strip()
    if output == "missing":
        return False
    try:
        st_mode = int(output, 16)
    except ValueError:
        raise RuntimeError(
            f"Unexpected output checking {HUMAN_AGENT_DIR}/{TASK_PY}: {output!r}"
        ) from None
    if not stat.S_ISREG(st_mode):
        raise RuntimeError(
            f"Cannot install human agent: {HUMAN_AGENT_DIR}/{TASK_PY} exists but is "
            "not a regular file. Remove it and retry."
        )
    return True


# Writes stdin to a temporary name ($1.tmp) in the verified directory, sets its mode
# (the helper's `umask 077` would otherwise leave it private to the owner), and
# publishes it as $1 with `ln`, which fails rather than replacing an existing entry
# (`mv` would replace one; `ln` also fails on a filesystem without hard links, which
# then surfaces as a write error). The temporary name is cleared first so a retry
# after an interrupted write is not blocked by the leftover, and `set -C` refuses to
# clobber a regular file or symlink that appears at that name in between. The
# temporary name is removed whether or not `ln` succeeded.
_TASK_PY_WRITE = (
    'rm -f "$1.tmp" && set -C && cat > "$1.tmp" && chmod 0755 "$1.tmp" || exit; '
    'ln "$1.tmp" "$1"; rc=$?; rm -f "$1.tmp"; exit $rc'
)


async def _write_task_py(
    sb: SandboxEnvironment, owner: str | None, contents: str
) -> None:
    """Write ``task.py`` into the verified directory, complete and 0755, atomically."""
    result = await exec_in_framework_directory(
        sb,
        HUMAN_AGENT_DIR,
        ["sh", "-c", _TASK_PY_WRITE, "sh", TASK_PY],
        user=owner,
        expected_uid=_expected_uid(owner),
        mode=HUMAN_AGENT_DIR_MODE,
        input=contents,
    )
    if not result.success:
        raise RuntimeError(
            f"Error writing {HUMAN_AGENT_DIR}/{TASK_PY}: {result.stderr.strip()}"
        )


# Runs as the login user with the content to append on stdin; $1 = file name,
# $2 = login user name (empty for the default user), $3 = marker line; a line equal
# to it means the block is already there. The home directory comes from the passwd
# database, by name when one was given (two accounts may share a uid) and by the uid
# the command actually runs as otherwise (docker exec does not always set HOME for
# -u), falling back to HOME. PATH is pinned to the base system directories for the
# same reason the framework-directory helper pins it: this may run as root.
_BASHRC_APPEND_SCRIPT = """
set -u
unset CDPATH
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
name=$1 login=$2 marker=$3
uid=$(id -u) || { echo "cannot determine the current uid" >&2; exit 2; }
home=$(getent passwd "${login:-$uid}" 2>/dev/null | cut -d: -f6)
[ -n "$home" ] || home=${HOME-}
case $home in
    /*) ;;
    *) echo "cannot determine the home directory of ${login:-uid $uid}" >&2; exit 2 ;;
esac
cd -- "$home" || { echo "cannot enter home directory $home" >&2; exit 2; }
if [ -L "$name" ]; then
    echo "refusing to append to $home/$name: it is a symbolic link" >&2
    exit 3
fi
if [ -e "$name" ] && [ ! -f "$name" ]; then
    echo "refusing to append to $home/$name: it is not a regular file" >&2
    exit 3
fi
if [ -f "$name" ] && grep -qxF -- "$marker" "$name"; then
    exit 0
fi
cat >> "$name"
"""


async def append_bashrc(
    sb: SandboxEnvironment, user: str | None, contents: str
) -> None:
    """Append ``contents`` to ``user``'s ``~/.bashrc`` unless already present.

    Runs as ``user`` (``None`` = the sandbox default user) so the write carries no
    authority that user does not already have; a ``.bashrc`` that is a symbolic
    link or some other non-regular entry is refused rather than written through. A
    missing ``.bashrc`` is created; one that already contains ``BASHRC_MARKER`` is
    left unchanged.

    Raises:
        RuntimeError: The append was refused or failed.
    """
    result = await sb.exec(
        [_SHELL, "-c", _BASHRC_APPEND_SCRIPT, "sh", BASHRC, user or "", BASHRC_MARKER],
        input=contents,
        user=user,
    )
    if not result.success:
        raise RuntimeError(
            f"Error appending to {BASHRC} for user {user or 'default'}: "
            f"{result.stderr.strip() or f'exit status {result.returncode}'}"
        )


def human_agent_commands(commands: list[HumanAgentCommand]) -> str:
    # filter out hidden commands
    commands = [command for command in commands if "cli" in command.contexts]

    # standard imports (including any dependencies that call methods carry)
    imports = dedent("""
    import argparse
    import sys
    from argparse import Namespace
    from pathlib import Path

    sys.path.append("/var/tmp/sandbox-services/human_agent")
    from human_agent import call_human_agent

    def format_time(t):
        minutes, seconds = divmod(t, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:.0f}:{minutes:02.0f}:{seconds:02.0f}"
    """)

    # command handler source code (extracted from call methods)
    command_handlers = "\n\n".join(
        dedent(
            inspect.getsource(command.cli).replace("cli(self, ", f"{command.name}(", 1)
        )
        for command in commands
    )

    # parse commands
    command_parsers: list[str] = []
    for command in commands:
        command_parsers.append(
            dedent(f"""
        {command.name}_parser = subparsers.add_parser("{command.name}", help="{command.description}")
        """).lstrip()
        )
        for arg in command.cli_args:
            if arg.name.startswith("--"):
                extras = 'action="store_true", default=False'
            else:
                extras = f"""nargs={1 if arg.required else '"?"'}"""
            command_parsers.append(
                dedent(f"""
                {command.name}_parser.add_argument("{arg.name}", {extras}, help="{arg.description}")
                """).strip()
            )

    parse = (
        dedent("""
    parser = argparse.ArgumentParser(description="Human agent tools.")
    subparsers = parser.add_subparsers(dest="command")
    """)
        + "\n"
        + "\n".join(command_parsers)
    )

    # dispatch commands
    command_dispatchers: list[str] = []
    for i, command in enumerate(commands):
        conditional = "if" if i == 0 else "elif"
        command_dispatchers.append(
            f'{conditional} command == "{command.name}": {command.name}(args)'
        )
    command_dispatchers.append("else: parser.print_help()")

    dispatch = dedent("""
    args = parser.parse_args()
    command = args.command
    delattr(args, 'command')
    """) + "\n".join(command_dispatchers)

    return "\n".join([imports, command_handlers, parse, dispatch]) + "\n"


def human_agent_bashrc(
    commands: list[HumanAgentCommand], bashrc_content: str | None, record_session: bool
) -> str:
    # only run in interative terminals
    TERMINAL_CHECK = dedent(f"""

    {BASHRC_MARKER}

    # only run if shell is interactive
    case $- in
        *i*) ;;
        *) return ;;
    esac

    # only run if attached to a terminal
    if ! tty -s; then
        return
    fi
    """)

    # shell alias and completions
    command_names = " ".join(
        [f"{command.name}" for command in commands if "cli" in command.contexts]
    )
    COMMANDS = dedent(f"""
    # shell alias for human agent commands
    alias task='python3 {HUMAN_AGENT_DIR}/{TASK_PY}'

    # completion handler
    _task_completion() {{
        local cur
        cur="${{COMP_WORDS[COMP_CWORD]}}"
        if [ "$COMP_CWORD" -eq 1 ]; then
            local commands="{command_names}"

            # Generate completion matches
            COMPREPLY=($(compgen -W "${{commands}}" -- ${{cur}}))
        fi
    }}
    complete -F _task_completion task
    """)

    if bashrc_content:
        COMMANDS = f"{COMMANDS}\n\n{bashrc_content}"

    # session recording
    if record_session:
        RECORDING = dedent(f"""
        # record human agent session transcript
        if [ -z "$SCRIPT_RUNNING" ]; then
            export SCRIPT_RUNNING=1
            LOGDIR={RECORD_SESSION_DIR}
            mkdir -p "$LOGDIR"
            TIMESTAMP=$(date +%Y%m%d_%H%M%S)
            INPUTFILE="$LOGDIR/$(whoami)_$TIMESTAMP.input"
            OUTPUTFILE="$LOGDIR/$(whoami)_$TIMESTAMP.output"
            TIMINGFILE="$LOGDIR/$(whoami)_$TIMESTAMP.timing"
            exec script -q -f -m advanced -I "$INPUTFILE" -O "$OUTPUTFILE" -T "$TIMINGFILE" -c "bash --login -i"
        fi
        """)
    else:
        RECORDING = ""

    # display task instructions
    INSTRUCTIONS = dedent("""
    if [ -z "$INSTRUCTIONS_SHOWN" ]; then
        export INSTRUCTIONS_SHOWN=1
        task instructions > ~/instructions.txt
        cat ~/instructions.txt
    fi
    """).lstrip()

    CLOCK = dedent("""
    task start
    """).lstrip()

    # return .bashrc
    return "\n".join([TERMINAL_CHECK, COMMANDS, RECORDING, INSTRUCTIONS, CLOCK])
