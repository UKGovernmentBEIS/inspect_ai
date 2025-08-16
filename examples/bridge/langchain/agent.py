from uuid import uuid4

from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.messages import (
    convert_to_messages,
    convert_to_openai_messages,
)
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.model import ModelOutput, messages_from_openai, messages_to_openai


@agent
def web_research_agent(*, max_results: int = 5) -> Agent:
    """LangChain Tavili search agent.

    Args:
       max_results: Max search results to return (for use of Tavily search tool)

    Returns:
       Agent function for handling samples. May be passed to Inspect `bridge()`
       to create a standard Inspect solver.
    """
    # Use OpenAI interface -- will be redirected to current Inspect model
    # by the agent_bridge() context manager.
    model = ChatOpenAI(model="inspect")

    # Configure web research tools/agent
    tools = [TavilySearchResults(max_results=max_results)]
    executor = create_react_agent(
        model=model,
        tools=tools,
        checkpointer=MemorySaver(),
    )

    # Sample handler
    async def execute(state: AgentState) -> AgentState:
        # Use bridge to map OpenAI Completions API to Inspect
        async with agent_bridge():
            # Read input (convert to LangChain)
            openai_messages = await messages_to_openai(state.messages)
            input = convert_to_messages(openai_messages)

            # Execute the agent
            result = await executor.ainvoke(
                input={"messages": input},
                config={"configurable": {"thread_id": uuid4()}},
            )

            # Update and return state
            openai_messages = convert_to_openai_messages(result["messages"])
            state.messages = await messages_from_openai(openai_messages)
            state.output = ModelOutput.from_message(state.messages[-1])
            return state

    return execute
