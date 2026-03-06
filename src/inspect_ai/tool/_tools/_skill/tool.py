from pathlib import Path
from textwrap import dedent
from typing import Sequence

from pydantic import Field

from inspect_ai.tool._tool import Tool, ToolError, tool
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util._store_model import StoreModel, store_as

from .install import install_skills
from .read import read_skills
from .types import Skill, SkillInfo


@tool
def skill(
    skills: Sequence[str | Path | Skill],
    *,
    sandbox: str | None = None,
    user: str | None = None,
    dir: str | None = None,
) -> Tool:
    """Make skills available to an agent.

    See the `Skill` documentation for details on defining skills.

    Args:
        skills: Agent skill specifications. Either a directory containing a skill or a full `Skill` specification.
        sandbox: Sandbox environment name to copy skills to.
        user: User to write skills files with.
        dir: Directory to install into (defaults to "./skills").
    """
    # resolve skills
    resolved_skills = read_skills(skills)

    async def execute(command: str) -> str:
        """Execute a skill within the main conversation.

        Args:
           command: The skill name (no arguments). E.g., "pdf" or "xlsx"
        """
        # see if we need to install the skills
        installed = store_as(InstalledSkills)
        if installed.skills is None:
            installed.skills = await install_skills(resolved_skills, sandbox, user, dir)

        # lookup skill
        skill_info = next((si for si in installed.skills if si.name == command), None)
        if skill_info is None:
            raise ToolError(f"Unknown skill: {command}")

        # return indicating the skill is running along with skill dir/instructions
        lines = [
            f'<command-message>The "{skill_info.name}" skill is running</command-message>',
            f"<command-name>{skill_info.name}</command-name>",
            "",
            f"Base Path: {skill_info.location}",
            "",
            skill_info.instructions,
        ]
        return "\n".join(lines)

    # skills prompt (derived from claude code and codex cli skills prompts)
    description = dedent(rf"""
    Invoke a skill to get specialized instructions for a task.

    <skills_instructions>
    Skills provide specialized capabilities and domain knowledge. Each skill contains instructions, and may include scripts, references, and assets.

    When to use:
    - Before starting a task, check if any skill in <available_skills> matches the request
    - Use the description field to determine relevance

    How to invoke:
    - Call this tool with the skill name only
    - Example: command: "pdf"
    - Example: command: "research"

    After invoking:
    - Follow the instructions returned by the skill
    - If the skill references folders like `references/`, `scripts/`, or `assets/` load only the specific files needed — don't bulk-load
    - If specific files are referended, their paths are relative to the indicated Base Path.
    - If scripts exist, prefer running them over rewriting equivalent code
    - If assets or templates exist, reuse them instead of recreating from scratch

    Multiple skills:
    - If multiple skills apply, choose the minimal set and invoke them in sequence
    - State which skills you're using and why

    Important:
    - When a skill is relevant, invoke this tool IMMEDIATELY as your first action — NEVER just mention a skill without actually calling this tool
    - Invoke the skill tool BEFORE generating any other response about the task
    - Only invoke skills listed in <available_skills>
    - Do not invoke a skill that is already running
    - If a skill can't be applied (missing files, unclear instructions), state the issue and proceed with the best alternative
    </skills_instructions>

    {_available_skills(resolved_skills)}
    """)

    return ToolDef(execute, name="skill", description=description).as_tool()


class InstalledSkills(StoreModel):
    skills: list[SkillInfo] | None = Field(default=None)


def _available_skills(skills: Sequence[Skill]) -> str:
    prompt = ["<available_skills>"]
    for skill_info in skills:
        prompt.extend(
            [
                "<skill>",
                f"<name>{skill_info.name}</name>",
                f"<description>{skill_info.description}</description></skill>",
            ]
        )
    prompt.append("</available_skills>")
    return "\n".join(prompt)
