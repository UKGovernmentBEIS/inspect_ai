from dataclasses import dataclass
from typing import Literal, Sequence

from inspect_ai.model._compaction import CompactionStrategy
from inspect_ai.model._model import Model
from inspect_ai.tool._tool import Tool, ToolSource
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._skill import Skill
from inspect_ai.util._limit import Limit


@dataclass(kw_only=True)
class Subagent:
    """Configuration blueprint for a subagent within a deep agent system."""

    name: str
    """Identifier used as the subagent_type value in task() dispatch."""

    description: str
    """Role description shown in the task() tool description."""

    prompt: str
    """System prompt for the subagent's react() loop."""

    tools: list[Tool | ToolDef | ToolSource] | None = None
    """Tools available to this subagent."""

    extra_tools: list[Tool | ToolDef | ToolSource] | None = None
    """Additional tools merged with the subagent's default tools."""

    model: str | Model | None = None
    """Model override for this subagent."""

    fork: bool = False
    """Dispatch mode (False = isolated, True = forked). Use same model
    or model family as parent when forking to preserve the prompt cache
    and avoid errors from incompatible tool call formats or reasoning
    content in the inherited message history."""

    skills: list[Skill] | None = None
    """Skills available to this subagent."""

    memory: Literal["readwrite", "readonly"] | bool = "readonly"
    """Memory tool access level."""

    limits: list[Limit] | None = None
    """Scoped limits applied to each invocation of this subagent."""

    compaction: CompactionStrategy | None = None
    """Compaction strategy for context management. None inherits
    the parent agent's compaction strategy."""


def subagent(
    *,
    name: str,
    description: str,
    prompt: str,
    tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    extra_tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    model: str | Model | None = None,
    fork: bool = False,
    skills: list[Skill] | None = None,
    memory: Literal["readwrite", "readonly"] | bool = "readonly",
    limits: list[Limit] | None = None,
    compaction: CompactionStrategy | None = None,
) -> Subagent:
    """Create a subagent configuration for use within a deep agent system.

    Args:
        name: Identifier used as the subagent_type value in task()
            dispatch. Must be a valid Python identifier (letters,
            digits, underscores).
        description: Role description shown in the task() tool
            description so the model knows when to delegate to
            this subagent.
        prompt: System prompt for the subagent's react() loop. For
            built-in subagents (research, plan, general), this is
            assembled by the factory from its default prompt plus
            any user-provided instructions.
        tools: Tools available to this subagent. None means "use
            defaults" (built-in factories set their own defaults;
            task() resolves at dispatch time).
        extra_tools: Additional tools merged with the subagent's
            default tools. Use this to extend a built-in subagent
            without replacing its default tool set.
        model: Model override for this subagent. None inherits the
            parent agent's model.
        fork: Dispatch mode. False (default) runs the subagent with
            isolated context (only the summary returns). True runs
            with forked context (inherits the parent's full message
            history). Use the same model or model family as the
            parent when forking to preserve the prompt cache and
            avoid errors from incompatible tool call formats or
            reasoning content.
        skills: Skills available to this subagent. None means no
            skills (general() overrides this to inherit parent
            skills).
        memory: Memory tool access level. "readwrite" gives full
            memory access, "readonly" exposes only read/search
            operations, False disables memory entirely. Overridden
            to False when the parent deepagent sets memory=False.
        limits: Scoped limits applied to each invocation of this
            subagent (e.g. token_limit, message_limit, time_limit,
            cost_limit).
        compaction: Compaction strategy for context management. None
            inherits the parent agent's compaction strategy.

    Returns:
        A Subagent configuration object.
    """
    if not name or not name.isidentifier():
        raise ValueError(
            f"Subagent name must be a valid Python identifier, got {name!r}"
        )
    if not description:
        raise ValueError("Subagent description must not be empty.")
    if not prompt:
        raise ValueError("Subagent prompt must not be empty.")
    if memory is True or memory not in ("readwrite", "readonly", False):
        raise ValueError(
            f"Subagent memory must be 'readwrite', 'readonly', or False, got {memory!r}"
        )

    return Subagent(
        name=name,
        description=description,
        prompt=prompt,
        tools=list(tools) if tools is not None else None,
        extra_tools=list(extra_tools) if extra_tools is not None else None,
        model=model,
        fork=fork,
        skills=skills,
        memory=memory,
        limits=limits,
        compaction=compaction,
    )
