import hashlib
from logging import getLogger
from pathlib import Path, PurePosixPath
from typing import NamedTuple, Sequence
from weakref import WeakKeyDictionary

import anyio

from inspect_ai.util import sandbox as sandbox_env
from inspect_ai.util._sandbox._privileged import privileged_exec, privileged_shell
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxUserUnsupportedError,
)

from .read import read_skills
from .types import Skill, SkillInfo

logger = getLogger(__name__)


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
    # resolve and validate skills before sandbox setup
    from .validate import check_unique_skill_names

    resolved_skills = read_skills(skills)
    check_unique_skill_names(resolved_skills)

    # resolve sandbox
    sbox = sandbox if isinstance(sandbox, SandboxEnvironment) else sandbox_env(sandbox)

    # install skills
    skills_dir = await _resolve_skills_dir(sbox, user, dir)
    skills_info: list[SkillInfo] = []
    for skill in resolved_skills:
        await _write_skill(sbox, user, skills_dir, skill)
        skills_info.append(_skill_info(skills_dir, skill))

    return skills_info


async def install_skills_shared(
    skills: Sequence[Skill],
    sandbox: str | None,
    user: str | None,
    dir: str | None,
) -> list[SkillInfo]:
    """Install skills into a sandbox directory shared by several skill tools.

    Skill tools in different tool state scopes keep their own skill lists but
    install into the same sandbox files. The files in the sandbox decide what
    is installed: a skill file that is missing is written, one that already
    holds the same bytes is left as is, and one that holds different bytes
    raises an error before any file of that skill is written. Files are
    compared by a SHA-256 digest computed in the sandbox, so no file size
    limit applies. A file whose write, ownership change or mode change is
    interrupted is removed, so the next install writes it again. Installs
    into one sandbox are serialised by one lock per sample sandbox.

    Args:
        skills: Resolved skills to install.
        sandbox: Sandbox environment name to copy skills to.
        user: User to write skills files with.
        dir: Directory to install into (defaults to "./skills").

    Returns:
        List of `SkillInfo` with skill names, descriptions, and locations.

    Raises:
        RuntimeError: If a skill file already exists in the sandbox with
            different contents.
    """
    sbox = sandbox_env(sandbox)
    skills_dir = await _resolve_skills_dir(sbox, user, dir)
    lock = _install_locks.setdefault(sbox, anyio.Lock())
    async with lock:
        for skill in skills:
            missing: list[_SkillFile] = []
            for file in _skill_files(skills_dir, skill):
                existing = await _sandbox_digest(sbox, file.path)
                if existing is None:
                    missing.append(file)
                elif existing != hashlib.sha256(_file_bytes(file.contents)).hexdigest():
                    raise RuntimeError(
                        f"Skill '{skill.name}' cannot be installed: {file.path} "
                        "already exists in the sandbox with different contents."
                    )
            for file in missing:
                await _write_skill_file_or_remove(sbox, user, file)
    return [_skill_info(skills_dir, skill) for skill in skills]


# one lock per sample sandbox (held weakly, so it goes with the sample), so a
# skill's files are complete before another tool reads them
_install_locks: WeakKeyDictionary[SandboxEnvironment, anyio.Lock] = WeakKeyDictionary()


# prints "missing" or the SHA-256 digest of file $1 (as "<digest>  -")
_DIGEST_SCRIPT = """
[ -e "$1" ] || { echo missing; exit 0; }
sha256sum < "$1"
"""


async def _sandbox_digest(sbox: SandboxEnvironment, file: str) -> str | None:
    result = await privileged_shell(sbox, _DIGEST_SCRIPT, file, user=None, timeout=60)
    if not result.success:
        raise RuntimeError(f"Error reading skill file {file}: {result.stderr}")
    output = result.stdout.strip()
    return None if output == "missing" else output.split()[0]


async def _checked_exec(
    sbox: SandboxEnvironment,
    user: str | None,
    cmd: list[str],
    *,
    cwd: str | None = None,
    as_user: str | None = None,
) -> str:
    # these run as `user` (the sandbox default user, root in most images, when
    # None) or as root, so utilities must not come from the image's PATH
    result = await privileged_exec(sbox, cmd, cwd=cwd, user=as_user or user, timeout=60)
    if not result.success:
        raise RuntimeError(f"Error executing command {' '.join(cmd)}: {result.stderr}")
    return result.stdout.strip()


async def _resolve_skills_dir(
    sbox: SandboxEnvironment, user: str | None, dir: str | None
) -> PurePosixPath:
    skills_dir = PurePosixPath(dir or "skills")
    if not skills_dir.is_absolute():
        skills_dir = (
            PurePosixPath(await _checked_exec(sbox, user, ["pwd"])) / skills_dir
        )
    return skills_dir


def _skill_info(skills_dir: PurePosixPath, skill: Skill) -> SkillInfo:
    return SkillInfo(
        name=skill.name,
        description=skill.description,
        instructions=skill.instructions,
        location=str(skills_dir / skill.name / "SKILL.md"),
    )


def _file_bytes(contents: str | bytes | Path) -> bytes:
    if isinstance(contents, Path):
        with open(contents, "rb") as f:
            return f.read()
    return contents.encode() if isinstance(contents, str) else contents


class _SkillFile(NamedTuple):
    path: str
    contents: str | bytes | Path
    executable: bool


def _skill_files(skills_dir: PurePosixPath, skill: Skill) -> list[_SkillFile]:
    skill_dir = skills_dir / skill.name
    files = [_SkillFile(str(skill_dir / "SKILL.md"), skill.skill_md(), False)]
    for subdir, contents, executable in (
        ("scripts", skill.scripts, True),
        ("references", skill.references, False),
        ("assets", skill.assets, False),
    ):
        files.extend(
            _SkillFile(str(skill_dir / subdir / file), file_contents, executable)
            for file, file_contents in contents.items()
        )
    return files


async def _write_skill(
    sbox: SandboxEnvironment,
    user: str | None,
    skills_dir: PurePosixPath,
    skill: Skill,
) -> None:
    for file in _skill_files(skills_dir, skill):
        await _write_skill_file(sbox, user, file)


async def _write_skill_file(
    sbox: SandboxEnvironment, user: str | None, file: _SkillFile
) -> None:
    # if it's a path read it as bytes
    contents = file.contents
    if isinstance(contents, Path):
        contents = _file_bytes(contents)

    # write the file
    await sbox.write_file(file.path, contents)

    # change user if required
    if user:
        try:
            await _checked_exec(sbox, user, ["chown", user, file.path], as_user="root")
        except SandboxUserUnsupportedError:
            await _checked_exec(sbox, user, ["chown", user, file.path], as_user=user)

    # mark executable if required
    if file.executable:
        await _checked_exec(sbox, user, ["chmod", "+x", file.path])


async def _write_skill_file_or_remove(
    sbox: SandboxEnvironment, user: str | None, file: _SkillFile
) -> None:
    try:
        await _write_skill_file(sbox, user, file)
    except BaseException:
        # a file left without its ownership or mode still has the skill's
        # bytes, so the next install would skip it: remove it
        with anyio.CancelScope(shield=True):
            try:
                await _checked_exec(sbox, None, ["rm", "-f", file.path])
            except Exception as ex:
                logger.warning(f"Unable to remove skill file {file.path}: {ex}")
        raise
