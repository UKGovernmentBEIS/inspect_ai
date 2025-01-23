from typing import Any
from uuid import uuid4

from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.messages import convert_to_messages, convert_to_openai_messages
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent


async def research_agent(sample: dict[str, Any]) -> dict[str, Any]:
    # create the model, tools, and agent
    model = ChatOpenAI(model_name=sample["model"])
    tools = [TavilySearchResults()]
    agent_executor = create_react_agent(model, tools, checkpointer=MemorySaver())

    # execute the agent (convert openai messages to langchain)
    result = await agent_executor.ainvoke(
        input={"messages": convert_to_messages(sample["messages"])},
        config={"configurable": {"thread_id": uuid4()}},
    )

    # return result (playback messages as openai-compatible)
    messages = convert_to_openai_messages(result["messages"])
    return {"output": messages[-1]["content"], "messages": messages}
