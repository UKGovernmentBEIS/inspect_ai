from pydantic import BaseModel, Field
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import WebSearchTool

from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.model import user_prompt


class AnswerToQueryOutput(BaseModel):
    answer: str = Field(description="The answer to the query")


@agent
def web_research_agent() -> Agent:
    """OpenAI Agents SDK search agent."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            # define agent
            agent = PydanticAgent(
                "openai-responses:inspect",
                builtin_tools=[WebSearchTool()],
                system_prompt="You help users find information by searching the web.",
                output_type=AnswerToQueryOutput,
            )

            # run agent and capture result
            result = await agent.run(user_prompt(state.messages).text)

            # capture the typed result as the completion (as the final
            # assistant message includes on the `final_answer()` tool
            # call that PydanticAI uses to report its answer
            bridge.state.output.completion = result.output.model_dump_json()

            # return state
            return bridge.state

    return execute
