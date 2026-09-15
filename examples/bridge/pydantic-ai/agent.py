from pydantic import BaseModel, Field
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.capabilities import WebSearch

from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.model import get_model, user_prompt
from inspect_ai.model._model import ModelName


class AnswerToQueryOutput(BaseModel):
    answer: str = Field(description="The answer to the query")


def _pydantic_bridge_model() -> str:
    """Map the active Inspect model to a Pydantic AI bridge model id.

    Pydantic AI picks its HTTP client from the provider prefix (``openai:``,
    ``anthropic:``, ``google:``, etc.). The bridge intercepts requests for
    models named ``inspect`` and routes them through Inspect's model layer, but
    the provider prefix must still match the client library Pydantic AI uses.
    """
    api = ModelName(get_model()).api
    match api:
        case "openai":
            return "openai-responses:inspect"
        case "anthropic":
            return "anthropic:inspect"
        case "google":
            return "google:inspect"
        case _:
            return "openai-responses:inspect"


@agent
def web_research_agent() -> Agent:
    """Pydantic AI Web Research Agent."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            agent = PydanticAgent(
                _pydantic_bridge_model(),
                capabilities=[WebSearch()],
                system_prompt="You help users find information by searching the web.",
                output_type=AnswerToQueryOutput,
                retries={"output": 3},
            )

            result = await agent.run(user_prompt(state.messages).text)

            # capture the typed result as the completion (as the final
            # assistant message includes on the `final_answer()` tool
            # call that PydanticAI uses to report its answer
            bridge.state.output.completion = result.output.model_dump_json()

            return bridge.state

    return execute
