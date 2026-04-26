from pathlib import Path
from typing import Literal, Sequence

from inspect_ai.model._model import Model
from inspect_ai.tool._tool import Tool, ToolSource
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._skill import Skill
from inspect_ai.util._limit import Limit

from .subagent import Subagent
from .subagent import subagent as subagent_factory

DEFAULT_GENERAL_PROMPT = """
You are a general-purpose agent. Your job is to complete the task you've
been given autonomously.

Work through the task step by step. Use your available tools as needed.
Keep going until the task is fully resolved — don't stop at the first
obstacle. If something doesn't work, diagnose the issue and try a
different approach.

Verify your results before finishing. Check that your output actually
meets the requirements, not just that it ran without errors. If
verification reveals problems, fix them.

Report the outcome and key results directly, not a step-by-step
replay of actions taken. If you could not fully complete the task,
state what you accomplished and what remains.
""".strip()


def general(
    *,
    tools: Sequence[Tool | ToolDef | ToolSource] | Literal["default"] = "default",
    extra_tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    instructions: str | None = None,
    skills: list[str | Path | Skill] | None = None,
    memory: Literal["readwrite", "readonly"] | bool = False,
    limits: list[Limit] | None = None,
    model: str | Model | None = None,
    fork: bool = False,
) -> Subagent:
    """Create a general-purpose subagent with full tool access.

    The general subagent inherits the parent agent's tools (including
    skills) by default and has read-write memory access. It is intended for
    tasks that require full capabilities in an isolated context.

    Args:
        tools: Tools for this subagent. "default" inherits the parent
            agent's tools. Pass a list to replace defaults entirely.
        extra_tools: Additional tools added on top of the default or
            custom tools.
        instructions: Additional instructions appended to the default
            general prompt.
        skills: Subagent-specific skills (merged with parent skills).
        memory: Memory access level ("readwrite", "readonly", or False).
        limits: Scoped limits for each invocation.
        model: Model override (None inherits from parent).
        fork: If True, inherits parent conversation context.
            Use same model or model family as parent to preserve
            the prompt cache and avoid errors from incompatible
            tool call formats or reasoning content.
    """
    prompt = DEFAULT_GENERAL_PROMPT
    if instructions:
        prompt = f"{prompt}\n\n{instructions}"

    resolved_tools = None if tools == "default" else list(tools)

    return subagent_factory(
        name="general",
        description="General-purpose autonomous task completion.",
        prompt=prompt,
        tools=resolved_tools,
        extra_tools=extra_tools,
        model=model,
        fork=fork,
        skills=skills,
        memory=memory,
        limits=limits,
    )
