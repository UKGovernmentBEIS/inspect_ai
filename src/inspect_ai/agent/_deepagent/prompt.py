"""System prompt assembly for deepagent().

Composes layered system prompts from string constants and dynamic
content (subagent list, memory/plan configuration, user instructions).
"""

from .subagent import Subagent

CORE_BEHAVIOR = """
Complete tasks autonomously using your available tools. Act rather than
narrate intent — don't say what you plan to do, just do it.

Keep going until the task is fully resolved. Don't stop at the first
attempt if it doesn't work — diagnose what went wrong and try a
different approach. If a tool call fails or returns unexpected results,
consider why it failed before retrying. If you find yourself repeating
the same action without progress, stop and reassess your approach.

Be concise and direct. Avoid preamble, unnecessary explanation, and
restating what you've already done. When you need information, use
your tools rather than making assumptions.

When multiple independent tool calls are needed, batch them in a single
response rather than making sequential round-trips.

Plan when the task is complex or multi-step. Break large tasks into
smaller pieces and track your progress. Verify your work before
finishing — check against the original requirements, not against your
own output. Confirm the task is actually solved, not just that your
steps ran without errors.

Use reasonable defaults rather than asking clarifying questions for
every detail. Only ask when genuinely blocked or when the task is
fundamentally ambiguous.
""".strip()

MEMORY_INSTRUCTIONS = """
Check your memory at the start of your work to recover any earlier
progress or context. Use the memory tool to persist important
intermediate results, findings, and status as you go. This protects
against context window limits and ensures progress is not lost. Record
key findings rather than trying to remember everything. Update or
remove stale entries to keep memory organized.

Use the todo_write tool to track high-level task decomposition. Mark steps
in progress as you start them and completed as you finish. If your
understanding changes mid-task, update the plan before continuing.
Only commit to work you will actually do — label anything else as
optional next steps and exclude it from the plan. Before finishing,
reconcile every TODO item: mark each as completed, no longer relevant,
or blocked (with a reason). Do not finish with in_progress or pending
items.
""".strip()

MEMORY_ONLY_INSTRUCTIONS = """
Check your memory at the start of your work to recover any earlier
progress or context. Use the memory tool to persist important
intermediate results, findings, and status as you go. This protects
against context window limits and ensures progress is not lost. Record
key findings rather than trying to remember everything. Update or
remove stale entries to keep memory organized.
""".strip()

PLAN_ONLY_INSTRUCTIONS = """
Use the todo_write tool to track high-level task decomposition. Mark steps
in progress as you start them and completed as you finish. If your
understanding changes mid-task, update the plan before continuing.
Only commit to work you will actually do — label anything else as
optional next steps and exclude it from the plan. Before finishing,
reconcile every TODO item: mark each as completed, no longer relevant,
or blocked (with a reason). Do not finish with in_progress or pending
items.
""".strip()


def build_subagent_dispatch(subagents: list[Subagent]) -> str:
    """Generate system prompt section describing available subagents.

    Args:
        subagents: List of configured subagents.

    Returns:
        Prompt text listing subagents and delegation guidance.
    """
    lines = [
        "You can delegate work to specialized subagents using the task tool.",
        "",
        "Available subagents:",
    ]
    for sa in subagents:
        lines.append(f"- **{sa.name}**: {sa.description}")
    lines.append("")
    lines.append(
        "Delegate when the work is complex, independent, or would benefit "
        "from an isolated context. Do the work directly when it's a simple "
        "lookup, a single tool call, or when the result depends on your "
        "current conversation state."
    )
    lines.append("")
    has_forked = any(sa.fork for sa in subagents)
    if has_forked:
        lines.append(
            "When delegating to non-forked subagents, include all necessary "
            "context in the prompt — they cannot see your conversation "
            "history. Forked subagents already have your full conversation "
            "context. Be specific about what information you need back."
        )
    else:
        lines.append(
            "When delegating, include all necessary context in the prompt — "
            "the subagent cannot see your conversation history. Be specific "
            "about what information you need back."
        )
    return "\n".join(lines)


def build_system_prompt(
    *,
    subagents: list[Subagent] | None = None,
    memory: bool = True,
    todo_write: bool = True,
    instructions: str | None = None,
) -> str:
    """Assemble the deepagent system prompt from layers.

    Args:
        subagents: Configured subagents (omit section if None or empty).
        memory: Whether the memory tool is enabled.
        todo_write: Whether the todo_write tool is enabled.
        instructions: User-provided instructions appended at the end.

    Returns:
        Assembled system prompt string.
    """
    sections: list[str] = [CORE_BEHAVIOR]

    if subagents:
        sections.append(build_subagent_dispatch(subagents))

    if memory and todo_write:
        sections.append(MEMORY_INSTRUCTIONS)
    elif memory:
        sections.append(MEMORY_ONLY_INSTRUCTIONS)
    elif todo_write:
        sections.append(PLAN_ONLY_INSTRUCTIONS)

    if instructions:
        sections.append(instructions)

    return "\n\n".join(sections)


def expand_prompt_placeholders(
    prompt: str,
    *,
    subagents: list[Subagent] | None = None,
    memory: bool = True,
    todo_write: bool = True,
    instructions: str | None = None,
) -> str:
    """Expand named placeholders in a custom prompt.

    Supports the following placeholders (all optional — if a placeholder
    is not present in the template, that content is simply not included):

    - ``{core_behavior}`` — core behavioral expectations
    - ``{subagent_dispatch}`` — subagent names, roles, delegation guidance
    - ``{memory_instructions}`` — memory/plan coordination guidance
    - ``{instructions}`` — user-provided instructions

    Args:
        prompt: Custom prompt template with optional placeholders.
        subagents: Configured subagents.
        memory: Whether the memory tool is enabled.
        todo_write: Whether the todo_write tool is enabled.
        instructions: User-provided instructions.

    Returns:
        Prompt with placeholders expanded.
    """
    result = prompt
    result = result.replace("{core_behavior}", CORE_BEHAVIOR)

    if subagents:
        result = result.replace(
            "{subagent_dispatch}", build_subagent_dispatch(subagents)
        )
    else:
        result = result.replace("{subagent_dispatch}", "")

    if memory and todo_write:
        result = result.replace("{memory_instructions}", MEMORY_INSTRUCTIONS)
    elif memory:
        result = result.replace("{memory_instructions}", MEMORY_ONLY_INSTRUCTIONS)
    elif todo_write:
        result = result.replace("{memory_instructions}", PLAN_ONLY_INSTRUCTIONS)
    else:
        result = result.replace("{memory_instructions}", "")

    result = result.replace("{instructions}", instructions or "")

    return result
