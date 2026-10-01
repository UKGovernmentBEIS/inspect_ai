from typing import Callable, TypeAlias

import anyio
import pytest
from test_helpers.limits import check_limit_event, exceed_token_limit_in_child_task

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai._util.registry import registry_create
from inspect_ai.agent import Agent, AgentState, agent, as_solver, as_tool
from inspect_ai.agent._handoff import handoff
from inspect_ai.agent._run import run
from inspect_ai.event._span import SpanBeginEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import transcript
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.solver._solver import Generate, Solver, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.solver._use_tools import use_tools
from inspect_ai.tool import ToolDef, tool
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.util._limit import (
    LimitExceededError,
    check_token_limit,
    message_limit,
    record_model_usage,
    token_limit,
)


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
    model_output = ModelOutput.from_content("mockllm/model", "hello")
    model_output.usage = ModelUsage(total_tokens=1)

    async def execute(state: AgentState) -> AgentState:
        """An agent which forever calls generate and appends messages.

        Args:
            state: Input state (conversation)
        """
        while True:
            result = await get_model(
                "mockllm/model", custom_outputs=[model_output]
            ).generate(state.messages)
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


def test_agent_as_tool_result_not_truncated():
    # the agent's report is the payload the caller asked for, so it is exempt
    # from max_tool_output (0 disables truncation)
    assert ToolDef(as_tool(web_surfer())).max_output == 0


def test_agent_as_tool_max_output_overridable():
    # callers who do want a cap can ask for one
    assert ToolDef(as_tool(web_surfer(), max_output=2048)).max_output == 2048
    assert ToolDef(as_tool(web_surfer(), max_output=None)).max_output is None


def test_agent_as_tool_curry():
    check_agent_as_tool_curry(as_tool)


def test_agent_as_tool_curry_invalid_param():
    check_agent_as_tool_curry_invalid_param(as_tool)


def test_agent_as_tool_no_docs_error():
    check_agent_as_tool_no_docs_error(as_tool)


def test_agent_as_tool_no_param_docs_error():
    check_agent_as_tool_no_param_docs_error(as_tool)


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

    # the sample's limit ends the sample rather than failing the tool call
    assert log.status == "success"
    assert log.samples
    sample = log.samples[0]
    assert sample.limit is not None
    assert sample.limit.type == "message"
    assert not any(isinstance(m, ChatMessageTool) for m in sample.messages)
    check_limit_event(log, "message")


@tool
def generating_tool(limit: int | None = None) -> Tool:
    async def execute() -> str:
        """Call the model until a limit stops it."""
        with token_limit(limit):
            await looping_agent()(AgentState(messages=[ChatMessageUser(content="hi")]))
        return "done"

    return execute


@solver
def mark_continued() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.messages.append(ChatMessageUser(content="continued"))
        return state

    return solve


def test_tool_model_call_sample_limit_ends_sample() -> None:
    log = eval(
        Task(
            solver=[
                use_tools(generating_tool()),
                call_looping_agent("generating_tool", arguments={}),
                mark_continued(),
            ],
            token_limit=5,
        )
    )[0]

    assert log.status == "success"
    assert log.samples
    sample = log.samples[0]
    assert sample.limit is not None
    assert sample.limit.type == "token"
    assert sample.limit.limit == 5
    assert sample.messages[-1].text != "continued"


@tool
def failing_and_limited_tool() -> Tool:
    async def execute() -> str:
        """Fail in one child task and exceed the sample's limit in another."""

        async def fail() -> None:
            raise RuntimeError("unrelated failure")

        async with anyio.create_task_group() as tg:
            tg.start_soon(fail)
            tg.start_soon(exceed_token_limit_in_child_task)
        return "done"

    return execute


def test_tool_grouped_sample_limit_with_other_error_ends_sample() -> None:
    log = eval(
        Task(
            solver=[
                use_tools(failing_and_limited_tool()),
                call_looping_agent("failing_and_limited_tool", arguments={}),
                mark_continued(),
            ],
            token_limit=5,
        )
    )[0]

    assert log.status == "success"
    assert log.samples
    sample = log.samples[0]
    assert sample.error is None
    assert sample.limit is not None
    assert sample.limit.type == "token"


@solver
def call_parallel_failing_and_limited_tools() -> Solver:
    """Run two parallel tools that fail together: one exceeds the sample's limit."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        arrived = 0
        both_arrived = anyio.Event()

        async def barrier() -> None:
            nonlocal arrived
            arrived += 1
            if arrived == 2:
                both_arrived.set()
            await both_arrived.wait()

        @tool(parallel=True)
        def limited() -> Tool:
            async def execute() -> str:
                """Exceed the sample's token limit."""
                await barrier()
                record_model_usage(ModelUsage(total_tokens=100))
                check_token_limit()
                return "done"

            return execute

        @tool(parallel=True)
        def failing() -> Tool:
            async def execute() -> str:
                """Fail with an unrelated error."""
                await barrier()
                raise RuntimeError("unrelated failure")

            return execute

        # alternate the order, since the first call is started first
        calls = [
            ToolCall(id="1", function="limited", arguments={}),
            ToolCall(id="2", function="failing", arguments={}),
        ]
        if state.epoch % 2 == 0:
            calls.reverse()
        state.messages.append(ChatMessageAssistant(content="", tool_calls=calls))
        result = await execute_tools(state.messages, [limited(), failing()])
        state.messages.extend(result.messages)
        state.messages.append(ChatMessageUser(content="continued"))
        return state

    return solve


def test_parallel_tool_sample_limit_wins_over_sibling_error() -> None:
    log = eval(
        Task(
            solver=call_parallel_failing_and_limited_tools(),
            token_limit=5,
            epochs=10,
        )
    )[0]

    assert log.status == "success"
    assert log.samples and len(log.samples) == 10
    for sample in log.samples:
        assert sample.error is None
        assert sample.limit is not None
        assert sample.limit.type == "token"
        assert sample.messages[-1].text != "continued"
        tool_events = [e for e in sample.events if isinstance(e, ToolEvent)]
        assert len(tool_events) == 2
        assert all(not e.pending for e in tool_events)


def test_tool_model_call_tool_limit_returns_tool_error() -> None:
    log = eval(
        Task(
            solver=[
                use_tools(generating_tool(limit=5)),
                call_looping_agent("generating_tool", arguments={}),
                mark_continued(),
            ],
            token_limit=1000,
        )
    )[0]

    assert log.status == "success"
    assert log.samples
    sample = log.samples[0]
    assert sample.limit is None
    tool_message = sample.messages[-2]
    assert isinstance(tool_message, ChatMessageTool)
    assert tool_message.error is not None
    assert tool_message.error.type == "limit"
    assert sample.messages[-1].text == "continued"


@pytest.mark.anyio
async def test_tool_model_call_agent_limit_ends_agent() -> None:
    @agent
    def tool_calling_agent() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            """Call generating_tool, then carry on.

            Args:
                state: Input state (conversation)
            """
            state.messages.append(
                ChatMessageAssistant(
                    content="",
                    tool_calls=[
                        ToolCall(id="1", function="generating_tool", arguments={})
                    ],
                )
            )
            result = await execute_tools(state.messages, [generating_tool()])
            state.messages.extend(result.messages)
            state.messages.append(ChatMessageUser(content="continued"))
            return state

        return execute

    agent_limit = token_limit(5)
    agent_state, limit_error = await run(
        tool_calling_agent(), "input", limits=[agent_limit]
    )

    # the agent's limit ends the agent, not just its tool call
    assert limit_error is not None
    assert limit_error.source is agent_limit
    assert agent_state.messages[-1].text != "continued"


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
    check_agent_as_tool_no_param_docs_error(handoff)


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


def test_agent_handoff_does_not_reuse_limits():
    agent_tool = handoff(looping_agent(), limits=[message_limit(10)])

    log = eval(
        Task(
            solver=[
                use_tools(agent_tool),
                call_looping_agent("transfer_to_looping_agent", arguments={}),
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
    assert log.samples
    sample = log.samples[0]
    assert sample.limit is not None
    assert sample.limit.type == "message"
    assert not any(
        m.text == "The looping_agent exceeded its message limit of 10."
        for m in sample.messages
    )
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
    assert any(
        isinstance(event, SpanBeginEvent) and event.name == "web_surfer"
        for event in transcript().events
    )


@pytest.mark.anyio
async def test_agent_run_with_name_param():
    await run(web_surfer(), "This is the input", name="my-agent", max_searches=22)

    assert any(
        isinstance(event, SpanBeginEvent) and event.name == "my-agent"
        for event in transcript().events
    )


@pytest.mark.anyio
async def test_agent_run_without_limits_param():
    result = await run(web_surfer(), "This is the input")

    # When no limits parameter is provided, only an AgentState is returned.
    assert isinstance(result, AgentState)


@pytest.mark.anyio
async def test_agent_run_with_limits_param_but_no_limit_hit() -> None:
    state, limit_error = await run(
        web_surfer(), "This is the input", limits=[token_limit(100)]
    )

    # When a limits parameter is provided, a tuple is returned.
    assert isinstance(state, AgentState)
    assert limit_error is None


@pytest.mark.anyio
async def test_agent_run_respects_limits() -> None:
    agent_state, limit_error = await run(
        looping_agent(), "This is the input", limits=[message_limit(10)]
    )

    assert limit_error is not None
    assert limit_error.type == "message"
    assert len(agent_state.messages) == 10


@pytest.mark.anyio
async def test_agent_run_parent_limit_hit() -> None:
    # run() should not catch another limit's error.
    with pytest.raises(LimitExceededError) as exc_info:
        with token_limit(10):
            await run(looping_agent(), "This is the input", limits=[token_limit(100)])

    assert exc_info.value.type == "token"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10


# Agent without -> Agent return type annotation (tests fix for registry_create)
@agent
def agent_no_return_type():
    async def execute(state: AgentState, value: int = 42) -> AgentState:
        """Agent without return type annotation.

        Args:
            state: Input state
            value: A test value

        Returns:
            Output state
        """
        state.output.completion = str(value)
        return state

    return execute


def test_agent_no_return_type_registry_create():
    """Test that agents without -> Agent annotation work with registry_create."""
    created_agent = registry_create("agent", "agent_no_return_type")
    # Should return an agent instance, not the factory function
    assert callable(created_agent)
    # The agent should be the inner execute function, not the factory
    assert hasattr(created_agent, "__registry_info__")


def test_agent_no_return_type_as_solver():
    """Test that agents without -> Agent annotation work with as_solver."""
    agent_solver = as_solver(agent_no_return_type())
    log = eval(Task(solver=agent_solver))[0]
    assert log.samples
    assert log.samples[0].output.completion == "42"


def test_agent_no_return_type_as_tool():
    """Test that agents without -> Agent annotation work with as_tool."""
    tool = as_tool(agent_no_return_type())
    tool_def = ToolDef(tool)
    assert tool_def.name == "agent_no_return_type"
    assert "value" in tool_def.parameters.properties


def test_handoff_react_respects_name():
    """Test that handoff uses react's name parameter for tool naming."""
    from inspect_ai.agent._react import react

    my_agent = react(
        name="custom_agent",
        description="A custom agent",
        tools=[],
    )

    tool = handoff(my_agent)
    tool_def = ToolDef(tool)

    # Should be transfer_to_custom_agent, not transfer_to_react
    assert tool_def.name == "transfer_to_custom_agent"


def test_handoff_multiple_react_agents_unique_names():
    """Test that multiple react agents with different names create unique tool names."""
    from inspect_ai.agent._react import react

    agent_a = react(name="agent_a", description="Agent A", tools=[])
    agent_b = react(name="agent_b", description="Agent B", tools=[])

    tool_a = handoff(agent_a)
    tool_b = handoff(agent_b)

    tool_def_a = ToolDef(tool_a)
    tool_def_b = ToolDef(tool_b)

    assert tool_def_a.name == "transfer_to_agent_a"
    assert tool_def_b.name == "transfer_to_agent_b"
    assert tool_def_a.name != tool_def_b.name
