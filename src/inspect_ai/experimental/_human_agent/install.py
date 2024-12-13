from pathlib import Path

from typing_extensions import TypedDict

from inspect_ai.solver._task_state import TaskState
from inspect_ai.util import sandbox


async def install_human_agent(state: TaskState, intermediate_scoring: bool) -> None:
    # see if we have already installed
    if not (await sandbox().exec(["mkdir", "/opt/human_agent"])).success:
        return

    # setup installation directory
    INSTALL_DIR = "human_agent_install"
    await checked_exec(["mkdir", "-p", INSTALL_DIR])

    # generate and documentation files
    for doc, content in human_agent_docs(state, intermediate_scoring).items():
        await checked_write_file(f"{INSTALL_DIR}/{doc}.txt", str(content))

    # copy agent cli files and make them executable
    cli_dir = Path(__file__).parent / "_resources" / "cli"
    for cli_file in cli_dir.iterdir():
        with open(cli_file, "r") as f:
            contents = f.read()
        file = f"{INSTALL_DIR}/{cli_file.name}"
        await checked_write_file(file, contents)
        await checked_exec(["chmod", "+x", file])

    # run install script then remove directory
    await checked_exec(["./install.sh"], cwd=INSTALL_DIR)
    await checked_exec(["rm", "-rf", INSTALL_DIR])


class HumanAgentDocs(TypedDict):
    welcome: str
    welcome_login: str
    instructions: str


def human_agent_docs(state: TaskState, intermediate_scoring: bool) -> HumanAgentDocs:
    return HumanAgentDocs(
        welcome="welcome!", welcome_login="welcome login!", instructions="instructions"
    )


async def checked_exec(
    cmd: list[str], input: str | bytes | None = None, cwd: str | None = None
) -> str:
    result = await sandbox().exec(cmd, input=input, cwd=cwd)
    if not result.success:
        raise RuntimeError(f"Error executing command {' '.join(cmd)}: {result.stderr}")
    return result.stdout


async def checked_write_file(file: str, contents: str) -> None:
    await checked_exec(["tee", "--", file], input=contents)
