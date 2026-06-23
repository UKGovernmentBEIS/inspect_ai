from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.messages import convert_to_messages
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.checkpoint.memory import MemorySaver

from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.model import messages_to_openai


@agent
def web_research_agent(*, max_results: int = 5) -> Agent:
    """LangChain Tavily search agent.

    Args:
       max_results: Max search results to return (for use of Tavily search tool)

    Returns:
       Agent function for handling samples. May be passed to Inspect `bridge()`
       to create a standard Inspect solver.
    """

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            model = ChatOpenAI(model="inspect")
            tools = [TavilySearch(max_results=max_results)]
            executor = create_agent(
                model=model,
                tools=tools,
                system_prompt=(
                    "You help users find information by searching the web."
                ),
                checkpointer=MemorySaver(),
            )

            openai_messages = await messages_to_openai(state.messages)
            messages = convert_to_messages(openai_messages)

            await executor.ainvoke(
                {"messages": messages},
                config={"configurable": {"thread_id": str(uuid4())}},
            )
            return bridge.state

    return execute
