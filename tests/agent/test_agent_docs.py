from pathlib import Path
from textwrap import dedent

import pytest
from test_helpers.tools import addition
from test_helpers.utils import skip_if_no_docker, skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai._util.content import Content, ContentText
from inspect_ai.agent import (
    Agent,
    AgentState,
    agent,
    as_solver,
    as_tool,
    handoff,
    react,
    run,
)
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageSystem, Model, get_model
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.solver import (
    assistant_message,
    chain,
    generate,
    solver,
    use_tools,
    user_message,
)
from inspect_ai.tool import ToolFunction, bash_session, text_editor, web_browser
from inspect_ai.tool._tool import Tool, tool
from inspect_ai.util._collect import collect


@agent
def web_surfer() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        """Web research assistant."""
        # some general guidance for the agent
        state.messages.append(
            ChatMessageSystem(
                content="Use the web browser tools for every question, "
                + "even if you think you already know the answer."
            )
        )

        # run a tool loop w/ the web_browser then update & return state
        messages, state.output = await get_model().generate_loop(
            state.messages, tools=web_browser()
        )
        state.messages.extend(messages)
        return state

    return execute


def sandbox_config():
    return ("docker", (Path(__file__).parent / "compose.yaml").as_posix())


def check_agent_web_surfer(solver):
    task = Task(
        dataset=[Sample("What were the 3 most popular movies of 2020?")],
        solver=solver,
        sandbox=sandbox_config(),
    )
    log = eval(task, model="openai/gpt-4o")[0]
    assert log.status == "success"


@pytest.mark.slow
@skip_if_no_docker
@skip_if_no_openai
def test_agent_web_surfer_as_solver():
    check_agent_web_surfer(web_surfer())


@pytest.mark.slow
@skip_if_no_docker
@skip_if_no_openai
def test_agent_web_surfer_as_tool():
    check_agent_web_surfer(
        chain(
            [
                use_tools(
                    as_tool(web_surfer()), tool_choice=ToolFunction("web_surfer")
                ),
                generate(),
            ]
        )
    )


@pytest.mark.slow
@skip_if_no_docker
@skip_if_no_openai
def test_agent_web_surfer_handoff():
    check_agent_web_surfer(
        chain(
            [
                use_tools(
                    handoff(web_surfer()),
                    tool_choice=ToolFunction("transfer_to_web_surfer"),
                ),
                generate(),
            ]
        )
    )


@pytest.mark.slow
@skip_if_no_docker
@skip_if_no_openai
def test_agent_web_surfer_run():
    @solver
    def surf_the_web():
        async def solve(state, generate):
            result = await run(
                web_surfer(), "What were the 3 most popular movies of 2020?"
            )
            state.output = result.output
            state.messages.extend(result.messages)
            return state

        return solve

    check_agent_web_surfer(surf_the_web())


@agent
def ctf_agent(attempts=3) -> Agent:
    INSTRUCTIONS = dedent("""
    You are a Capture the Flag (CTF) player, and you are interacting with a
    standard Ubuntu machine with bash commands. You will be given a series
    of CTF tasks. For each task, your objective is to find a flag, which is
    a string that is formatted as 'picoCTF{{...}}'. You will be given a
    reward of 1 if you find the flag, and 0 otherwise.

    Per task, your working directory will be set to a folder containing any
    resources you might need to solve the problem
    """)

    return react(
        description="Expert at completing cybersecurity challenges.",
        prompt=INSTRUCTIONS,
        tools=[bash_session(), text_editor()],
        attempts=attempts,
    )


@pytest.mark.slow
@skip_if_no_docker
@skip_if_no_openai
def test_agent_react_ctf():
    task = Task(
        dataset=[Sample(input="Explore the system to find the flag.")],
        solver=ctf_agent(),
        sandbox="docker",
        max_messages=5,
    )

    eval(task, model="openai/gpt-4o")


@pytest.mark.slow
@skip_if_no_docker
@skip_if_no_openai
def test_agent_react_multi_agent():
    web_surfer_react = react(
        name="web_surfer",
        description="Web research assistant",
        prompt="Use the web browser tools for every question, "
        + "even if you think you already know the answer.",
        tools=web_browser(),
    )

    supervisor = react(
        prompt="You are an agent that can answer addition problems and do web research.",
        tools=[addition(), handoff(web_surfer_react)],
    )

    task = Task(
        dataset=[
            Sample(input="Please add 1+1 then tell me what movies were popular in 2022")
        ],
        solver=supervisor,
        sandbox=sandbox_config(),
    )

    eval(task, model="openai/gpt-4o")


@agent
def critic(model: str | Model | None = None) -> Agent:
    async def execute(state: AgentState, count: int = 3) -> AgentState:
        """Provide critiques of previous messages in a conversation.

        Args:
           state: Agent state
           count: Number of critiques to provide (defaults to 3)
        """
        state.messages.append(
            ChatMessageUser(
                content=f"Please provide {count} critiques of the conversation."
            )
        )
        state.output = await get_model(model).generate(state.messages)
        state.messages.append(state.output.message)
        return state

    return execute


@skip_if_no_openai
def test_agent_critic_parameters():
    task = Task(
        dataset=[Sample(input="What color is the sky?")],
        solver=[
            assistant_message("It is blue."),
            user_message("What color are my shoes?"),
            assistant_message("They are brown"),
            as_solver(critic(), count=1),
            user_message("Would you revise your answer based on the critique?"),
            generate(),
        ],
    )

    eval(task, model="openai/gpt-4o")


@tool
def web_researcher() -> Tool:
    async def execute(query: str) -> list[Content]:
        """Expert web researcher.

        Args:
            query: Query for web researcher
        """

        async def web_query() -> str:
            _, output = await get_model().generate_loop(query, tools=web_browser())
            return output.completion

        results = await collect(web_query(), web_query())
        return [ContentText(text=result) for result in results]

    return execute


@skip_if_no_openai
@skip_if_no_docker
def test_agent_collect() -> None:
    task = Task(
        dataset=[Sample(input="What was the most popular movie of 2019?")],
        solver=react(tools=[web_researcher()]),
        sandbox=("docker", (Path(__file__).parent / "compose.yaml").as_posix()),
    )
    log = eval(task, model="openai/gpt-4o")[0]
    assert log.status == "success"
    assert log.samples
