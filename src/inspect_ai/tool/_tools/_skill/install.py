import hashlib
import posixpath
from pathlib import Path, PurePosixPath
from typing import Sequence
from weakref import WeakKeyDictionary

import anyio
from pydantic import Field

from inspect_ai.util import sandbox as sandbox_env
from inspect_ai.util._sandbox._privileged import privileged_exec, privileged_shell
from inspect_ai.util._sandbox.context import sandbox_environments_context_var
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxUserUnsupportedError,
)
from inspect_ai.util._store_model import StoreModel, store_as

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
    install into the same sandbox directory. A record in the sample store
    (skill name to content hash, per sandbox and physical directory) makes
    each skill's files be written once: a skill already installed with the
    same contents is skipped, and one installed with different contents
    raises an error. The record is checkpointed with the store, so it holds
    after a resume. A checkpoint taken before the record existed has none:
    after resuming it, the first tool to install a skill writes it again, as
    it did before.

    Args:
        skills: Resolved skills to install.
        sandbox: Sandbox environment name to copy skills to.
        user: User to write skills files with.
        dir: Directory to install into (defaults to "./skills").

    Returns:
        List of `SkillInfo` with skill names, descriptions, and locations.

    Raises:
        RuntimeError: If a skill of the same name was already installed in
            the directory with different contents.
    """
    sbox = sandbox_env(sandbox)
    skills_dir = await _resolve_skills_dir(sbox, user, dir)
    record_key = f"{_sandbox_name(sbox)}:{await _physical_dir(sbox, user, skills_dir)}"
    # held across the writes of one tool's skills, so a skill's files are
    # complete before another tool can find it recorded
    lock = _install_locks.setdefault(sbox, {}).setdefault(record_key, anyio.Lock())
    async with lock:
        record = store_as(SkillFiles)
        for skill in skills:
            digest = _skill_hash(skill)
            installed_digest = record.hashes.get(record_key, {}).get(skill.name)
            if installed_digest is None:
                await _write_skill(sbox, user, skills_dir, skill)
                hashes = dict(record.hashes)
                hashes[record_key] = {**hashes.get(record_key, {}), skill.name: digest}
                record.hashes = hashes
            elif installed_digest != digest:
                raise RuntimeError(
                    f"Skill '{skill.name}' is already installed in {skills_dir} "
                    "with different contents. Give the skills different names "
                    "or install them into different directories."
                )
    return [_skill_info(skills_dir, skill) for skill in skills]


class SkillFiles(StoreModel):
    """Skills installed in each sandbox directory (name to content hash)."""

    hashes: dict[str, dict[str, str]] = Field(default_factory=dict)


# keyed by the sample's sandbox environment, so samples do not share locks
_install_locks: WeakKeyDictionary[SandboxEnvironment, dict[str, anyio.Lock]] = (
    WeakKeyDictionary()
)


def _sandbox_name(sbox: SandboxEnvironment) -> str:
    environments = sandbox_environments_context_var.get(None) or {}
    for name, environment in environments.items():
        if environment is sbox:
            return name
    raise RuntimeError("Skill sandbox is not one of the sample's sandboxes.")


# print the physical path of the deepest existing ancestor of $1 (symlinks
# resolved), followed by the rest of $1, which does not exist yet
_PHYSICAL_DIR_SCRIPT = """
dir=$1 rest=
while [ ! -d "$dir" ]; do
  rest="/${dir##*/}$rest"
  dir=${dir%/*}
  [ -n "$dir" ] || dir=/
done
cd "$dir" || exit 1
physical=$(pwd -P)
[ "$physical" != / ] || physical=
printf '%s%s\\n' "$physical" "${rest:-/}"
"""


async def _physical_dir(
    sbox: SandboxEnvironment, user: str | None, skills_dir: PurePosixPath
) -> PurePosixPath:
    result = await privileged_shell(
        sbox, _PHYSICAL_DIR_SCRIPT, str(skills_dir), user=user, timeout=60
    )
    if not result.success:
        raise RuntimeError(
            f"Error resolving skills directory {skills_dir}: {result.stderr}"
        )
    # the rest holds no symlinks, so its ".." can be resolved lexically
    return PurePosixPath(posixpath.normpath(result.stdout.strip()))


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


def _skill_hash(skill: Skill) -> str:
    digest = hashlib.sha256()

    def add(data: bytes) -> None:
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)

    add(skill.skill_md().encode())
    for subdir, files in (
        ("scripts", skill.scripts),
        ("references", skill.references),
        ("assets", skill.assets),
    ):
        add(subdir.encode())
        add(str(len(files)).encode())
        for file in sorted(files):
            add(file.encode())
            add(_file_bytes(files[file]))
    return digest.hexdigest()


async def _write_skill(
    sbox: SandboxEnvironment,
    user: str | None,
    skills_dir: PurePosixPath,
    skill: Skill,
) -> None:
    skill_dir = skills_dir / skill.name

    async def write_skill_file(
        file: str, contents: str | bytes | Path, executable: bool = False
    ) -> None:
        # if it's a path read it as bytes
        if isinstance(contents, Path):
            contents = _file_bytes(contents)

        # write the file
        await sbox.write_file(file, contents)

        # change user if required
        if user:
            try:
                await _checked_exec(sbox, user, ["chown", user, file], as_user="root")
            except SandboxUserUnsupportedError:
                await _checked_exec(sbox, user, ["chown", user, file], as_user=user)

        # mark executable if required
        if executable:
            await _checked_exec(sbox, user, ["chmod", "+x", file])

    async def write_supporting_files(
        subdir: str, files: dict[str, str | bytes | Path], executable: bool = False
    ) -> None:
        for file, contents in files.items():
            await write_skill_file(str(skill_dir / subdir / file), contents, executable)

    await write_skill_file(str(skill_dir / "SKILL.md"), skill.skill_md())
    await write_supporting_files("scripts", skill.scripts, executable=True)
    await write_supporting_files("references", skill.references)
    await write_supporting_files("assets", skill.assets)
