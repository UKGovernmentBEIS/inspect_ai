from openai import AsyncOpenAI

from inspect_ai import Task, eval, task
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.dataset import Sample
from inspect_ai.model._prompt import user_prompt
from inspect_ai.scorer import includes


@agent
def responses_agent() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            client = AsyncOpenAI()

            await client.responses.create(
                model="inspect",
                input=user_prompt(state.messages).text,
            )

            return bridge.state

    return execute


@task
def bridged_task():
    return Task(
        dataset=[
            Sample(
                input="Please print the word 'hello'?",
                target="hello",
            )
        ],
        solver=responses_agent(),
        scorer=includes(),
    )


if __name__ == "__main__":
    eval(
        bridged_task(),
        model="openai/gpt-4o",
        display="plain",
    )
