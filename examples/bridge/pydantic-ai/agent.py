from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import WebSearchTool

from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.model import user_prompt


@agent
def web_research_agent() -> Agent:
    """OpenAI Agents SDK search agent."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            agent = PydanticAgent(
                "openai-responses:inspect",
                builtin_tools=[WebSearchTool()],
                system_prompt="You help users find information by searching the web.",
            )

            await agent.run(user_prompt(state.messages).text)

            return bridge.state

    return execute
