from pathlib import Path, PurePosixPath
from typing import Sequence

from inspect_ai.util import sandbox as sandbox_env
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from .read import read_skills
from .types import Skill, SkillInfo


async def install_skills(
    skills: Sequence[str | Path | Skill],
    sandbox: str | SandboxEnvironment | None = None,
    user: str | None = None,
    dir: str | None = None,
) -> list[SkillInfo]:
    """Install skills into a sandbox.

    Args:
        skills: Agent skills to install.
        sandbox: Sandbox environment name to copy skills to.
        user: User to write skills files with.
        dir: Directory to install into (defaults to "./skills").

    Returns:
        List of `SkillInfo` with skill names, descriptions, and locations.
    """
    # resolve sandbox
    sbox = sandbox if isinstance(sandbox, SandboxEnvironment) else sandbox_env(sandbox)

    # exec helper
    async def checked_exec(
        cmd: list[str], *, cwd: str | None = None, as_user: str | None = None
    ) -> str:
        result = await sbox.exec(cmd, cwd=cwd, user=as_user or user, timeout=60)
        if not result.success:
            raise RuntimeError(
                f"Error executing command {' '.join(cmd)}: {result.stderr}"
            )
        return result.stdout.strip()

    # write helper
    async def write_skill_file(
        file: str, contents: str | bytes | Path, executable: bool = False
    ) -> None:
        # if it's a path read it as bytes
        if isinstance(contents, Path):
            with open(contents, "rb") as f:
                contents = f.read()

        # write the file
        await sbox.write_file(file, contents)

        # change user if required
        if user:
            await checked_exec(["chown", user, file], as_user="root")

        # mark executable if required
        if executable:
            await checked_exec(["chmod", "+x", file])

    # determine skills dir
    skills_dir = PurePosixPath(dir or "skills")
    if not skills_dir.is_absolute():
        skills_dir = PurePosixPath(await checked_exec(["sh", "-c", "pwd"])) / skills_dir

    # helper to write supporting files
    async def write_supporting_files(
        subdir: str, files: dict[str, str | bytes | Path], executable: bool = False
    ) -> None:
        for file, contents in files.items():
            await write_skill_file(str(skill_dir / subdir / file), contents, executable)

    # install skills
    skills_info: list[SkillInfo] = []
    for skill in read_skills(skills):
        # determine root skill dir
        skill_dir = skills_dir / skill.name

        # compute skill info and write main skill file
        skill_info = SkillInfo(
            name=skill.name,
            description=skill.description,
            instructions=skill.instructions,
            location=str(skill_dir / "SKILL.md"),
        )
        await write_skill_file(skill_info.location, skill.skill_md())
        await write_supporting_files("scripts", skill.scripts, executable=True)
        await write_supporting_files("references", skill.references)
        await write_supporting_files("assets", skill.assets)

        skills_info.append(skill_info)

    return skills_info
