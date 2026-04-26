from pathlib import Path
from typing import Literal, Sequence

from inspect_ai.model._model import Model
from inspect_ai.tool._tool import Tool, ToolSource
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._skill import Skill
from inspect_ai.util._limit import Limit

from .subagent import Subagent
from .subagent import subagent as subagent_factory

DEFAULT_RESEARCH_PROMPT = """
You are a research agent with read-only access. Your job is to gather
and synthesize information relevant to the task you've been given.
You cannot modify files or run destructive commands — only read, search,
and analyze.

Use your available tools to investigate thoroughly. Try multiple search
strategies if your first approach doesn't find what you need — different
queries, different paths, different sources. Batch parallel tool calls
when searching across multiple files or paths. Cross-reference findings
when possible to verify accuracy.

Focus on finding specific, actionable information rather than making
assumptions. If you find partial or conflicting information, report
what you found and note the gaps or conflicts.

Return your findings directly with specific details and evidence.
Lead with the most important results, not a narrative of your search
process. If information is incomplete or conflicting, state what you
found and what remains uncertain.
""".strip()


def research(
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
    """Create a research subagent for read-only information gathering.

    The research subagent is configured with read-only tools by default
    and is intended for tasks that involve gathering and synthesizing
    information without modifying state.

    Args:
        tools: Tools for this subagent. "default" provides read-only
            sandbox tools (read_file, list_files, grep) when a sandbox
            is available. Pass a list to replace defaults entirely.
        extra_tools: Additional tools added on top of the default or
            custom tools.
        instructions: Additional instructions appended to the default
            research prompt.
        skills: Subagent-specific skills (merged with parent skills).
        memory: Memory access level ("readonly", "readwrite", or False).
        limits: Scoped limits for each invocation.
        model: Model override (None inherits from parent).
        fork: If True, inherits parent conversation context.
            Use same model or model family as parent to preserve
            the prompt cache and avoid errors from incompatible
            tool call formats or reasoning content.
    """
    prompt = DEFAULT_RESEARCH_PROMPT
    if instructions:
        prompt = f"{prompt}\n\n{instructions}"

    resolved_tools = None if tools == "default" else list(tools)

    return subagent_factory(
        name="research",
        description="Search, read, and analyze information. Use for investigative tasks that require gathering data from multiple sources.",
        prompt=prompt,
        tools=resolved_tools,
        extra_tools=extra_tools,
        model=model,
        fork=fork,
        skills=skills,
        memory=memory,
        limits=limits,
    )
