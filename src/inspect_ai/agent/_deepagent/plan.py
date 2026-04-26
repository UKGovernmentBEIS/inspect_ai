from typing import Literal, Sequence

from inspect_ai.model._model import Model
from inspect_ai.tool._tool import Tool, ToolSource
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util._limit import Limit

from .subagent import Subagent
from .subagent import subagent as subagent_factory

DEFAULT_PLAN_PROMPT = """
You are a planning agent. Your job is to analyze a task and produce a
structured plan for accomplishing it.

Use your available tools to understand the current state, constraints,
and what resources are available. Don't plan in the abstract — ground
your plan in what you actually observe.

Break the work into concrete, actionable steps. Each step should be
specific enough to execute without ambiguity. Identify dependencies
between steps, potential risks, and any information gaps that could
block progress.

Return a clear, ordered plan. Flag any assumptions you're making and
any decisions that need input before proceeding. If the task can be
approached multiple ways, recommend one approach and briefly note why.
""".strip()


def plan(
    *,
    tools: Sequence[Tool | ToolDef | ToolSource] | Literal["default"] = "default",
    extra_tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    instructions: str | None = None,
    memory: Literal["readwrite", "readonly"] | bool = "readonly",
    limits: list[Limit] | None = None,
    model: str | Model | None = None,
    fork: bool = False,
) -> Subagent:
    """Create a plan subagent for structured planning.

    The plan subagent is configured with read-only tools by default
    and is intended for analyzing tasks and producing structured
    implementation plans without executing changes.

    Args:
        tools: Tools for this subagent. "default" provides read-only
            sandbox tools (read_file, list_files, grep) when a sandbox
            is available. Pass a list to replace defaults entirely.
        extra_tools: Additional tools added on top of the default or
            custom tools.
        instructions: Additional instructions appended to the default
            plan prompt.
        memory: Memory access level ("readonly", "readwrite", or False).
        limits: Scoped limits for each invocation.
        model: Model override (None inherits from parent).
        fork: If True, inherits parent conversation context.
            Use same model or model family as parent to preserve
            the prompt cache and avoid errors from incompatible
            tool call formats or reasoning content.
    """
    prompt = DEFAULT_PLAN_PROMPT
    if instructions:
        prompt = f"{prompt}\n\n{instructions}"

    resolved_tools = None if tools == "default" else list(tools)

    return subagent_factory(
        name="plan",
        description="Structured planning and task decomposition.",
        prompt=prompt,
        tools=resolved_tools,
        extra_tools=extra_tools,
        model=model,
        fork=fork,
        memory=memory,
        limits=limits,
    )
