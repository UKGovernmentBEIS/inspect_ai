from test_helpers.tool_call_utils import find_tool_call
from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.agent import Agent, AgentState, agent, handoff
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
    input = "Please use the searcher to determine the max_searches."
    if max_searches and not handoff_tool:
        input = f"{input} Please pass the value {max_searches} to the searcher."
    log = eval(
        Task(dataset=[Sample(input=input)]),
        solver=[use_tools(handoff_tool or handoff(searcher())), generate()],
        model="openai/gpt-4o-mini",
    )[0]
    assert log.samples
    tool_call = find_tool_call(log, "handoff_to_searcher")
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
