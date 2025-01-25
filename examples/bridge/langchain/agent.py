from typing import Any
from uuid import uuid4

from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.messages import AIMessage, convert_to_messages
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent


def web_research_agent(*, max_results: int = 5):
    """LangChain Tavili search agent.

    Args:
       max_results: Max search results to return (for use of Tavily search tool)

    Returns:
       Agent function for handling samples. May be passed to Inspect `bridge()`
       to create a standard Inspect solver.
    """
    # Use OpenAI interface (will be redirected to current Inspect model)
    model = ChatOpenAI(model="inspect")

    # Configure web research tools/agent
    tools = [TavilySearchResults(max_results=max_results)]
    executor = create_react_agent(
        model=model,
        tools=tools,
        checkpointer=MemorySaver(),
    )

    # Sample handler
    async def run(sample: dict[str, Any]) -> dict[str, Any]:
        # Read input (these are standard OpenAI message dicts, convert to LangChain)
        input = convert_to_messages(sample["input"])

        # Execute the agent
        result = await executor.ainvoke(
            input={"messages": input},
            config={"configurable": {"thread_id": uuid4()}},
        )

        # Return output (content of last message)
        message: AIMessage = result["messages"][-1]
        return dict(output=str(message.content))

    return run
