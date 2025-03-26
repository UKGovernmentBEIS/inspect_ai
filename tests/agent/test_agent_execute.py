from typing import Callable, TypeAlias

import pytest

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai.agent import Agent, AgentState, agent, as_solver, as_tool
from inspect_ai.agent._handoff import handoff
from inspect_ai.agent._run import run
from inspect_ai.solver._solver import Solver
from inspect_ai.tool import ToolDef
from inspect_ai.tool._tool import Tool


@agent
def web_surfer() -> Agent:
    async def execute(state: AgentState, max_searches: int = 5) -> AgentState:
        """Web surfer for conducting web research into a topic.

        Args:
            state: Input state (conversation)
            max_searches: Maximum number of web searches to conduct

        Returns:
            Ouput state (additions to conversation)
        """
        state.output.completion = str(max_searches)
        return state

    return execute


@agent
def web_surfer_no_default() -> Agent:
    async def execute(state: AgentState, max_searches: int) -> AgentState:
        """Web surfer for conducting web research into a topic.

        Args:
            state: Input state (conversation)
            max_searches: Maximum number of web searches to conduct

        Returns:
            Ouput state (additions to conversation)
        """
        state.output.completion = str(max_searches)
        return state

    return execute


@agent
def web_surfer_no_docs() -> Agent:
    async def execute(state: AgentState, max_searches: int = 3) -> AgentState:
        return state

    return execute


@agent
def web_surfer_no_param_docs() -> Agent:
    async def execute(state: AgentState, max_searches: int = 3) -> AgentState:  # noqa: D417
        """Web surfer for conducting web research into a topic.

        Args:
            state: Input state (conversation)

        Returns:
            Ouput state (additions to conversation)
        """
        return state

    return execute


ToolConverter: TypeAlias = Callable[..., Tool]


def check_agent_as_tool(
    converter: ToolConverter,
    tool_name: str = "web_surfer",
    input_param: str | None = "input",
):
    tool = converter(web_surfer())
    tool_def = ToolDef(tool)
    assert tool_def.name == tool_name
    assert (
        tool_def.description == "Web surfer for conducting web research into a topic."
    )
    num_params = 1
    if input_param is not None:
        assert input_param in tool_def.parameters.properties
        num_params += 1
    assert len(tool_def.parameters.properties) == num_params
    assert "max_searches" in tool_def.parameters.properties


def check_agent_as_tool_curry(
    converter: ToolConverter,
    tool_name: str = "web_surfer",
    input_param: str | None = "input",
):
    tool = converter(web_surfer(), max_searches=3)
    tool_def = ToolDef(tool)
    assert tool_def.name == tool_name
    assert (
        tool_def.description == "Web surfer for conducting web research into a topic."
    )
    num_params = 0
    if input_param is not None:
        assert input_param in tool_def.parameters.properties
        num_params += 1
    assert len(tool_def.parameters.properties) == num_params
    assert "max_searches" not in tool_def.parameters.properties


def check_agent_as_tool_curry_invalid_param(converter: ToolConverter):
    with pytest.raises(ValueError, match="does not have a"):
        converter(web_surfer(), foo=3)


def check_agent_as_tool_no_docs_error(converter: ToolConverter):
    with pytest.raises(ValueError, match="Description not provided"):
        converter(web_surfer_no_docs())


def check_agent_as_tool_no_param_docs_error(converter: ToolConverter):
    with pytest.raises(ValueError, match="provided for parameter"):
        converter(web_surfer_no_param_docs())


def test_agent_as_tool():
    check_agent_as_tool(as_tool)


def test_agent_as_tool_curry():
    check_agent_as_tool_curry(as_tool)


def test_agent_as_tool_curry_invalid_param():
    check_agent_as_tool_curry_invalid_param(as_tool)


def test_agent_as_tool_no_docs_error():
    check_agent_as_tool_no_docs_error(as_tool)


def test_agent_as_tool_no_param_docs_error():
    check_agent_as_tool_no_docs_error(as_tool)


def test_agent_handoff():
    check_agent_as_tool(handoff, tool_name="transfer_to_web_surfer", input_param=None)


def test_agent_handoff_curry():
    check_agent_as_tool_curry(
        handoff, tool_name="transfer_to_web_surfer", input_param=None
    )


def test_agent_handoff_curry_invalid_param():
    check_agent_as_tool_curry_invalid_param(handoff)


def test_agent_handoff_no_docs_error():
    check_agent_as_tool_no_docs_error(handoff)


def test_agent_handoff_no_param_docs_error():
    check_agent_as_tool_no_docs_error(handoff)


def check_agent_as_solver(agent_solver: Solver):
    log = eval(Task(solver=agent_solver))[0]
    assert log.samples
    assert log.samples[0].output.completion == "5"


def test_agent_as_solver():
    agent_solver = as_solver(web_surfer())
    check_agent_as_solver(agent_solver)


def test_agent_as_solver_with_param():
    agent_solver = as_solver(web_surfer_no_default(), max_searches=5)
    check_agent_as_solver(agent_solver)


def test_agent_as_solver_no_param():
    with pytest.raises(ValueError, match="as a solver"):
        agent_solver = as_solver(web_surfer_no_default())
        eval(Task(solver=agent_solver))[0]


@pytest.mark.anyio
async def test_agent_run():
    state = await run(web_surfer(), "This is the input", max_searches=22)
    assert state.output.completion == "22"
