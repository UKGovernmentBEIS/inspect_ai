"""End-to-end tests for the skill() tool."""

from pathlib import Path

import pytest
from test_helpers.utils import flaky_retry, skip_if_no_docker, skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.tool import bash, skill
from inspect_ai.tool._tools._skill.read import SkillParsingError, _read_skill
from inspect_ai.tool._tools._skill.types import Skill

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
        model="openai/gpt-5.1-codex",
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
