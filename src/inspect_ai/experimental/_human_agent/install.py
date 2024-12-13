import inspect
from textwrap import dedent, indent

from typing_extensions import TypedDict

from inspect_ai.solver._task_state import TaskState
from inspect_ai.util import sandbox

from .commands import HumanAgentCommand

INSTALL_DIR = "human_agent_install"
HUMAN_AGENT_DIR = "/opt/human_agent"
COMMANDS_PY = "commands.py"
INSTALL_SH = "install.sh"
WELCOME_FILE = "welcome.txt"
WELCOME_LOGIN_FILE = "welcome_login.txt"
INSTRUCTIONS_FILE = "instructions.txt"


async def install_human_agent(
    state: TaskState, commands: list[HumanAgentCommand]
) -> None:
    # see if we have already installed
    if not (await sandbox().exec(["mkdir", HUMAN_AGENT_DIR])).success:
        return

    # setup installation directory
    await checked_exec(["mkdir", "-p", INSTALL_DIR])

    # generate and write documentation files
    for doc, content in human_agent_docs(state, commands).items():
        await checked_write_file(f"{INSTALL_DIR}/{doc}.txt", str(content))

    # generate and write commands.py
    commands_py = human_agent_commands_py(commands)
    await checked_write_file(
        f"{INSTALL_DIR}/{COMMANDS_PY}", commands_py, executable=True
    )

    # write installation script
    install_sh = human_agent_install_sh(commands)
    await checked_write_file(f"{INSTALL_DIR}/{INSTALL_SH}", install_sh, executable=True)

    # run install script then remove directory
    await checked_exec(["bash", f"./{INSTALL_SH}"], cwd=INSTALL_DIR)
    await checked_exec(["rm", "-rf", INSTALL_DIR])


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

    """)

    welcome_login = dedent(f"""
    The command reference will also be saved in the file {WELCOME_FILE}.
    Task instructions are at {INSTRUCTIONS_FILE} and are also displayed below.

    =================================================================================

{indent(instructions, "    ")}
    """).lstrip()

    return HumanAgentDocs(
        welcome=welcome, welcome_login=welcome_login, instructions=instructions
    )


def human_agent_commands_py(commands: list[HumanAgentCommand]) -> str:
    PREFIX = dedent("""
    #!/usr/bin/env python3
    import argparse
    import os
    import sys

    sys.path.append("/tmp/inspect-sandbox-services/human_agent")
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


def human_agent_install_sh(commands: list[HumanAgentCommand]) -> str:
    PREFIX = dedent(f"""
    #!/usr/bin/env bash

    # install commands
    HUMAN_AGENT="{HUMAN_AGENT_DIR}"
    mkdir -p $HUMAN_AGENT
    cp {COMMANDS_PY} $HUMAN_AGENT

    # copy documentation
    cp {WELCOME_FILE} ..
    cp {INSTRUCTIONS_FILE} ..

    # create bash aliases for commands
    create_alias() {{
        echo "alias $1='python3 $HUMAN_AGENT/{COMMANDS_PY} $1'" >> ~/.bashrc
    }}
    """)

    registration = dedent(f"""
    for cmd in {' '.join([command.name for command in commands])}; do
        create_alias $cmd
    done
    """)

    SUFFIX = dedent(f"""
    # add welcome login content
    echo 'cat <<- "EOF"' >> ~/.bashrc
    cat {WELCOME_FILE} >> ~/.bashrc
    cat {WELCOME_LOGIN_FILE} >> ~/.bashrc
    echo '' >> ~/.bashrc
    echo 'EOF' >> ~/.bashrc
    """)

    return "\n\n".join([PREFIX, registration, SUFFIX])


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
