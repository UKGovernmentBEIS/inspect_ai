import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, convert_to_messages
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent


def web_research_agent(*, model: BaseChatModel | None = None, max_results: int = 5):
    """LangChain web research agent.

    Can be used outside of Inspect (see __main__ handler below) or within Inspect
    using the bridge() function (see task.py)

    Args:
       model: LangChain model. Specify `None` (the default) when using with Inspect.
       max_results: Max search results to return (for use of Tavily search tool)

    Returns:
       Agent function for handling samples. May be passed to Inspect `bridge()`
       to create a standard Inspect solver.
    """
    # Configure web research tools/agent
    agent_model = ChatOpenAI(model="inspect") if model is None else model
    agent_tools = [TavilySearchResults(max_results=max_results)]
    agent_executor = create_react_agent(
        model=agent_model,
        tools=agent_tools,
        checkpointer=MemorySaver(),
    )

    # Sample handler
    async def run(sample: dict[str, Any]) -> dict[str, Any]:
        # Read input (these are standard OpenAI message dicts, convert to LangChain)
        input = convert_to_messages(sample["input"])

        # Execute the agent
        result = await agent_executor.ainvoke(
            input={"messages": input},
            config={"configurable": {"thread_id": uuid4()}},
        )

        # Return output (content of last message)
        ai_message: AIMessage = result["messages"][-1]
        return dict(output=str(ai_message.content))

    return run


# Use the agent outside of Inspect
if __name__ == "__main__":

    async def main():
        # Read json dataset
        dataset_path = Path(__file__).parent / "dataset.json"
        with open(dataset_path, "r") as f:
            dataset = json.load(f)

        # Create agent and run samples in parallel
        agent = web_research_agent(model=ChatOpenAI(model="gpt-4o"))
        results = await asyncio.gather(*[agent(sample) for sample in dataset])

        # Print outputs
        print("\n\n===\n\n".join([result["output"] for result in results]))

    asyncio.run(main())
