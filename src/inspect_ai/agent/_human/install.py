import inspect
from textwrap import dedent

from inspect_ai.util import sandbox

from .commands.command import HumanAgentCommand

INSTALL_DIR = "human_agent_install"
HUMAN_AGENT_DIR = "/opt/human_agent"
TASK_PY = "task.py"
INSTALL_SH = "install.sh"
BASHRC = ".bashrc"
WELCOME_FILE = "welcome.txt"
WELCOME_LOGIN_FILE = "welcome_login.txt"
INSTRUCTIONS_FILE = "instructions.txt"
RECORD_SESSION_DIR = "/var/tmp/user-sessions"


async def install_human_agent(
    user: str | None,
    commands: list[HumanAgentCommand],
    record_session: bool,
) -> None:
    # see if we have already installed
    if not (await sandbox().exec(["mkdir", HUMAN_AGENT_DIR])).success:
        return

    # setup installation directory
    await checked_exec(["mkdir", "-p", INSTALL_DIR])

    # generate task.py
    task_py = human_agent_commands(commands)
    await checked_write_file(f"{INSTALL_DIR}/{TASK_PY}", task_py, executable=True)

    # generate .bashrc
    bash_rc = human_agent_bashrc(commands, record_session)
    await checked_write_file(f"{INSTALL_DIR}/{BASHRC}", bash_rc, executable=True)

    # write and run installation script
    install_sh = human_agent_install_sh(user)
    await checked_write_file(f"{INSTALL_DIR}/{INSTALL_SH}", install_sh, executable=True)
    await checked_exec(["bash", f"./{INSTALL_SH}"], cwd=INSTALL_DIR)
    await checked_exec(["rm", "-rf", INSTALL_DIR])


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


def human_agent_bashrc(commands: list[HumanAgentCommand], record_session: bool) -> str:
    # only run in interative terminals
    TERMINAL_CHECK = dedent("""

    ### Inspect Human Agent Setup #########################################=

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


def human_agent_install_sh(user: str | None) -> str:
    return dedent(f"""
    #!/usr/bin/env bash

    # create installation directory
    HUMAN_AGENT="{HUMAN_AGENT_DIR}"
    mkdir -p $HUMAN_AGENT

    # copy command script
    cp {TASK_PY} $HUMAN_AGENT

    # get user's home directory
    USER="{user or ""}"
    if [ -z "$USER" ]; then
        USER=$(whoami)
    fi
    USER_HOME=$(getent passwd $USER | cut -d: -f6)

    # append to user's .bashrc
    cat {BASHRC} >> $USER_HOME/{BASHRC}
    """)


async def checked_exec(
    cmd: list[str],
    input: str | bytes | None = None,
    cwd: str | None = None,
) -> str:
    result = await sandbox().exec(cmd, input=input, cwd=cwd)
    if not result.success:
        raise RuntimeError(f"Error executing command {' '.join(cmd)}: {result.stderr}")
    return result.stdout


async def checked_write_file(
    file: str, contents: str, executable: bool = False
) -> None:
    await checked_exec(["tee", "--", file], input=contents)
    if executable:
        await checked_exec(["chmod", "+x", file])
