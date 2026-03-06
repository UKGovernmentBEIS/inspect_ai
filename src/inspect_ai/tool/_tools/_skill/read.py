from pathlib import Path
from typing import Any, Sequence

import yaml
from jsonschema import Draft7Validator

from .types import Skill


def read_skills(skills: Sequence[str | Path | Skill]) -> list[Skill]:
    """Read skill specifications.

    See the [agent skills specification](https://agentskills.io/specification) for details on defining skills.

    Args:
       skills: Directories containing SKILL.md files.

    Returns:
       List of parsed and validated Skills.

    Raises:
       SkillParsingError: If SKILL.md is missing, malformed, or invalid.
    """
    return [
        skill if isinstance(skill, Skill) else _read_skill(skill) for skill in skills
    ]


def _read_skill(location: str | Path) -> Skill:
    """Read a skill specification.

    See the [agent skills specification](https://agentskills.io/specification) for details on defining skills.

    Args:
       location: Directory containing SKILL.md file.

    Returns:
       Parsed and validated Skill object.

    Raises:
       SkillParsingError: If SKILL.md is missing, malformed, or invalid.
    """
    # Convert to Path and validate
    skill_dir = Path(location) if isinstance(location, str) else location
    skill_dir = skill_dir.absolute()

    if not skill_dir.exists():
        raise SkillParsingError(f"Skill directory does not exist: {skill_dir}")
    if not skill_dir.is_dir():
        raise SkillParsingError(f"Skill location is not a directory: {skill_dir}")

    # Check SKILL.md exists
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        raise SkillParsingError(f"SKILL.md not found in: {skill_dir}")

    # Read and parse SKILL.md
    content = skill_file.read_text(encoding="utf-8")
    frontmatter, instructions = _parse_frontmatter(content)

    # Validate frontmatter
    _validate_frontmatter(frontmatter)

    # Validate name matches directory name
    skill_name = frontmatter["name"]
    if skill_name != skill_dir.name:
        raise SkillParsingError(
            f"Skill name '{skill_name}' does not match directory name '{skill_dir.name}'"
        )

    # Enumerate optional directories
    scripts = _enumerate_directory(skill_dir / "scripts")
    references = _enumerate_directory(skill_dir / "references")
    assets = _enumerate_directory(skill_dir / "assets")

    # Construct and return Skill
    return Skill(
        name=skill_name,
        description=frontmatter["description"],
        instructions=instructions,
        scripts=scripts,
        references=references,
        assets=assets,
        license=frontmatter.get("license"),
        compatibility=frontmatter.get("compatibility"),
        metadata=frontmatter.get("metadata"),
        **{"allowed-tools": frontmatter.get("allowed-tools")},
    )


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content.

    Args:
        content: Markdown content potentially containing YAML frontmatter.

    Returns:
        Tuple of (frontmatter dict, markdown body).
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    frontmatter_str = parts[1].strip()
    body = parts[2].lstrip("\n")

    try:
        frontmatter = yaml.safe_load(frontmatter_str)
    except yaml.YAMLError as ex:
        raise SkillParsingError(f"Invalid YAML frontmatter: {ex}") from ex

    return frontmatter if isinstance(frontmatter, dict) else {}, body


def _skill_schema() -> dict[str, Any]:
    """Return JSON schema for skill frontmatter validation."""
    return {
        "type": "object",
        "required": ["name", "description"],
        "properties": {
            "name": {
                "type": "string",
                "maxLength": 64,
                "pattern": r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$",
            },
            "description": {
                "type": "string",
                "maxLength": 1024,
            },
            "license": {
                "type": "string",
            },
            "compatibility": {
                "type": "string",
                "maxLength": 500,
            },
            "metadata": {
                "type": "object",
            },
            "allowed-tools": {
                "type": "string",
            },
        },
        "additionalProperties": False,
    }


def _validate_frontmatter(frontmatter: dict[str, Any]) -> None:
    """Validate frontmatter against JSON schema.

    Args:
        frontmatter: Parsed frontmatter dictionary.

    Raises:
        SkillParsingError: If validation fails.
    """
    schema = _skill_schema()
    validator = Draft7Validator(schema)
    errors = list(validator.iter_errors(frontmatter))

    if errors:
        error_messages = [error.message for error in errors]
        message = "\n".join(
            [f"Found {len(errors)} validation error(s) parsing SKILL.md:"]
            + [f"- {msg}" for msg in error_messages]
        )
        raise SkillParsingError(message, error_messages)


def _enumerate_directory(dir_path: Path) -> dict[str, str | bytes | Path]:
    """Enumerate files in a directory recursively, returning relative_path->Path mapping.

    Args:
        dir_path: Directory to enumerate.

    Returns:
        Dictionary mapping relative path (e.g., 'bash/script.sh') to absolute path.
        Excludes files/directories starting with '.' or '_'.
    """
    if not dir_path.exists() or not dir_path.is_dir():
        return {}

    result: dict[str, str | bytes | Path] = {}
    for file_path in dir_path.rglob("*"):
        # Skip directories, only include files
        if not file_path.is_file():
            continue
        # Skip hidden files/dirs (any path component starting with . or _)
        relative = file_path.relative_to(dir_path)
        if any(part.startswith((".", "_")) for part in relative.parts):
            continue
        result[str(relative)] = file_path.absolute()

    return result


class SkillParsingError(Exception):
    """Exception raised when skill parsing fails."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        self.message = message
        self.errors = errors or []
        super().__init__(message)
