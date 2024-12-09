from pathlib import Path

from inspect_ai.util import sandbox


async def configure_sandbox() -> None:
    await install_human_cli()


async def install_human_cli() -> None:
    # copy cli package src
    HUMAN_CLI_DIR = "human_cli"
    await sandbox().exec(["mkdir", "-p", HUMAN_CLI_DIR])
    cli_package_dir = Path(__file__).parent / "_resources" / "cli"
    for package_file in cli_package_dir.iterdir():
        with open(package_file, "r") as f:
            contents = f.read()
        await write_sandbox_file(f"{HUMAN_CLI_DIR}/{package_file.name}", contents)

    # install and then remove cli package src
    await sandbox().exec(["pip", "install", HUMAN_CLI_DIR])
    await sandbox().exec(["rm", "-rf", HUMAN_CLI_DIR])


async def write_sandbox_file(file: str, contents: str) -> None:
    await sandbox().exec(["tee", "--", file], input=contents)
