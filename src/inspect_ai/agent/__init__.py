from typing import TYPE_CHECKING

from inspect_ai._util.lazy import lazy_attributes

# eager: core types and lightweight helpers that only reach into
# ``model`` / ``tool`` / ``util`` (and ``scorer._metric``); none of these
# pull ``log`` or ``event`` at import time.
from ._agent import Agent, AgentState, agent, agent_with, is_agent
from ._as_solver import as_solver
from ._as_tool import as_tool
from ._filter import MessageFilter, content_only, last_message, remove_tools
from ._handoff import handoff
from ._run import run
from ._types import (
    AgentAttempts,
    AgentContinue,
    AgentPrompt,
    AgentSubmit,
)

if TYPE_CHECKING:
    # lazy: built-in agents and the bridge machinery (the latter imports
    # ``inspect_ai.log._samples`` at module level, which is the historic
    # source of the agent <-> log import cycle).
    from inspect_ai.tool._mcp._tools_bridge import BridgedToolsSpec

    from ._bridge.bridge import agent_bridge, bridge
    from ._bridge.sandbox.bridge import sandbox_agent_bridge
    from ._bridge.sandbox.types import SandboxAgentBridge
    from ._bridge.types import AgentBridge
    from ._deepagent.deepagent import deepagent
    from ._deepagent.general import general
    from ._deepagent.plan import plan
    from ._deepagent.research import research
    from ._deepagent.subagent import Subagent, subagent
    from ._human.agent import human_cli
    from ._react import react

__all__ = [
    "react",
    "bridge",
    "human_cli",
    "run",
    "handoff",
    "as_tool",
    "as_solver",
    "agent_bridge",
    "sandbox_agent_bridge",
    "AgentBridge",
    "SandboxAgentBridge",
    "BridgedToolsSpec",
    "content_only",
    "last_message",
    "remove_tools",
    "MessageFilter",
    "Agent",
    "AgentState",
    "agent",
    "agent_with",
    "is_agent",
    "AgentPrompt",
    "AgentAttempts",
    "AgentContinue",
    "AgentSubmit",
    "Subagent",
    "deepagent",
    "subagent",
    "research",
    "plan",
    "general",
]

lazy_attributes(
    __name__,
    {
        "react": "inspect_ai.agent._react",
        "agent_bridge": "inspect_ai.agent._bridge.bridge",
        "bridge": "inspect_ai.agent._bridge.bridge",
        "sandbox_agent_bridge": "inspect_ai.agent._bridge.sandbox.bridge",
        "SandboxAgentBridge": "inspect_ai.agent._bridge.sandbox.types",
        "AgentBridge": "inspect_ai.agent._bridge.types",
        "human_cli": "inspect_ai.agent._human.agent",
        "Subagent": "inspect_ai.agent._deepagent",
        "deepagent": "inspect_ai.agent._deepagent",
        "general": "inspect_ai.agent._deepagent",
        "plan": "inspect_ai.agent._deepagent",
        "research": "inspect_ai.agent._deepagent",
        "subagent": "inspect_ai.agent._deepagent",
        "BridgedToolsSpec": "inspect_ai.tool._mcp._tools_bridge",
    },
)
