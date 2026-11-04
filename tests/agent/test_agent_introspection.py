# the wrapper @agent puts around an agent must keep it introspectable when its
# module defers annotations
from __future__ import annotations

from typing import get_type_hints

from inspect_ai.agent import Agent, AgentState, agent, agent_with, as_tool, handoff
from inspect_ai.tool import Tool
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import parse_tool_info


@agent
def policy() -> Agent:
    async def execute(state: AgentState, tools: list[Tool]) -> AgentState:
        """Generate a reply.

        Args:
            state: The conversation.
            tools: Tools to offer the model.
        """
        return state

    return execute


@agent(description="Adds things.")
def adder(scale: int = 2) -> Agent:
    async def execute(state: AgentState, count: int, label: str = "x") -> AgentState:
        """Add up.

        Args:
            state: The conversation.
            count: How many to add.
            label: A label.
        """
        return state

    return execute


def test_a_model_agent_keeps_its_tools_parameter() -> None:
    info = parse_tool_info(policy())
    assert list(info.parameters.properties) == ["state", "tools"]
    assert (
        info.parameters.properties["tools"].description == "Tools to offer the model."
    )
    assert get_type_hints(policy())["tools"] == list[Tool]


def test_tool_names_and_parameters_come_from_the_agent() -> None:
    as_a_tool = ToolDef(as_tool(adder()))
    assert as_a_tool.name == "adder"
    assert as_a_tool.description == "Adds things."
    assert list(as_a_tool.parameters.properties) == ["input", "count", "label"]
    assert as_a_tool.parameters.properties["count"].description == "How many to add."

    to_hand_off = ToolDef(handoff(adder()))
    assert to_hand_off.name == "transfer_to_adder"
    assert list(to_hand_off.parameters.properties) == ["count", "label"]


def test_agent_with_renames_the_wrapped_agent() -> None:
    renamed = agent_with(adder(), name="Renamed", description="Renamed adder.")
    assert ToolDef(as_tool(renamed)).name == "renamed"
    assert ToolDef(as_tool(renamed)).description == "Renamed adder."
    assert ToolDef(handoff(renamed)).name == "transfer_to_renamed"
