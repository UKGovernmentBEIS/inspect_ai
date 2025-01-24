import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import jsonlines
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import convert_to_messages, convert_to_openai_messages
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent


def research_agent(*, model: str | BaseChatModel = "inspect", max_results: int = 5):
    """LangChain web research agent.

    Can be used outside of Inspect (see __main__ handler below) or within Inspect
    using the bridge() function (see task.py)

    Args:
       model: "inspect" for use with the Inspect bridge or a LangChain model.
       max_results: Max search results to return (for use of Tavily search tool)

    Returns:
       Agent function for handling samples. May be passed to Inspect `bridge()`
       to create a standard Inspect solver.
    """
    # Configure web research tools/agent
    agent_model = ChatOpenAI(model="inspect") if model == "inspect" else model
    agent_tools = [TavilySearchResults(max_results=max_results)]
    agent_executor = create_react_agent(
        model=agent_model,
        tools=agent_tools,
        checkpointer=MemorySaver(),
    )

    # Sample handler
    async def run(sample: dict[str, Any]) -> dict[str, Any]:
        # Read input messages (these are in standard OpenAI format, convert to LangChain)
        input = convert_to_messages(sample["input"])

        # Execute the agent
        result = await agent_executor.ainvoke(
            input={"messages": input},
            config={"configurable": {"thread_id": uuid4()}},
        )

        # Read and return messages and output (convert messages to OpenAI format)
        messages = convert_to_openai_messages(result["messages"])
        output = messages[-1]["content"]
        return dict(output=output, messages=messages)

    return run


# Develop and test the agent in isolation from Inspect
if __name__ == "__main__":

    async def main():
        # Read json lines dataset and build samples
        dataset_path = Path(__file__).parent / "dataset.jsonl"
        with open(dataset_path, "r") as f:
            dataset = list(jsonlines.Reader(f).iter(type=dict))
            samples = [dict(input=record["input"]) for record in dataset]

        # Run samples in parallel
        agent = research_agent(model=ChatOpenAI(model="gpt-4o"))
        results = await asyncio.gather(*[agent(sample) for sample in samples])

        # Print outputs
        print([result["output"] for result in results])

    asyncio.run(main())
