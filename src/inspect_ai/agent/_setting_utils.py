from __future__ import annotations

from collections.abc import Sequence
from typing import Callable, Literal

from inspect_ai.tool._tool import Tool, ToolSource
from inspect_ai.tool._tool_def import ToolDef

from ._setting import Workspace
from ._setting import setting as get_setting

WorkspaceToolFactory = Callable[[Workspace, int], Sequence[Tool | ToolDef]]
"""Creates tools for a workspace.

Args:
    workspace: The workspace to create tools for.
    index: Position in the workspaces tuple (0 = primary).

Returns:
    Tools to provide the agent for this workspace.
"""


def tools_from_setting(
    solver_tools: list[Tool | ToolDef | ToolSource],
    workspace_tools: WorkspaceToolFactory,
    framework_tools: set[str] | None = None,
) -> list[Tool | ToolDef | ToolSource]:
    """Create tools from the current Setting and merge with solver tools.

    When no Setting exists, solver_tools are returned unchanged.

    When a Setting exists, the Setting describes the tool surface:
    - Calls ``workspace_tools`` for each workspace to create tools
    - Prepends Setting.tools
    - Drops solver tools unless they are in ``framework_tools``
    - ToolSource items always pass through (names not known statically)

    Args:
        solver_tools: Tools provided by the solver/scaffolding.
        workspace_tools: Factory that creates tools for each workspace.
        framework_tools: Names of scaffolding tools (e.g. submit) that should
            survive even when a Setting describes the tool surface.

    Returns:
        Merged tool list: setting tools + workspace tools + surviving solver tools.
    """
    s = get_setting()
    if s is None:
        return solver_tools

    # collect setting tools + workspace tools
    setting_tools: list[Tool | ToolDef] = list(s.tools)

    for i, ws in enumerate(s.workspaces):
        setting_tools.extend(workspace_tools(ws, i))

    # build a set of setting tool names
    setting_tool_names: set[str] = set()
    for st in setting_tools:
        setting_tool_names.add(
            ToolDef(st).name if not isinstance(st, ToolDef) else st.name
        )

    # Setting describes the tool surface: only keep solver tools that are
    # ToolSources (can't filter statically) or framework tools not already
    # provided by the setting.
    keep = framework_tools or set()
    filtered: list[Tool | ToolDef | ToolSource] = []
    for solver_tool in solver_tools:
        if isinstance(solver_tool, ToolSource):
            filtered.append(solver_tool)
        else:
            name = (
                ToolDef(solver_tool).name
                if not isinstance(solver_tool, ToolDef)
                else solver_tool.name
            )
            if name in keep and name not in setting_tool_names:
                filtered.append(solver_tool)

    return list(setting_tools) + filtered


class OnTurnResult:
    """Result of calling handle_on_turn."""

    __slots__ = ("action", "message")

    def __init__(
        self,
        action: Literal["break", "continue", "proceed"],
        message: str | None = None,
    ) -> None:
        self.action: Literal["break", "continue", "proceed"] = action
        self.message: str | None = message


async def handle_on_turn() -> OnTurnResult:
    """Call the Setting on_turn callback and return the action to take.

    Reads the Setting from the current sample. If on_turn is present,
    calls it and interprets the result:
    - False: sets state.completed = True, returns action="break"
    - str: returns action="continue" with the message (caller should append
      it to its own message list and skip on_continue)
    - None/True: returns action="proceed"

    Note: This function sets state.completed on "break" but does NOT inject
    messages. The caller must append result.message to its own state to avoid
    AgentState/TaskState message list divergence.

    Returns:
        OnTurnResult with action and optional message.
    """
    from inspect_ai.solver._task_state import sample_state

    s = get_setting()
    if s is None or s.on_turn is None:
        return OnTurnResult("proceed")

    result = await s.on_turn()

    if result is False:
        state = sample_state()
        if state is not None:
            state.completed = True
        return OnTurnResult("break")
    elif isinstance(result, str):
        return OnTurnResult("continue", message=result)
    else:
        return OnTurnResult("proceed")
