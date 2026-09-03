"""Install the human agent's ``task`` command into a sandbox.

The installation is ``task.py`` (the CLI the human runs) in ``HUMAN_AGENT_DIR`` and
an alias for it appended to the login user's ``.bashrc``. The human logs in as an
unprivileged user in a sandbox that user may already have been able to prepare, so
nothing here trusts a pathname the sandbox user could have planted:

- ``HUMAN_AGENT_DIR`` is a root-owned framework directory in mode ``0755`` (see
  ``inspect_ai.util._sandbox._framework_directory`` for the contract): root alone
  can add or replace entries, and every user can read and run ``task.py``. An
  entry that fails the contract aborts the installation rather than being adopted
  or repaired.
- "Already installed" means the verified directory holds ``task.py`` as a regular
  file; any other entry there is an error, never a reason to skip.
- ``task.py`` is published through the helper's atomic write, so it only ever
  exists complete, in its final mode, and never over an existing entry.
- The ``.bashrc`` append runs as the login user with the content on stdin, refuses
  a ``.bashrc`` that is not a regular file, and is idempotent, so a failed
  installation can be retried without duplicating the block. Because it carries
  only that user's authority, a ``.bashrc`` the user cannot write (one left
  root-owned by an image build) fails the installation instead of being written
  by the sandbox default user (root in most images) as ``install.sh`` used to.

Rootless sandboxes (root cannot be used, or the provider silently runs commands as
the default user) install with the default user as the directory owner. When the
human logs in as that user there is no boundary between the two; when ``user``
names a different account, the default user owns ``task.py`` and the human runs it
(as before, when ``install.sh`` wrote it as the default user). If the default user
cannot create the directory under ``/opt``, the installation fails with that error
rather than silently skipping. Unlike the sandbox tools, a wrong-mode directory is
refused even here: no earlier release left a rootless installation to repair, and
the fallback may itself be running as root.
"""

import inspect
import stat
from textwrap import dedent

from inspect_ai.util import SandboxEnvironment, sandbox
from inspect_ai.util._sandbox._framework_directory import (
    SHELL_PATH,
    ensure_framework_directory,
    expected_uid_for,
    stat_in_framework_directory,
    try_ensure_framework_directory_as_root,
    write_file_in_framework_directory,
)

from .commands.command import HumanAgentCommand

TRACE_HUMAN_AGENT = "Human Agent"

HUMAN_AGENT_DIR = "/opt/human_agent"
HUMAN_AGENT_DIR_MODE = 0o755
"""Root-owned, traversable by every user so the login user can run ``task.py``."""
TASK_PY = "task.py"
TASK_PY_MODE = 0o755
"""Readable and runnable by every user; only the directory owner can replace it."""
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
        FrameworkDirectoryError: ``HUMAN_AGENT_DIR`` cannot be trusted or created.
        FrameworkDirectoryUnavailableError: The directory could not be verified.
        RuntimeError: ``task.py`` is not a regular file or could not be checked or
            written, or the ``.bashrc`` append was refused or failed.
    """
    sb = sandbox_env or sandbox()
    owner = await _ensure_human_agent_dir(sb)
    if await _task_py_installed(sb, owner):
        return

    bash_rc = human_agent_bashrc(commands, bashrc_content, record_session)
    await append_bashrc(sb, user, bash_rc)

    await write_file_in_framework_directory(
        sb,
        HUMAN_AGENT_DIR,
        TASK_PY,
        human_agent_commands(commands),
        user=owner,
        expected_uid=expected_uid_for(owner),
        mode=HUMAN_AGENT_DIR_MODE,
        file_mode=TASK_PY_MODE,
    )


async def _ensure_human_agent_dir(sb: SandboxEnvironment) -> str | None:
    """Create or adopt ``HUMAN_AGENT_DIR``; return its owner (``None`` = default user).

    The rootless fallback never repairs a wrong-mode directory (see module docs).
    """
    if await try_ensure_framework_directory_as_root(
        sb, HUMAN_AGENT_DIR, mode=HUMAN_AGENT_DIR_MODE, trace_tag=TRACE_HUMAN_AGENT
    ):
        return "root"
    await ensure_framework_directory(
        sb, HUMAN_AGENT_DIR, user=None, mode=HUMAN_AGENT_DIR_MODE
    )
    return None


async def _task_py_installed(sb: SandboxEnvironment, owner: str | None) -> bool:
    """Whether the verified ``HUMAN_AGENT_DIR`` already holds ``task.py``.

    Only a regular file counts as installed. Any other kind of entry is an error
    rather than a reason to install over it.
    """
    st_mode = await stat_in_framework_directory(
        sb,
        HUMAN_AGENT_DIR,
        TASK_PY,
        user=owner,
        expected_uid=expected_uid_for(owner),
        mode=HUMAN_AGENT_DIR_MODE,
    )
    if st_mode is None:
        return False
    if not stat.S_ISREG(st_mode):
        raise RuntimeError(
            f"Cannot install human agent: {HUMAN_AGENT_DIR}/{TASK_PY} exists but is "
            "not a regular file. Remove it and retry."
        )
    return True


# Runs as the login user with the content to append on stdin; $1 = file name,
# $2 = login user name (empty for the default user), $3 = marker line; a line equal
# to it means the block is already there. The home directory comes from the passwd
# database, by name when one was given (two accounts may share a uid) and by the uid
# the command actually runs as otherwise (docker exec does not always set HOME for
# -u). A named user missing from passwd is an error: falling back to HOME would
# write into whichever home the command happens to run in (root's, if the provider
# ignored ``user``). Only the uid lookup falls back to HOME, for images without
# getent; a named login on such an image is an error that says getent is missing,
# not that the account is. PATH is pinned to the base system directories for the
# same reason the framework-directory helper pins it: this may run as root.
_BASHRC_APPEND_SCRIPT = """
set -u
unset CDPATH
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
name=$1 login=$2 marker=$3
uid=$(id -u) || { echo "cannot determine the current uid" >&2; exit 2; }
home=
if command -v getent >/dev/null 2>&1; then
    home=$(getent passwd "${login:-$uid}" 2>/dev/null | cut -d: -f6)
    if [ -z "$home" ] && [ -n "$login" ]; then
        echo "unknown user $login: no such account in the passwd database" >&2
        exit 2
    fi
elif [ -n "$login" ]; then
    echo "cannot look up the home directory of $login: getent not found" >&2
    exit 2
fi
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
    authority that user does not already have. A missing ``.bashrc`` is created; a
    non-regular one is refused; one containing ``BASHRC_MARKER`` is left unchanged.

    Raises:
        RuntimeError: ``user`` is not in the sandbox's passwd database (or the
            sandbox has no ``getent`` to look it up with), or the append was
            refused or failed.
    """
    result = await sb.exec(
        [
            SHELL_PATH,
            "-c",
            _BASHRC_APPEND_SCRIPT,
            "sh",
            BASHRC,
            user or "",
            BASHRC_MARKER,
        ],
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
