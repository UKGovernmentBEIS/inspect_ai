from typing import Any
from uuid import uuid4

from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.messages import convert_to_messages, convert_to_openai_messages
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent


async def research_agent(sample: dict[str, Any]) -> dict[str, Any]:
    # Read model (this is an Inspect model name e.g. google/gemini-1.5-pro).
    # Use OpenAI interface (when running in the Inspect bridge this will be
    # redirected to the appropriate Inspect model provider).
    model_name = sample["model"]
    model = ChatOpenAI(model_name=model_name)

    # Read messages (these are in standard OpenAI format, convert to LangChain)
    messages = convert_to_messages(sample["messages"])

    # Configure web research tools/agent
    tools = [TavilySearchResults()]
    agent_executor = create_react_agent(model, tools, checkpointer=MemorySaver())

    # Execute the agent
    result = await agent_executor.ainvoke(
        input={"messages": messages},
        config={"configurable": {"thread_id": uuid4()}},
    )

    # Read and return messages and output (convert messages to OpenAI format)
    agent_messages = convert_to_openai_messages(result["messages"])
    agent_output = agent_messages[-1]["content"]
    return dict(output=agent_output, messages=agent_messages)
