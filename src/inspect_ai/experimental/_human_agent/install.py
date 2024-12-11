from pathlib import Path

from inspect_ai.util import sandbox


async def install_human_agent() -> None:
    # copy agent src files and make them executable
    INSTALL_DIR = "human_agent_install"
    await checked_exec(["mkdir", "-p", INSTALL_DIR])
    cli_package_dir = Path(__file__).parent / "_resources" / "cli"
    for package_file in cli_package_dir.iterdir():
        with open(package_file, "r") as f:
            contents = f.read()
        file = f"{INSTALL_DIR}/{package_file.name}"
        await checked_write_file(file, contents)
        await checked_exec(["chmod", "+x", file])

    # run install script then remove directory
    await checked_exec(["./install.sh"], cwd=INSTALL_DIR)
    await checked_exec(["rm", "-rf", INSTALL_DIR])


async def checked_exec(
    cmd: list[str], input: str | bytes | None = None, cwd: str | None = None
) -> str:
    result = await sandbox().exec(cmd, input=input, cwd=cwd)
    if not result.success:
        raise RuntimeError(f"Error executing command {' '.join(cmd)}: {result.stderr}")
    return result.stdout


async def checked_write_file(file: str, contents: str) -> None:
    await checked_exec(["tee", "--", file], input=contents)
