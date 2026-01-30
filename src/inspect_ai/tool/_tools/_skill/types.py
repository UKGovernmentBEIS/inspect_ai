from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue


class Skill(BaseModel):
    """Agent skill specification.

    See https://agentskills.io/specification for additional details.
    """

    name: str = Field(max_length=64, pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    """Skill name. Max 64 characters. Lowercase letters, numbers, and hyphens only. Must not start or end with a hyphen."""

    description: str = Field(max_length=1024)
    """Describes what the skill does and when to use it. Max 1024 characters."""

    instructions: str
    """Skill instructions.

    Information agents need to perform the task effectively including step-by-step instructions, examples of inputs and outputs, and common edge cases.

    Note that the agent will load this entire file once it's decided to activate a skill so you should try to keep it under 500 lines long. You can break additional information into scripts/, references/ and assets/ directories.

    If you do use scripts/, references/, etc. you should mention them explicitly in the `instructions` so models know to read them as required.
    """

    scripts: dict[str, str | bytes | Path] = Field(default_factory=dict)
    """Executable code that agents can run.

    Scripts should:

    - Be self-contained or clearly document dependencies
    - Include helpful error messages
    - Handle edge cases gracefully

    Supported languages depend on the agent implementation. Common options include Python, Bash, and JavaScript."""

    references: dict[str, str | bytes | Path] = Field(default_factory=dict)
    """Additional documentation that agents can read when needed.

    - REFERENCE.md - Detailed technical reference
    - FORMS.md - Form templates or structured data formats
    - Domain-specific files (finance.md, legal.md, etc.)

    Keep individual reference files focused. Agents load these on demand, so smaller files mean less use of context.
    """

    assets: dict[str, str | bytes | Path] = Field(default_factory=dict)
    """Static resources.

    - Templates (document templates, configuration templates)
    - Images (diagrams, examples)
    - Data files (lookup tables, schemas)
    """

    license: str | None = Field(default=None)
    """License name or reference to a bundled license file."""

    compatibility: str | None = Field(max_length=500, default=None)
    """Indicates environment requirements (intended product, system packages, network access, etc.). Max 500 characters."""

    metadata: dict[str, JsonValue] | None = Field(default=None)
    """Arbitrary key-value mapping for additional metadata."""

    allowed_tools: str | None = Field(default=None, alias="allowed-tools")
    """Space-delimited list of pre-approved tools the skill may use. (Experimental)."""

    model_config = ConfigDict(populate_by_name=True)

    def skill_md(self) -> str:
        """Render the skill as SKILL.md content.

        Returns:
            SKILL.md formatted string with YAML frontmatter and instructions body.
        """
        # Build frontmatter dict with only non-None values
        frontmatter: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
        }
        if self.license is not None:
            frontmatter["license"] = self.license
        if self.compatibility is not None:
            frontmatter["compatibility"] = self.compatibility
        if self.metadata is not None:
            frontmatter["metadata"] = self.metadata
        if self.allowed_tools is not None:
            frontmatter["allowed-tools"] = self.allowed_tools

        # Render YAML frontmatter
        yaml_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)

        return f"---\n{yaml_str}---\n\n{self.instructions}"


class SkillInfo(BaseModel):
    """Agent skill info."""

    name: str = Field(max_length=64, pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    """Skill name. Max 64 characters. Lowercase letters, numbers, and hyphens only. Must not start or end with a hyphen."""

    description: str = Field(max_length=1024)
    """Describes what the skill does and when to use it. Max 1024 characters."""

    instructions: str
    """Skill instructions."""

    location: str
    """Full path to skill description file (SKILL.md)"""
