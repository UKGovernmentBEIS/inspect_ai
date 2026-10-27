"""End-to-end tests for the skill() tool."""

import hashlib
import os
import re
from pathlib import Path

import anyio
import pytest
from test_helpers.sandbox import CannedSandbox
from test_helpers.utils import flaky_retry, skip_if_no_docker, skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import Generate, Solver, TaskState, fork, solver
from inspect_ai.tool import Tool, ToolError, bash, skill
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._skill.install import install_lock, install_skills
from inspect_ai.tool._tools._skill.read import SkillParsingError, _read_skill
from inspect_ai.tool._tools._skill.tool import _cache_lock
from inspect_ai.tool._tools._skill.types import Skill
from inspect_ai.util import (
    SandboxUserUnsupportedError,
    Store,
    store,
    subtask,
    tool_state_scope,
)
from inspect_ai.util._sandbox.context import (
    sandbox_default_context_var,
    sandbox_environments_context_var,
)
from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.limits import (
    OutputLimitExceededError,
    override_max_read_file_size,
)
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment
from inspect_ai.util._store import init_subtask_store
from inspect_ai.util._subprocess import ExecResult

# Path to test skills directory
SKILLS_DIR = Path(__file__).parent / "skills"


def create_skill_md(
    name: str = "test-skill",
    description: str = "A test skill",
    extra_frontmatter: str = "",
    body: str = "# Instructions\n\nDo the thing.",
) -> str:
    """Helper to create SKILL.md content."""
    return f"""---
name: {name}
description: {description}
{extra_frontmatter}---
{body}
"""


class TestSkillNameUniqueness:
    def test_duplicate_names_in_skill_tool(self) -> None:
        """skill() rejects duplicate skill names."""
        sk1 = Skill(name="pdf", description="First.", instructions="1.")
        sk2 = Skill(name="pdf", description="Second.", instructions="2.")
        with pytest.raises(ValueError, match="Duplicate skill name"):
            skill([sk1, sk2])

    async def test_duplicate_names_in_install_skills(self) -> None:
        """install_skills() rejects duplicate skill names before sandbox setup."""
        sk1 = Skill(name="pdf", description="First.", instructions="1.")
        sk2 = Skill(name="pdf", description="Second.", instructions="2.")
        # Should fail with ValueError, not ProcessLookupError (no sandbox)
        with pytest.raises(ValueError, match="Duplicate skill name"):
            await install_skills([sk1, sk2])

    def test_unique_names_accepted(self) -> None:
        """skill() accepts unique skill names."""
        sk1 = Skill(name="pdf", description="PDF.", instructions="1.")
        sk2 = Skill(name="xlsx", description="Excel.", instructions="2.")
        tool = skill([sk1, sk2])
        assert tool is not None


class TestSkillInstallation:
    async def test_install_as_local_current_user(self) -> None:
        if os.name != "posix":
            pytest.skip("requires POSIX user identities")
        local = LocalSandboxEnvironment()
        sk = Skill(
            name="example",
            description="Example",
            instructions="Example",
            scripts={"run.sh": "echo hello"},
        )
        try:
            [installed] = await install_skills(
                [sk], sandbox=local, user=str(os.geteuid()), dir=local.directory.name
            )
            path = Path(installed.location)
            assert path.read_text() == sk.skill_md()
            assert path.stat().st_uid == os.geteuid()
            script = path.parent / "scripts" / "run.sh"
            assert script.read_text() == "echo hello"
            assert script.stat().st_mode & 0o100
        finally:
            local.directory.cleanup()

    @pytest.mark.parametrize(
        "root_result, fallback_success, expected_users",
        [
            (SandboxUserUnsupportedError("no root"), True, ["root", "1000"]),
            (SandboxUserUnsupportedError("no root"), False, ["root", "1000"]),
            (TimeoutError("timeout"), True, ["root"]),
            (PermissionError("permission denied"), True, ["root"]),
            (ExecResult(False, 1, "", "chown failed"), True, ["root"]),
        ],
    )
    async def test_chown_fallback(
        self,
        root_result: Exception | ExecResult[str],
        fallback_success: bool,
        expected_users: list[str],
    ) -> None:
        def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
            if user == "root":
                if isinstance(root_result, Exception):
                    raise root_result
                return root_result
            return ExecResult(
                fallback_success, 0 if fallback_success else 1, "", "chown failed"
            )

        sandbox = CannedSandbox(policy)
        sk = Skill(name="example", description="Example", instructions="Example")
        if isinstance(root_result, SandboxUserUnsupportedError) and fallback_success:
            await install_skills([sk], sandbox=sandbox, user="1000", dir="/skills")
        else:
            error_type = (
                type(root_result)
                if isinstance(root_result, Exception)
                and not isinstance(root_result, SandboxUserUnsupportedError)
                else RuntimeError
            )
            with pytest.raises(error_type):
                await install_skills([sk], sandbox=sandbox, user="1000", dir="/skills")
        assert [user for _, user in sandbox.exec_calls] == expected_users

    async def test_nested_files_install_at_posix_paths(self, tmp_path: Path) -> None:
        """Files in subdirectories land in the matching sandbox subdirectory."""
        skill_dir = tmp_path / "test-skill"
        (skill_dir / "scripts" / "bash").mkdir(parents=True)
        (skill_dir / "assets" / "templates" / "email").mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(create_skill_md())
        (skill_dir / "scripts" / "bash" / "run.sh").write_text("echo hello")
        (skill_dir / "assets" / "templates" / "email" / "welcome.txt").write_text("Hi")

        sandbox = CannedSandbox.returning(ExecResult(True, 0, "", ""))
        await install_skills([skill_dir], sandbox=sandbox, dir="/skills")

        assert sorted(sandbox.written) == [
            "/skills/test-skill/SKILL.md",
            "/skills/test-skill/assets/templates/email/welcome.txt",
            "/skills/test-skill/scripts/bash/run.sh",
        ]


class TestSkillParsing:
    def test_valid_skill_minimal(self, tmp_path: Path) -> None:
        """Test parsing a valid skill with only SKILL.md."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(create_skill_md())

        result = _read_skill(skill_dir)

        assert isinstance(result, Skill)
        assert result.name == "test-skill"
        assert result.description == "A test skill"
        assert "# Instructions" in result.instructions
        assert result.scripts == {}
        assert result.references == {}
        assert result.assets == {}

    def test_valid_skill_with_directories(self, tmp_path: Path) -> None:
        """Test parsing a skill with scripts/, references/, and assets/ directories."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(create_skill_md())

        # Create subdirectories with files
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.py").write_text("print('hello')")
        (scripts_dir / "helper.sh").write_text("echo hello")

        refs_dir = skill_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "API.md").write_text("# API Reference")

        assets_dir = skill_dir / "assets"
        assets_dir.mkdir()
        (assets_dir / "template.txt").write_text("template content")

        result = _read_skill(skill_dir)

        assert len(result.scripts) == 2
        assert "run.py" in result.scripts
        assert "helper.sh" in result.scripts
        assert isinstance(result.scripts["run.py"], Path)

        assert len(result.references) == 1
        assert "API.md" in result.references

        assert len(result.assets) == 1
        assert "template.txt" in result.assets

    def test_valid_skill_with_optional_fields(self, tmp_path: Path) -> None:
        """Test parsing a skill with optional frontmatter fields."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            create_skill_md(
                extra_frontmatter='license: MIT\ncompatibility: "Python 3.10+"\nallowed-tools: bash python\n'
            )
        )

        result = _read_skill(skill_dir)

        assert result.license == "MIT"
        assert result.compatibility == "Python 3.10+"
        assert result.allowed_tools == "bash python"

    def test_valid_skill_with_metadata(self, tmp_path: Path) -> None:
        """Test parsing a skill with metadata field."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        content = """---
name: test-skill
description: A test skill
metadata:
  version: "1.0"
  author: Test Author
---
# Instructions
"""
        (skill_dir / "SKILL.md").write_text(content)

        result = _read_skill(skill_dir)

        assert result.metadata == {"version": "1.0", "author": "Test Author"}

    def test_excludes_hidden_files(self, tmp_path: Path) -> None:
        """Test that hidden files (starting with . or _) are excluded."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(create_skill_md())

        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.py").write_text("print('hello')")
        (scripts_dir / ".hidden").write_text("hidden")
        (scripts_dir / "_private.py").write_text("private")

        result = _read_skill(skill_dir)

        assert len(result.scripts) == 1
        assert "run.py" in result.scripts
        assert ".hidden" not in result.scripts
        assert "_private.py" not in result.scripts

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        """Test that string paths are accepted."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(create_skill_md())

        result = _read_skill(str(skill_dir))

        assert result.name == "test-skill"

    def test_subdirectories_in_scripts(self, tmp_path: Path) -> None:
        """Test that subdirectories are enumerated with relative path keys."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(create_skill_md())

        # Create nested directory structure
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "root.py").write_text("# root level")

        bash_dir = scripts_dir / "bash"
        bash_dir.mkdir()
        (bash_dir / "run.sh").write_text("echo hello")
        (bash_dir / "setup.sh").write_text("echo setup")

        python_dir = scripts_dir / "python"
        python_dir.mkdir()
        (python_dir / "main.py").write_text("print('main')")

        result = _read_skill(skill_dir)

        assert len(result.scripts) == 4
        assert "root.py" in result.scripts
        assert "bash/run.sh" in result.scripts
        assert "bash/setup.sh" in result.scripts
        assert "python/main.py" in result.scripts

    def test_deeply_nested_subdirectories(self, tmp_path: Path) -> None:
        """Test that deeply nested directories work correctly."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(create_skill_md())

        # Create deeply nested structure: assets/templates/email/welcome.txt
        assets_dir = skill_dir / "assets"
        assets_dir.mkdir()
        templates_dir = assets_dir / "templates"
        templates_dir.mkdir()
        email_dir = templates_dir / "email"
        email_dir.mkdir()
        (email_dir / "welcome.txt").write_text("Welcome!")

        result = _read_skill(skill_dir)

        assert len(result.assets) == 1
        assert "templates/email/welcome.txt" in result.assets

    def test_subdirectories_excludes_hidden_in_path(self, tmp_path: Path) -> None:
        """Test that files in hidden directories are excluded."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(create_skill_md())

        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "visible.py").write_text("visible")

        # Hidden directory
        hidden_dir = scripts_dir / ".hidden"
        hidden_dir.mkdir()
        (hidden_dir / "secret.py").write_text("secret")

        # Private directory
        private_dir = scripts_dir / "_private"
        private_dir.mkdir()
        (private_dir / "internal.py").write_text("internal")

        # Visible directory with hidden file
        visible_dir = scripts_dir / "visible"
        visible_dir.mkdir()
        (visible_dir / "ok.py").write_text("ok")
        (visible_dir / ".hidden.py").write_text("hidden")

        result = _read_skill(skill_dir)

        assert "visible.py" in result.scripts
        assert "visible/ok.py" in result.scripts
        assert ".hidden/secret.py" not in result.scripts
        assert "_private/internal.py" not in result.scripts
        assert "visible/.hidden.py" not in result.scripts


class TestSkillParsingErrors:
    def test_directory_not_found(self, tmp_path: Path) -> None:
        """Test error when skill directory doesn't exist."""
        with pytest.raises(SkillParsingError) as exc_info:
            _read_skill(tmp_path / "nonexistent")

        assert "does not exist" in str(exc_info.value)

    def test_not_a_directory(self, tmp_path: Path) -> None:
        """Test error when location is a file, not a directory."""
        file_path = tmp_path / "not-a-dir"
        file_path.write_text("content")

        with pytest.raises(SkillParsingError) as exc_info:
            _read_skill(file_path)

        assert "not a directory" in str(exc_info.value)

    def test_missing_skill_md(self, tmp_path: Path) -> None:
        """Test error when SKILL.md is missing."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()

        with pytest.raises(SkillParsingError) as exc_info:
            _read_skill(skill_dir)

        assert "SKILL.md not found" in str(exc_info.value)

    def test_invalid_yaml_frontmatter(self, tmp_path: Path) -> None:
        """Test error when YAML frontmatter is invalid."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: [invalid yaml
---
# Instructions
""")

        with pytest.raises(SkillParsingError) as exc_info:
            _read_skill(skill_dir)

        assert "Invalid YAML" in str(exc_info.value)

    def test_missing_required_name(self, tmp_path: Path) -> None:
        """Test error when required 'name' field is missing."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
description: A test skill
---
# Instructions
""")

        with pytest.raises(SkillParsingError) as exc_info:
            _read_skill(skill_dir)

        assert "validation error" in str(exc_info.value).lower()
        assert "'name' is a required property" in str(exc_info.value)

    def test_missing_required_description(self, tmp_path: Path) -> None:
        """Test error when required 'description' field is missing."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: test-skill
---
# Instructions
""")

        with pytest.raises(SkillParsingError) as exc_info:
            _read_skill(skill_dir)

        assert "validation error" in str(exc_info.value).lower()
        assert "'description' is a required property" in str(exc_info.value)

    def test_invalid_name_pattern_uppercase(self, tmp_path: Path) -> None:
        """Test error when name contains uppercase letters."""
        skill_dir = tmp_path / "Test-Skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(create_skill_md(name="Test-Skill"))

        with pytest.raises(SkillParsingError) as exc_info:
            _read_skill(skill_dir)

        assert "validation error" in str(exc_info.value).lower()
        assert "does not match" in str(exc_info.value)

    def test_invalid_name_pattern_starts_with_hyphen(self, tmp_path: Path) -> None:
        """Test error when name starts with hyphen."""
        skill_dir = tmp_path / "-test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(create_skill_md(name="-test-skill"))

        with pytest.raises(SkillParsingError) as exc_info:
            _read_skill(skill_dir)

        assert "validation error" in str(exc_info.value).lower()

    def test_name_mismatch_directory(self, tmp_path: Path) -> None:
        """Test error when skill name doesn't match directory name."""
        skill_dir = tmp_path / "actual-dir-name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(create_skill_md(name="different-name"))

        with pytest.raises(SkillParsingError) as exc_info:
            _read_skill(skill_dir)

        assert "does not match directory name" in str(exc_info.value)
        assert "different-name" in str(exc_info.value)
        assert "actual-dir-name" in str(exc_info.value)

    def test_additional_properties_rejected(self, tmp_path: Path) -> None:
        """Test error when unknown frontmatter fields are provided."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            create_skill_md(extra_frontmatter="unknown-field: value\n")
        )

        with pytest.raises(SkillParsingError) as exc_info:
            _read_skill(skill_dir)

        assert "Additional properties are not allowed" in str(exc_info.value)

    def test_no_frontmatter(self, tmp_path: Path) -> None:
        """Test error when SKILL.md has no frontmatter."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Just markdown\n\nNo frontmatter here.")

        with pytest.raises(SkillParsingError) as exc_info:
            _read_skill(skill_dir)

        assert "validation error" in str(exc_info.value).lower()


class TestSkillMd:
    def test_skill_md_minimal(self) -> None:
        """Test rendering skill with only required fields."""
        s = Skill(
            name="test-skill",
            description="A test skill",
            instructions="# Instructions\n\nDo the thing.",
        )

        result = s.skill_md()

        assert result.startswith("---\n")
        assert "name: test-skill" in result
        assert "description: A test skill" in result
        assert "---\n\n# Instructions" in result
        assert "Do the thing." in result

    def test_skill_md_with_optional_fields(self) -> None:
        """Test rendering skill with all optional fields."""
        s = Skill(
            name="test-skill",
            description="A test skill",
            instructions="# Instructions",
            license="MIT",
            compatibility="Python 3.10+",
            metadata={"version": "1.0", "author": "Test"},
            allowed_tools="bash python",  # type: ignore[call-arg]
        )

        result = s.skill_md()

        assert "name: test-skill" in result
        assert "license: MIT" in result
        assert "compatibility: Python 3.10+" in result
        assert "allowed-tools: bash python" in result
        assert "metadata:" in result
        assert "version:" in result

    def test_skill_md_excludes_none_values(self) -> None:
        """Test that None values are not included in frontmatter."""
        s = Skill(
            name="test-skill",
            description="A test skill",
            instructions="# Instructions",
            license=None,
            compatibility=None,
            metadata=None,
            allowed_tools=None,  # type: ignore[call-arg]
        )

        result = s.skill_md()

        assert "license:" not in result
        assert "compatibility:" not in result
        assert "metadata:" not in result
        assert "allowed-tools:" not in result
        assert "null" not in result.lower()

    def test_skill_md_roundtrip(self, tmp_path: Path) -> None:
        """Test that parse -> render -> parse produces equivalent skill."""
        # Create original skill
        original = Skill(
            name="test-skill",
            description="A test skill for roundtrip",
            instructions="# Instructions\n\nStep 1: Do this.\nStep 2: Do that.",
            license="MIT",
            compatibility="Python 3.10+",
            metadata={"version": "1.0"},
            allowed_tools="bash",  # type: ignore[call-arg]
        )

        # Render to SKILL.md content
        skill_md_content = original.skill_md()

        # Write to disk and parse back
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(skill_md_content)

        parsed = _read_skill(skill_dir)

        # Compare key fields (scripts/references/assets will differ as they come from dirs)
        assert parsed.name == original.name
        assert parsed.description == original.description
        assert parsed.instructions == original.instructions
        assert parsed.license == original.license
        assert parsed.compatibility == original.compatibility
        assert parsed.metadata == original.metadata
        assert parsed.allowed_tools == original.allowed_tools


@skip_if_no_openai
@skip_if_no_docker
@pytest.mark.slow
@flaky_retry(max_retries=3)
def test_skill_end_to_end() -> None:
    """Test that the skill tool works end-to-end with Docker sandbox.

    This test verifies that:
    1. The model invokes the skill to get instructions
    2. The model reads the asset file (contains ALPHA-BRAVO-CHARLIE)
    3. The model runs the provided script (outputs DELTA-ECHO-FOXTROT)
    """
    task = Task(
        dataset=[
            Sample(
                input=(
                    "What is the secret code? You MUST first read the asset file "
                    "and tell me what it contains, then run the script to get the answer."
                ),
                target=["ALPHA-BRAVO-CHARLIE", "DELTA-ECHO-FOXTROT"],
            ),
        ],
        solver=react(
            prompt=(
                "You have access to a skill that will tell you how to find the secret code. "
                "Use the skill tool first to get instructions, then follow them exactly. "
                "You must read the asset file AND run the script as instructed."
            ),
            tools=[
                skill([SKILLS_DIR / "secret-code"]),
                bash(),
            ],
        ),
        message_limit=20,
        scorer=includes(),
        sandbox=("docker", str(SKILLS_DIR / "compose.yaml")),
    )

    result = eval(
        task,
        model="openai/gpt-5.3-codex",
    )[0]

    assert result.status == "success", f"Eval failed with status: {result.status}"

    # Get the final model output
    samples = result.samples
    assert samples is not None and len(samples) > 0

    sample = samples[0]
    messages = sample.messages

    # Find all assistant messages and tool outputs to check content
    all_content = []
    for msg in messages:
        if hasattr(msg, "content"):
            if isinstance(msg.content, str):
                all_content.append(msg.content)
            elif isinstance(msg.content, list):
                for item in msg.content:
                    if hasattr(item, "text"):
                        all_content.append(item.text)

    combined_output = " ".join(all_content)

    # Verify the model read the asset (ALPHA-BRAVO-CHARLIE should appear)
    assert "ALPHA-BRAVO-CHARLIE" in combined_output, (
        "Model did not read the asset file. "
        f"Expected 'ALPHA-BRAVO-CHARLIE' in output but got: {combined_output[:500]}..."
    )

    # Verify the model ran the script (DELTA-ECHO-FOXTROT should appear)
    assert "DELTA-ECHO-FOXTROT" in combined_output, (
        "Model did not run the script. "
        f"Expected 'DELTA-ECHO-FOXTROT' in output but got: {combined_output[:500]}..."
    )


class _FileSandbox(CannedSandbox):
    """Keeps written files in memory and answers the installer's commands.

    `pwd` gives /work, the digest script hashes the in-memory file, `chown`
    records the owner, `rm -f` removes the file, and writes yield so
    concurrent installs interleave.
    """

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        super().__init__(self._answer)
        self.files = dict(files or {})
        self.owners: dict[str, str] = {}

    def _answer(self, cmd: list[str], user: str | None) -> ExecResult[str]:
        if cmd[-1] == "pwd":
            return ExecResult(True, 0, "/work", "")
        if "sha256sum" in cmd[2]:
            contents = self.files.get(cmd[-1])
            if contents is None:
                return ExecResult(True, 0, "missing\n", "")
            return ExecResult(
                True, 0, f"{hashlib.sha256(contents).hexdigest()}  -\n", ""
            )
        if cmd[4:5] == ["chown"]:
            self.owners[cmd[-1]] = cmd[-2]
        if cmd[4:6] == ["rm", "-f"]:
            self.files.pop(cmd[-1], None)
            self.owners.pop(cmd[-1], None)
        return ExecResult(True, 0, "", "")

    async def write_file(self, file: str, contents: str | bytes) -> None:
        await anyio.lowlevel.checkpoint()
        await super().write_file(file, contents)
        self.files[file] = contents.encode() if isinstance(contents, str) else contents


class _BlockingSandbox(_FileSandbox):
    """Blocks the first `stage` (write, chown or chmod) of an install.

    The blocked operation waits for `release`. If its caller is cancelled
    first, the backend still carries it out later, as a detached
    `docker exec` can: a write lands half the file and a command runs. These
    late effects are kept until `apply_late()`.
    """

    def __init__(self, stage: str) -> None:
        super().__init__()
        self.stage = stage
        self.block = True
        self.blocked = anyio.Event()
        self.release = anyio.Event()
        self.blocked_path = ""
        self.late_files: dict[str, bytes] = {}
        self.late_cmds: list[list[str]] = []
        self.finalized: list[tuple[str, str]] = []

    async def _block(self, path: str) -> None:
        self.block = False
        self.blocked_path = path
        self.blocked.set()
        await self.release.wait()

    def apply_late(self) -> None:
        self.files.update(self.late_files)
        for cmd in self.late_cmds:
            self._answer(cmd, None)

    async def write_file(self, file: str, contents: str | bytes) -> None:
        if self.stage == "write" and self.block:
            try:
                await self._block(file)
            except anyio.get_cancelled_exc_class():
                data = contents.encode() if isinstance(contents, str) else contents
                self.late_files[file] = data[: len(data) // 2]
                raise
        await super().write_file(file, contents)

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        if cmd[4:5] == [self.stage] and self.block:
            try:
                await self._block(cmd[-1])
            except anyio.get_cancelled_exc_class():
                self.late_cmds.append(cmd)
                raise
        if cmd[4:5] in (["chown"], ["chmod"]):
            self.finalized.append((cmd[4], cmd[-1]))
        return await super().exec(
            cmd, input, cwd, env, user, timeout, timeout_retry, concurrency
        )


class _CountingLocalSandbox(LocalSandboxEnvironment):
    def __init__(self) -> None:
        super().__init__()
        self.written: list[str] = []

    async def write_file(self, file: str, contents: str | bytes) -> None:
        self.written.append(file)
        await super().write_file(file, contents)


def _use_sandbox(sandbox: SandboxEnvironment) -> None:
    sandbox_environments_context_var.set({"default": sandbox})
    sandbox_default_context_var.set("default")


class TestSkillToolStateScope:
    SKILL = Skill(name="example", description="Example.", instructions="Do it.")
    OTHER = Skill(name="example", description="Example.", instructions="Other.")

    @pytest.fixture
    def sandbox(self) -> _FileSandbox:
        """A sandbox that keeps written files in memory."""
        return _FileSandbox()

    async def test_default_skill_tool_is_per_scope(self, sandbox: _FileSandbox) -> None:
        _use_sandbox(sandbox)
        init_subtask_store(Store())
        tool = skill([self.SKILL])
        with tool_state_scope("w-1"):
            await tool(command="example")
            await tool(command="example")
        with tool_state_scope("w-2"):
            await tool(command="example")
        assert sandbox.written == ["/work/skills/example/SKILL.md"]
        assert "InstalledSkills:skills" not in store()
        assert store().get("InstalledSkills:@w-1:skills") is not None
        assert store().get("InstalledSkills:@w-2:skills") is not None

    async def test_deepagent_child_skill_tool_is_per_scope(
        self, sandbox: _FileSandbox
    ) -> None:
        from inspect_ai.agent._deepagent.agent_tool import _resolve_tools
        from inspect_ai.agent._deepagent.subagent import subagent

        _use_sandbox(sandbox)
        init_subtask_store(Store())
        sa = subagent(name="general", description="General.", prompt="General.")

        async def call_child_skill() -> None:
            tools = _resolve_tools(
                sa, [sa], None, None, [self.SKILL], 0, 1, get_messages=None
            )
            [child_skill] = [
                t for t in tools if isinstance(t, Tool) and ToolDef(t).name == "skill"
            ]
            await child_skill(command="example")

        with tool_state_scope("w-1"):
            await call_child_skill()
        with tool_state_scope("w-2"):
            await call_child_skill()
        assert sandbox.written == ["/work/skills/example/SKILL.md"]
        assert "InstalledSkills:general:skills" not in store()
        assert store().get("InstalledSkills:@w-1#general:skills") is not None
        assert store().get("InstalledSkills:@w-2#general:skills") is not None

        # outside a scope the subagent name is today's instance
        await call_child_skill()
        assert store().get("InstalledSkills:general:skills") is not None

    async def test_concurrent_first_calls_across_scopes_install_once(
        self, sandbox: _FileSandbox
    ) -> None:
        _use_sandbox(sandbox)
        init_subtask_store(Store())
        skill_with_script = Skill(
            name="example",
            description="Example.",
            instructions="Do it.",
            scripts={"run.sh": "echo hello"},
        )
        tool = skill([skill_with_script])

        async def call_in_scope(name: str) -> None:
            with tool_state_scope(name):
                await tool(command="example")

        async with anyio.create_task_group() as tg:
            tg.start_soon(call_in_scope, "w-1")
            tg.start_soon(call_in_scope, "w-2")

        assert sandbox.written == [
            "/work/skills/example/SKILL.md",
            "/work/skills/example/scripts/run.sh",
        ]
        assert store().get("InstalledSkills:@w-1:skills") is not None
        assert store().get("InstalledSkills:@w-2:skills") is not None

    async def test_conflicting_skill_contents_raise(
        self, sandbox: _FileSandbox
    ) -> None:
        _use_sandbox(sandbox)
        init_subtask_store(Store())
        with tool_state_scope("w-1"):
            await skill([self.SKILL])(command="example")
        with tool_state_scope("w-2"):
            with pytest.raises(
                RuntimeError,
                match="/work/skills/example/SKILL.md already exists in the sandbox with different contents",
            ):
                await skill([self.OTHER])(command="example")
        assert sandbox.written == ["/work/skills/example/SKILL.md"]
        assert sandbox.files["/work/skills/example/SKILL.md"] == (
            self.SKILL.skill_md().encode()
        )

    async def test_existing_sandbox_files_are_compared(self) -> None:
        """Files already in the sandbox (a resumed sandbox or the image) count."""
        path = "/work/skills/example/SKILL.md"
        same = _FileSandbox({path: self.SKILL.skill_md().encode()})
        _use_sandbox(same)
        init_subtask_store(Store())
        await skill([self.SKILL])(command="example")
        assert same.written == []

        different = _FileSandbox({path: b"other"})
        _use_sandbox(different)
        init_subtask_store(Store())
        with pytest.raises(RuntimeError, match="different contents"):
            await skill([self.SKILL])(command="example")
        assert different.written == []
        assert different.files[path] == b"other"

    async def test_aliased_skill_dirs_compare_the_same_files(self) -> None:
        if os.name != "posix":
            pytest.skip("requires POSIX symlinks")
        local = _CountingLocalSandbox()
        try:
            _use_sandbox(local)
            init_subtask_store(Store())
            root = Path(local.directory.name)
            (root / "other" / "child").mkdir(parents=True)
            (root / "other" / "skills").mkdir()
            (root / "link").symlink_to(root / "other" / "skills")
            (root / "child-link").symlink_to(root / "other" / "child")
            aliases = [
                f"{root}/link",  # symlink
                f"{root}/other/skills/../skills",  # ..
                f"{root}/child-link/../skills",  # symlink then ..
            ]
            with tool_state_scope("w-0"):
                await skill([self.SKILL], dir=f"{root}/other/skills")(command="example")
            for scope, dir in zip(["w-1", "w-2", "w-3"], aliases):
                with tool_state_scope(scope):
                    await skill([self.SKILL], dir=dir)(command="example")
            assert len(local.written) == 1

            for dir in aliases:
                with tool_state_scope("w-4"):
                    with pytest.raises(RuntimeError, match="different contents"):
                        await skill([self.OTHER], dir=dir)(command="example")
            assert len(local.written) == 1
            skill_md = root / "other" / "skills" / "example" / "SKILL.md"
            assert skill_md.read_text() == self.SKILL.skill_md()
        finally:
            local.directory.cleanup()

    @pytest.mark.parametrize("wrapper", ["subtask", "fork"])
    @pytest.mark.parametrize("conflict", [False, True])
    def test_installs_through_subtask_and_fork_branches(
        self, wrapper: str, conflict: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        written: list[str] = []
        local_write_file = LocalSandboxEnvironment.write_file

        async def counting_write_file(
            self: LocalSandboxEnvironment, file: str, contents: str | bytes
        ) -> None:
            written.append(file)
            await local_write_file(self, file, contents)

        monkeypatch.setattr(LocalSandboxEnvironment, "write_file", counting_write_file)

        first = self.SKILL
        second = self.OTHER if conflict else self.SKILL

        @solver
        def install(scope: str, sk: Skill) -> Solver:
            async def solve(state: TaskState, generate: Generate) -> TaskState:
                with tool_state_scope(scope):
                    await skill([sk])(command="example")
                return state

            return solve

        @subtask
        async def install_subtask(scope: str, sk: Skill) -> None:
            with tool_state_scope(scope):
                await skill([sk])(command="example")

        @solver
        def branches() -> Solver:
            async def solve(state: TaskState, generate: Generate) -> TaskState:
                if wrapper == "fork":
                    await fork(state, [install("w-1", first), install("w-2", second)])
                else:
                    await install_subtask("w-1", first)
                    await install_subtask("w-2", second)
                return state

            return solve

        log = eval(
            Task(dataset=[Sample(input="x")], solver=branches(), sandbox="local"),
            model="mockllm/model",
        )[0]
        assert log.samples is not None
        error = log.samples[0].error
        if conflict:
            assert error is not None and "different contents" in error.message
        else:
            assert error is None
        assert len(written) == 1 and written[0].endswith("skills/example/SKILL.md")

    @pytest.mark.parametrize("stage", ["write", "chown", "chmod"])
    async def test_interrupted_install_is_redone(self, stage: str) -> None:
        sandbox = _BlockingSandbox(stage)
        _use_sandbox(sandbox)
        init_subtask_store(Store())
        with_script = Skill(
            name="example",
            description="Example.",
            instructions="Do it.",
            scripts={"run.sh": "echo hello"},
        )

        async def first_install() -> None:
            with tool_state_scope("w-1"):
                await skill([with_script], user="1000")(command="example")

        async with anyio.create_task_group() as tg:
            tg.start_soon(first_install)
            await sandbox.blocked.wait()
            tg.cancel_scope.cancel()
            sandbox.release.set()
        assert sandbox.blocked_path

        sandbox.finalized.clear()
        with tool_state_scope("w-2"):
            await skill([with_script], user="2000")(command="example")
        # whatever the cancelled install left running lands now
        sandbox.apply_late()
        expected = {
            "/work/skills/example/SKILL.md": with_script.skill_md().encode(),
            "/work/skills/example/scripts/run.sh": b"echo hello",
        }
        assert sandbox.files == expected
        assert sandbox.owners == {path: "2000" for path in expected}
        assert ("chown" if stage == "write" else stage, sandbox.blocked_path) in (
            sandbox.finalized
        )

    async def test_cancelled_install_starts_no_further_files(self) -> None:
        sandbox = _BlockingSandbox("write")
        _use_sandbox(sandbox)
        init_subtask_store(Store())
        full = Skill(
            name="example",
            description="Example.",
            instructions="Do it.",
            scripts={"run.sh": "echo hello"},
            references={"ref.md": "ref"},
            assets={"data.txt": "data"},
        )

        async def install() -> None:
            await skill([full])(command="example")

        async with anyio.create_task_group() as tg:
            tg.start_soon(install)
            await sandbox.blocked.wait()
            tg.cancel_scope.cancel()
            sandbox.release.set()

        # the write in flight finishes; nothing after it starts
        assert sandbox.files == {
            "/work/skills/example/SKILL.md": full.skill_md().encode()
        }
        assert sandbox.written == ["/work/skills/example/SKILL.md"]
        assert not install_lock(sandbox).locked()

    async def test_failed_write_is_removed(self) -> None:
        class FailingSandbox(_FileSandbox):
            fail = True

            async def write_file(self, file: str, contents: str | bytes) -> None:
                if self.fail:
                    self.fail = False
                    self.files[file] = b"part"
                    raise RuntimeError("write failed")
                await super().write_file(file, contents)

        sandbox = FailingSandbox()
        _use_sandbox(sandbox)
        init_subtask_store(Store())
        with tool_state_scope("w-1"):
            with pytest.raises(RuntimeError, match="write failed"):
                await skill([self.SKILL])(command="example")
        assert sandbox.files == {}
        with tool_state_scope("w-2"):
            await skill([self.SKILL])(command="example")
        assert sandbox.files == {
            "/work/skills/example/SKILL.md": self.SKILL.skill_md().encode()
        }

    @pytest.mark.parametrize("second_sandbox", [None, "other"])
    async def test_concurrent_first_calls_for_one_instance_keep_the_first_list(
        self, second_sandbox: str | None
    ) -> None:
        sandbox = _BlockingSandbox("write")
        other = _FileSandbox()
        sandbox_environments_context_var.set({"default": sandbox, "other": other})
        sandbox_default_context_var.set("default")
        init_subtask_store(Store())
        alpha = Skill(name="alpha", description="Alpha.", instructions="Alpha.")
        beta = Skill(name="beta", description="Beta.", instructions="Beta.")
        first = skill([alpha], instance="team")
        second = skill([beta], instance="team", sandbox=second_sandbox)
        errors: list[str] = []

        async def call_second() -> None:
            try:
                await second(command="beta")
            except ToolError as ex:
                errors.append(ex.message)

        async with anyio.create_task_group() as tg:
            tg.start_soon(first, "alpha")
            await sandbox.blocked.wait()
            tg.start_soon(call_second)
            while _cache_lock(store(), "team").statistics().tasks_waiting == 0:
                await anyio.lowlevel.checkpoint()
            sandbox.release.set()

        # as before tool state scopes: the first tool to install sets the list
        assert errors == ["Unknown skill: beta"]
        await first(command="alpha")
        with pytest.raises(ToolError, match="Unknown skill: beta"):
            await second(command="beta")
        assert list(sandbox.files) == ["/work/skills/alpha/SKILL.md"]
        assert other.files == {}

    async def test_existing_identical_script_is_made_executable(self) -> None:
        local = _CountingLocalSandbox()
        try:
            _use_sandbox(local)
            init_subtask_store(Store())
            dir = Path(local.directory.name) / "skills"
            contents = "#!/bin/sh\necho hello\n"
            with_script = Skill(
                name="example",
                description="Example.",
                instructions="Do it.",
                scripts={"run.sh": contents},
            )
            script = dir / "example" / "scripts" / "run.sh"
            script.parent.mkdir(parents=True)
            script.write_text(contents)
            script.chmod(0o644)
            (dir / "example" / "SKILL.md").write_text(with_script.skill_md())

            await skill([with_script], dir=str(dir))(command="example")
            assert local.written == []
            assert os.access(script, os.X_OK)
        finally:
            local.directory.cleanup()

    async def test_file_names_with_the_same_path_are_refused(
        self, sandbox: _FileSandbox
    ) -> None:
        _use_sandbox(sandbox)
        init_subtask_store(Store())
        aliased = self.SKILL.model_copy(
            update={"assets": {"file.txt": "first", "./file.txt": "second"}}
        )
        with pytest.raises(
            ValueError,
            match="Skill 'example' has assets file names 'file.txt' and './file.txt'",
        ):
            await skill([aliased])(command="example")
        assert sandbox.written == []

    async def test_non_canonical_file_name_installs_at_normalized_path(
        self, sandbox: _FileSandbox
    ) -> None:
        _use_sandbox(sandbox)
        init_subtask_store(Store())
        dotted = self.SKILL.model_copy(update={"assets": {"./file.txt": "data"}})
        with tool_state_scope("w-1"):
            await skill([dotted])(command="example")
        with tool_state_scope("w-2"):
            await skill([dotted])(command="example")
        assert sandbox.written == [
            "/work/skills/example/SKILL.md",
            "/work/skills/example/assets/file.txt",
        ]

    @pytest.mark.parametrize("name", ["", "/etc/passwd", "../file.txt", "a/../b"])
    async def test_file_names_outside_their_directory_are_refused(
        self, sandbox: _FileSandbox, name: str
    ) -> None:
        _use_sandbox(sandbox)
        init_subtask_store(Store())
        bad = self.SKILL.model_copy(update={"references": {name: "data"}})
        with pytest.raises(
            ValueError,
            match=f"Skill 'example' has an invalid references file name '{re.escape(name)}'",
        ):
            await skill([bad])(command="example")
        assert sandbox.written == []

    async def test_nested_file_names_are_accepted(self, sandbox: _FileSandbox) -> None:
        _use_sandbox(sandbox)
        init_subtask_store(Store())
        nested = self.SKILL.model_copy(
            update={
                "scripts": {"tools/run.sh": "echo hi"},
                "assets": {"a/b/c.txt": "c"},
            }
        )
        await skill([nested])(command="example")
        assert sandbox.written == [
            "/work/skills/example/SKILL.md",
            "/work/skills/example/scripts/tools/run.sh",
            "/work/skills/example/assets/a/b/c.txt",
        ]

    async def test_comparison_is_not_limited_by_read_file_size(self) -> None:
        local = _CountingLocalSandbox()
        try:
            _use_sandbox(local)
            init_subtask_store(Store())
            dir = f"{local.directory.name}/skills"
            asset = f"{dir}/example/assets/data.bin"
            large = Skill(
                name="example",
                description="Example.",
                instructions="Do it.",
                assets={"data.bin": b"x" * 256},
            )
            different = large.model_copy(update={"assets": {"data.bin": b"y" * 256}})
            with override_max_read_file_size(128):
                with tool_state_scope("w-1"):
                    await skill([large], dir=dir)(command="example")
                with tool_state_scope("w-2"):
                    await skill([large], dir=dir)(command="example")
                with tool_state_scope("w-3"):
                    with pytest.raises(RuntimeError, match="different contents"):
                        await skill([different], dir=dir)(command="example")
                assert len(local.written) == 2
                with pytest.raises(OutputLimitExceededError):
                    await local.read_file(asset, text=False)
        finally:
            local.directory.cleanup()
