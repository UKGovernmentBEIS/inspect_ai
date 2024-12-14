import inspect
from textwrap import dedent, indent

from typing_extensions import TypedDict

from inspect_ai.solver._task_state import TaskState
from inspect_ai.util import sandbox

from .commands import HumanAgentCommand
from .record import record_session_setup

INSTALL_DIR = "human_agent_install"
HUMAN_AGENT_DIR = "/opt/human_agent"
COMMANDS_PY = "commands.py"
INSTALL_SH = "install.sh"
BASHRC = ".bashrc"
WELCOME_FILE = "welcome.txt"
WELCOME_LOGIN_FILE = "welcome_login.txt"
INSTRUCTIONS_FILE = "instructions.txt"


async def install_human_agent(
    state: TaskState, commands: list[HumanAgentCommand], record_session: bool
) -> None:
    # see if we have already installed
    if not (await sandbox().exec(["mkdir", HUMAN_AGENT_DIR])).success:
        return

    # setup installation directory
    await checked_exec(["mkdir", "-p", INSTALL_DIR])

    # generate commands.py
    commands_py = human_agent_commands(commands)
    await checked_write_file(
        f"{INSTALL_DIR}/{COMMANDS_PY}", commands_py, executable=True
    )

    # generate .bashrc
    bash_rc = human_agent_bashrc(commands, record_session)
    await checked_write_file(f"{INSTALL_DIR}/{BASHRC}", bash_rc, executable=True)

    # generate documentation
    for doc, content in human_agent_docs(state, commands).items():
        await checked_write_file(f"{INSTALL_DIR}/{doc}.txt", str(content))

    # write and run installation script
    install_sh = human_agent_install_sh()
    await checked_write_file(f"{INSTALL_DIR}/{INSTALL_SH}", install_sh, executable=True)
    await checked_exec(["bash", f"./{INSTALL_SH}"], cwd=INSTALL_DIR)
    await checked_exec(["rm", "-rf", INSTALL_DIR])


def human_agent_commands(commands: list[HumanAgentCommand]) -> str:
    PREFIX = dedent("""
    #!/usr/bin/env python3
    import argparse
    import os
    import sys
    from pathlib import Path

    sys.path.append("/var/tmp/inspect-sandbox-services/human_agent")
    from human_agent import call_human_agent
    """)

    code = "\n\n".join(
        dedent(
            inspect.getsource(command.call).replace(
                "call(self)", f"{command.name}()", 1
            )
        )
        for command in commands
    )

    command_map = (
        "{"
        + ", ".join([f'"{command.name}": {command.name}' for command in commands])
        + "}"
    )
    registration = f"_commands: dict = {command_map}"

    SUFFIX = dedent("""
    if len(sys.argv) > 0:
        command = os.path.basename(sys.argv[1])
        handler = _commands.get(command, None)
        if handler:
            handler()
        else:
            sys.stderr.write(f"command not recognized: {command}")
            sys.exit(1)
    else:
        sys.stderr.write("no command specified")
        sys.exit(1)
    """)

    return "\n\n".join([PREFIX, code, registration, SUFFIX])


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

    # command aliases
    COMMANDS = "\n".join(
        ["# shell aliases for human agent commands"]
        + [
            f"alias {command.name}='python3 {HUMAN_AGENT_DIR}/{COMMANDS_PY} {command.name}'"
            for command in commands
        ]
    )

    # session recording
    RECORDING = record_session_setup() if record_session else ""

    # display welcome login
    WELCOME = dedent(f"""
    # display human agent welcome message
    cat {HUMAN_AGENT_DIR}/{WELCOME_LOGIN_FILE}
    """).lstrip()

    # return .bashrc
    return "\n".join([TERMINAL_CHECK, COMMANDS, RECORDING, WELCOME])


class HumanAgentDocs(TypedDict):
    welcome: str
    welcome_login: str
    instructions: str


def human_agent_docs(
    state: TaskState, commands: list[HumanAgentCommand]
) -> HumanAgentDocs:
    commands_text = "\n".join(
        [
            f"- {command.name}: {command.description}"
            for command in commands
            if not command.hidden
        ]
    )

    instructions = "\n\n".join([message.text for message in state.messages])

    welcome = dedent(f"""
    =================================================================================
                            WELCOME TO YOUR INSPECT TASK!
    =================================================================================

    Please use the following commands as you complete your work:

{indent(commands_text, "    ")}
    """).lstrip()

    welcome_login = dedent(f"""
{indent(welcome, "    ")}
    The command reference will also be saved in the file {WELCOME_FILE}.
    Task instructions are at {INSTRUCTIONS_FILE} and are also displayed below.

    =================================================================================

{indent(instructions, "    ")}

    """).lstrip()

    return HumanAgentDocs(
        welcome=welcome, welcome_login=welcome_login, instructions=instructions
    )


def human_agent_install_sh() -> str:
    COMMANDS = dedent(f"""
    #!/usr/bin/env bash

    # create installation directory
    HUMAN_AGENT="{HUMAN_AGENT_DIR}"
    mkdir -p $HUMAN_AGENT

    # copy commands
    cp {COMMANDS_PY} $HUMAN_AGENT

    # append to bash rc
    cat {BASHRC} >> ~/{BASHRC}

    $ copy documentation
    cp {WELCOME_LOGIN_FILE} $HUMAN_AGENT
    cp {WELCOME_FILE} ..
    cp {INSTRUCTIONS_FILE} ..
    """)

    return "\n\n".join([COMMANDS])


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
