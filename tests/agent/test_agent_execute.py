from typing import Callable, TypeAlias

import pytest
from test_helpers.limits import check_limit_event

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai.agent import Agent, AgentState, agent, as_solver, as_tool
from inspect_ai.agent._handoff import handoff
from inspect_ai.agent._run import run
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool
from inspect_ai.model._model import get_model
from inspect_ai.solver._solver import Generate, Solver, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.solver._use_tools import use_tools
from inspect_ai.tool import ToolDef
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.util._limit import LimitExceededError, message_limit


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


@agent
def looping_agent() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        """An agent which forever calls generate and appends messages.

        Args:
            state: Input state (conversation)
        """
        while True:
            result = await get_model("mockllm/model").generate(state.messages)
            state.messages.append(result.message)
        return state

    return execute


@solver
def call_looping_agent(
    function_name: str = "looping_agent", arguments: dict = {"input": "input"}
) -> Solver:
    """A solver which makes a tool call to looping_agent."""

    async def solve(state: TaskState, generate: Generate):
        state.messages.append(
            ChatMessageAssistant(
                content="Call tool",
                tool_calls=[
                    ToolCall(id="1", function=function_name, arguments=arguments)
                ],
            )
        )
        tool_result = await execute_tools(state.messages, state.tools)
        state.messages.extend(tool_result.messages)
        return state

    return solve


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


def test_agent_as_tool_respects_limits() -> None:
    agent_tool = as_tool(looping_agent(), limits=[message_limit(10)])

    log = eval(
        Task(
            solver=[
                use_tools(agent_tool),
                call_looping_agent(),
            ]
        )
    )[0]

    assert log.status == "success"
    assert log.samples
    tool_message = log.samples[0].messages[-1]
    assert isinstance(tool_message, ChatMessageTool)
    assert tool_message.error is not None
    assert "The tool exceeded its message limit of 10." in tool_message.error.message
    check_limit_event(log, "message")


def test_agent_as_tool_respects_sample_limits() -> None:
    agent_tool = as_tool(looping_agent())

    log = eval(
        Task(
            solver=[
                use_tools(agent_tool),
                call_looping_agent(),
            ],
            message_limit=10,
        )
    )[0]

    assert log.status == "success"
    assert log.samples
    tool_message = log.samples[0].messages[-1]
    assert isinstance(tool_message, ChatMessageTool)
    assert tool_message.error is not None
    assert tool_message.error.message == "The tool exceeded its message limit of 10."
    check_limit_event(log, "message")


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


def test_agent_handoff_respects_limits():
    agent_tool = handoff(looping_agent(), limits=[message_limit(10)])

    log = eval(
        Task(
            solver=[
                use_tools(agent_tool),
                call_looping_agent("transfer_to_looping_agent", arguments={}),
            ]
        )
    )[0]

    assert log.status == "success"
    assert log.samples
    assert (
        log.samples[0].messages[-1].content
        == "The looping_agent exceeded its message limit of 10."
    )
    check_limit_event(log, "message")


def test_agent_handoff_respects_sample_limits():
    agent_tool = handoff(looping_agent())

    log = eval(
        Task(
            solver=[
                use_tools(agent_tool),
                call_looping_agent("transfer_to_looping_agent", arguments={}),
            ],
            message_limit=10,
        )
    )[0]

    assert log.status == "success"
    check_limit_event(log, "message")


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


def test_agent_as_solver_respects_limits() -> None:
    agent_solver = as_solver(looping_agent(), limits=[message_limit(10)])

    log = eval(Task(solver=agent_solver))[0]

    assert log.status == "success"
    assert log.samples
    assert len(log.samples[0].messages) == 10
    check_limit_event(log, "message")


def test_agent_as_solver_respects_sample_limits() -> None:
    agent_solver = as_solver(looping_agent())

    log = eval(
        Task(
            solver=agent_solver,
            message_limit=10,
        )
    )[0]

    assert log.status == "success"
    assert log.samples
    assert len(log.samples[0].messages) == 10
    check_limit_event(log, "message")


@pytest.mark.anyio
async def test_agent_run():
    state = await run(web_surfer(), "This is the input", max_searches=22)
    assert state.output.completion == "22"


async def test_agent_run_respects_limits() -> None:
    with pytest.raises(LimitExceededError):
        await run(looping_agent(), "This is the input", limits=[message_limit(10)])
