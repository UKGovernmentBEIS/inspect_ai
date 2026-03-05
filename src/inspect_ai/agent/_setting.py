from __future__ import annotations

from typing import Awaitable, Callable, NamedTuple

from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_def import ToolDef

OnTurn = Callable[[], Awaitable[bool | str | None]]
"""Callback to be called each iteration of the agent loop.

Return values indicate what should happen next:
    `False` — stop the agent.
    `str` — inject a user message and continue.
    `None` or `True` — continue normally.
"""


class Workspace(NamedTuple):
    """A sandbox environment the agent should have access to."""

    name: str = "default"
    """Workspace name (matches docker-compose service name)."""

    description: str = ""
    """Human-readable description of this workspace for the agent."""

    user: str | None = None
    """User to run commands as in this sandbox."""


class Setting(NamedTuple):
    """Execution setting declared by the task.

    Describes workspaces, tools, and per-turn callbacks that the task
    requests from agent scaffolding.
    """

    workspaces: tuple[Workspace, ...] = ()
    """Sandboxes the agent should have access to. First is primary.
    Sandboxes not listed should be hidden from the agent."""

    tools: tuple[Tool | ToolDef, ...] = ()
    """Task-specific tools."""

    on_turn: OnTurn | None = None
    """Callback to be called each iteration of the agent loop."""


def setting() -> Setting | None:
    """Get the Setting for the current sample, if any."""
    from inspect_ai.solver._task_state import sample_state

    state = sample_state()
    if state is None:
        return None
    return state._setting
