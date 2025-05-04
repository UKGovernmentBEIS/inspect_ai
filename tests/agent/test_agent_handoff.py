from test_helpers.tool_call_utils import find_tool_call
from test_helpers.tools import addition
from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.agent import Agent, AgentState, agent, handoff
from inspect_ai.agent._filter import MessageFilter, last_message, remove_tools
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    get_model,
)
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import Tool


@agent
def searcher() -> Agent:
    async def execute(state: AgentState, max_searches: int = 5) -> AgentState:
        """Searcher that computes max searches.

        Args:
            state: Input state (conversation)
            max_searches: Maximum number of web searches to conduct

        Returns:
            Ouput state (additions to conversation)
        """
        state.messages.append(
            ChatMessageUser(content=f"The maximum searches is {max_searches}")
        )

        return state

    return execute


def check_agent_handoff(
    max_searches: int | None = None, handoff_tool: Tool | None = None
):
    input = (
        "Please use the searcher to determine the max_searches. "
        + "You should only handoff to the searcher tool a single time, then just report the result."
    )
    if max_searches and not handoff_tool:
        input = f"{input} Please pass the value {max_searches} to the searcher."
    log = eval(
        Task(dataset=[Sample(input=input)]),
        solver=[use_tools(handoff_tool or handoff(searcher())), generate()],
        model="openai/gpt-4o-mini",
    )[0]
    assert log.samples
    tool_call = find_tool_call(log, "transfer_to_searcher")
    assert tool_call
    max_searches = max_searches or 5
    assistant_message = log.samples[0].messages[-1]
    assert str(max_searches) in assistant_message.text


@skip_if_no_openai
def test_agent_handoff_tool():
    check_agent_handoff()


@skip_if_no_openai
def test_agent_handoff_tool_arg():
    check_agent_handoff(10)


@skip_if_no_openai
def test_agent_handoff_tool_curry():
    check_agent_handoff(15, handoff(searcher(), max_searches=15))


@agent
def searcher2() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        """Searcher that computes max searches.

        Args:
            state: Input state (conversation)
            max_searches: Maximum number of web searches to conduct

        Returns:
            Ouput state (additions to conversation)
        """
        return state

    return execute


@skip_if_no_openai
def test_agent_handoff_user_message():
    log = eval(
        Task(
            dataset=[
                Sample(input="Please use the searcher2 to determine the max_searches.")
            ]
        ),
        solver=[use_tools(handoff(searcher2())), generate()],
        model="openai/gpt-4o-mini",
    )[0]
    assert log.samples
    messages = log.samples[0].messages

    def check_message(message: ChatMessage, message_type: type[ChatMessage]) -> None:
        assert isinstance(message, message_type)
        assert "searcher2" in message.text

    check_message(messages[-1], ChatMessageAssistant)
    check_message(messages[-2], ChatMessageUser)
    check_message(messages[-3], ChatMessageTool)


@agent
def searcher3() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        """Searcher that computes max searches.

        Args:
            state: Input state (conversation)
            max_searches: Maximum number of web searches to conduct

        Returns:
            Ouput state (additions to conversation)
        """
        output = await get_model().generate(state.messages)
        state.messages.append(output.message)
        state.output = output

        return state

    return execute


@skip_if_no_openai
def test_agent_handoff_assistant_prefix():
    log = eval(
        Task(
            dataset=[
                Sample(input="Please use the searcher3 to determine the max_searches.")
            ]
        ),
        solver=[use_tools(handoff(searcher3())), generate()],
        model="openai/gpt-4o-mini",
    )[0]
    assert log.samples
    messages = log.samples[0].messages
    assistant_message = messages[-3]
    assert isinstance(assistant_message, ChatMessageAssistant)
    assert assistant_message.text.startswith("[searcher3]")


@agent
def eventsource() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        """Agent that yields events

        Args:
            state: Input state (conversation)
            max_searches: Maximum number of web searches to conduct

        Returns:
            Ouput state (additions to conversation)
        """
        from inspect_ai.log._transcript import transcript

        # this creates a model event
        model = get_model("mockllm/model")
        await model.generate("What time is it?")

        # this creates an info event
        transcript().info("This is an InfoEvent")

        # raise an error
        raise RuntimeError("Boom!")

    return execute


@skip_if_no_openai
def test_agent_handoff_tool_event():
    log = eval(
        Task(
            dataset=[Sample(input="Please use the eventsource to source some events.")]
        ),
        solver=[use_tools(handoff(eventsource())), generate()],
        model="openai/gpt-4o-mini",
        log_format="json",
    )[0]
    assert log.samples

    # ensure that we have a tool event with the embedded model event
    tool_event = next(
        (event for event in log.samples[0].events if event.event == "tool")
    )
    assert tool_event
    model_event = next(
        (event for event in reversed(log.samples[0].events) if event.event == "model")
    )
    assert model_event
    assert model_event.input[0].text == "What time is it?"


@agent
def tool_checker() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        """Tool checker that checks if tool messages are present.

        Args:
            state: Input state (conversation)

        Returns:
            Ouput state (additions to conversation)
        """
        tool_messages = sum(
            [
                1
                for m in state.messages
                if isinstance(m, ChatMessageTool)
                or (isinstance(m, ChatMessageAssistant) and m.tool_calls is not None)
            ]
        )
        state.messages.append(ChatMessageAssistant(content=str(tool_messages)))

        return state

    return execute


def check_agent_handoff_input_filter(
    input_filter: MessageFilter | None, tool_count: int
):
    log = eval(
        Task(
            dataset=[
                Sample(
                    input="Please use the addition tool to add 1+1. Then, handoff to the tool_checker. "
                    + "You should only handoff to the tool checker a single time, then just report the result."
                )
            ]
        ),
        solver=[
            use_tools(addition(), handoff(tool_checker(), input_filter=input_filter)),
            generate(),
        ],
        model="openai/gpt-4o-mini",
        parallel_tool_calls=False,
        log_format="json",
    )[0]
    assert log.samples
    assert (
        next(
            (
                message
                for message in log.samples[0].messages
                if message.text == f"[tool_checker] {tool_count}"
            ),
            None,
        )
        is not None
    )


@skip_if_no_openai
def test_agent_handoff_no_input_filter():
    check_agent_handoff_input_filter(None, 4)


@skip_if_no_openai
def test_agent_handoff_remove_tools_input_filter():
    check_agent_handoff_input_filter(remove_tools, 0)


@agent
def oracle() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        """Oracle that answers questions.

        Args:
            state: Input state (conversation)

        Returns:
            Ouput state (additions to conversation)
        """
        state.output = await get_model().generate(state.messages)
        state.messages.append(state.output.message)
        state.messages.append(
            ChatMessageUser(content="That's great, can you give me another answer?")
        )
        state.output = await get_model().generate(state.messages)
        state.messages.append(state.output.message)

        return state

    return execute


def check_agent_handoff_output_filter(
    output_filter: MessageFilter | None, messages_len: int
):
    log = eval(
        Task(
            dataset=[
                Sample(
                    input="Please ask the oracle a question?"
                    + "You should only ask the oracle a single question, then just report the result."
                )
            ]
        ),
        solver=[use_tools(handoff(oracle(), output_filter=output_filter)), generate()],
        model="openai/gpt-4o-mini",
        log_format="json",
    )[0]
    assert log.samples
    assert len(log.samples[0].messages) == messages_len


@skip_if_no_openai
def test_agent_handoff_no_output_filter():
    check_agent_handoff_output_filter(None, 8)


@skip_if_no_openai
def test_agent_handoff_last_message_output_filter():
    check_agent_handoff_output_filter(last_message, 6)
