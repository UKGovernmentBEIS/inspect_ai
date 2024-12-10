from pathlib import Path

from inspect_ai.util import sandbox
from inspect_ai.util._subprocess import ExecResult


async def configure_sandbox() -> None:
    await install_human_cli()


async def install_human_cli() -> None:
    # copy cli src files and make them executable
    INSTALL_DIR = "human_cli_install"
    check(await sandbox().exec(["mkdir", "-p", INSTALL_DIR]))
    cli_package_dir = Path(__file__).parent / "_resources" / "cli"
    for package_file in cli_package_dir.iterdir():
        with open(package_file, "r") as f:
            contents = f.read()
        file = f"{INSTALL_DIR}/{package_file.name}"
        check(await write_sandbox_file(file, contents))
        check(await sandbox().exec(["chmod", "+x", file]))

    # run install script then remove directory
    check(await sandbox().exec(["./install.sh"], cwd=INSTALL_DIR))
    check(await sandbox().exec(["rm", "-rf", INSTALL_DIR]))


async def write_sandbox_file(file: str, contents: str) -> ExecResult[str]:
    return await sandbox().exec(["tee", "--", file], input=contents)


def check(result: ExecResult[str]) -> None:
    print(result.stdout)
    print(result.stderr)
