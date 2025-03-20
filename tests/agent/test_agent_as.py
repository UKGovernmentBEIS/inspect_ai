import pytest

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai.agent import Agent, AgentState, agent, as_tool
from inspect_ai.solver._as_solver import as_solver
from inspect_ai.solver._solver import Solver
from inspect_ai.tool import ToolDef


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


def test_agent_as_tool():
    tool = as_tool(web_surfer())
    tool_def = ToolDef(tool)
    assert tool_def.name == "web_surfer"
    assert (
        tool_def.description == "Web surfer for conducting web research into a topic."
    )
    assert len(tool_def.parameters.properties) == 2
    assert "input" in tool_def.parameters.properties
    assert "max_searches" in tool_def.parameters.properties


def test_agent_as_tool_no_docs_error():
    with pytest.raises(ValueError, match="Description not provided"):
        as_tool(web_surfer_no_docs())


def test_agent_as_tool_no_param_docs_error():
    with pytest.raises(ValueError, match="provided for parameter"):
        as_tool(web_surfer_no_param_docs())


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
