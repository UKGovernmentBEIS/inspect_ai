from typing import Literal, Sequence

from inspect_ai.model._model import Model
from inspect_ai.tool._tool import Tool, ToolSource
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util._limit import Limit

from .subagent import Subagent

DEFAULT_RESEARCH_PROMPT = """\
You are a research agent. Your job is to gather and synthesize information \
relevant to the task you've been given.

Use your available tools to investigate thoroughly. Cross-reference multiple \
sources when possible. Focus on finding accurate, relevant information rather \
than making assumptions.

Return a concise summary of your findings. Include specific details, evidence, \
and references that will be useful to the caller. If you could not find \
definitive information, say so clearly and explain what you did find.\
"""


def research(
    *,
    tools: Sequence[Tool | ToolDef | ToolSource] | Literal["default"] = "default",
    extra_tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    instructions: str | None = None,
    memory: Literal["readwrite", "readonly"] | bool = "readonly",
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

    return Subagent(
        name="research",
        description="Read-only information gathering and synthesis.",
        prompt=prompt,
        tools=resolved_tools,
        extra_tools=list(extra_tools) if extra_tools else None,
        model=model,
        fork=fork,
        memory=memory,
        limits=limits,
    )
