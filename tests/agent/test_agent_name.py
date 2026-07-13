"""Tests for the separation of an agent's registry identity from its display name.

Invariant: `RegistryInfo.name` is always the registry lookup name.

- A decorator `@agent(name="X")` overrides the registry name (traditional).
- `agent_with(name="Y")` never overrides the registry name; `Y` is a display name
  only (used for transcript spans, handoff prose, and handoff/as_tool tool names)
  and must not leak into the replayable `eval.solver`.
"""

from typing import cast

from inspect_ai._eval.loader import as_solver_spec, solver_from_spec
from inspect_ai._util.registry import (
    create_registry_object,
    registry_create,
    registry_create_from_dict,
    registry_unqualified_name,
)
from inspect_ai.agent import Agent, AgentState, agent, agent_with, handoff, react
from inspect_ai.agent._agent import agent_display_name
from inspect_ai.agent._as_solver import as_solver
from inspect_ai.agent._as_tool import sanitize_tool_name
from inspect_ai.tool._tool_description import tool_description


@agent
def display_named_agent(
    name: str = "Display Name", description: str = "An agent"
) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        return state

    return agent_with(execute, name=name, description=description)


@agent(name="Decorator Name", description="A decorator-named agent")
def decorator_named_agent() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        return state

    return execute


@agent
def plain_agent() -> Agent:
    """A plain agent."""

    async def execute(state: AgentState) -> AgentState:
        return state

    return execute


def test_agent_with_name_does_not_override_registry_identity() -> None:
    inst = display_named_agent()
    # RegistryInfo.name is the factory identity, not the agent_with display name
    assert registry_unqualified_name(inst) == "display_named_agent"
    # the display name lives separately
    assert agent_display_name(inst) == "Display Name"


def test_agent_with_solver_spec_uses_factory_identity() -> None:
    inst = display_named_agent()
    spec = as_solver_spec(as_solver(inst))
    assert spec.solver == "display_named_agent"
    # and the reference round-trips through the registry
    assert registry_create("agent", spec.solver) is not None


def test_decorator_name_overrides_registry_identity() -> None:
    # rule (1): @agent(name=...) DOES set the registry identity
    inst = decorator_named_agent()
    assert registry_unqualified_name(inst) == "Decorator Name"
    assert agent_display_name(inst) == "Decorator Name"
    assert as_solver_spec(as_solver(inst)).solver == "Decorator Name"


def test_handoff_tool_name_uses_sanitized_display_name() -> None:
    assert (
        tool_description(handoff(display_named_agent())).name
        == "transfer_to_display_name"
    )


def test_plain_agent_handoff_name_unchanged() -> None:
    tool = handoff(plain_agent(), description="A plain agent")
    assert tool_description(tool).name == "transfer_to_plain_agent"


def test_react_rename_keeps_factory_identity_and_drives_handoff() -> None:
    r = react(name="My Researcher", description="A researcher", prompt="x")
    # display name is the visible / handoff name ...
    assert agent_display_name(r) == "My Researcher"
    assert tool_description(handoff(r)).name == "transfer_to_my_researcher"
    # ... but replay references the react factory, with the rename carried in args
    spec = as_solver_spec(as_solver(r))
    assert spec.solver == "inspect_ai/react"
    assert spec.args.get("name") == "My Researcher"


def test_react_rename_round_trips_through_solver_from_spec() -> None:
    # an agent factory with its own `name` parameter must be re-creatable from
    # its recorded spec (the registry_create() positional-`name` collision).
    r = react(name="My Researcher", description="A researcher", prompt="x")
    spec = as_solver_spec(as_solver(r))
    assert solver_from_spec(spec) is not None


def test_replay_preserves_display_name() -> None:
    # re-creating an agent from its recorded spec must keep the display name
    # (the @agent wrapper's metadata is preserved through create_registry_object).
    r = react(name="My Researcher", description="A researcher", prompt="x")
    spec = as_solver_spec(as_solver(r))
    recreated = cast(
        Agent, create_registry_object("agent", spec.solver, spec.args_passed)
    )
    assert agent_display_name(recreated) == "My Researcher"


def test_registry_create_from_dict_with_name_param() -> None:
    # registry_create_from_dict must not collide when params include `name`.
    obj = cast(
        Agent,
        registry_create_from_dict(
            {
                "type": "agent",
                "name": "inspect_ai/react",
                "params": {"name": "X", "prompt": "p"},
            }
        ),
    )
    assert agent_display_name(obj) == "X"


@agent
def emoji_named_agent() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        return state

    return agent_with(execute, name="🤖", description="An agent")


def test_handoff_tool_name_falls_back_when_display_name_unsanitizable() -> None:
    # a display name with no usable characters falls back to the registry name
    assert (
        tool_description(handoff(emoji_named_agent())).name
        == "transfer_to_emoji_named_agent"
    )


def test_agent_with_on_registered_agent_preserves_identity() -> None:
    renamed = agent_with(display_named_agent(), name="Renamed Agent")
    # identity preserved; only the display name changes
    assert registry_unqualified_name(renamed) == "display_named_agent"
    assert agent_display_name(renamed) == "Renamed Agent"
    assert as_solver_spec(as_solver(renamed)).solver == "display_named_agent"
    assert tool_description(handoff(renamed)).name == "transfer_to_renamed_agent"


def test_sanitize_tool_name() -> None:
    assert sanitize_tool_name("Claude Code") == "claude_code"
    assert sanitize_tool_name("  My  Agent  ") == "my_agent"
    assert sanitize_tool_name("Agent#1!") == "agent1"
    assert sanitize_tool_name("already_ok-name") == "already_ok-name"
