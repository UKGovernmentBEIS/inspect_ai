from textwrap import dedent
from typing import Literal

from rich.prompt import Prompt

from inspect_ai import Task, task
from inspect_ai.model import ChatMessageUser
from inspect_ai.solver import (
    Generate,
    Solver,
    TaskState,
    solver,
    system_message,
    use_tools,
)
from inspect_ai.solver._chain import chain
from inspect_ai.tool import bash, computer, python
from inspect_ai.tool._tools._bash_session import bash_session
from inspect_ai.tool._tools._text_editor import text_editor
from inspect_ai.tool._tools._web_browser._web_browser import web_browser
from inspect_ai.util import input_screen

Mode = Literal["shell", "computer", "multi-tool"]


@task
def intervention(mode: Mode = "shell", approval: bool = False) -> Task:
    match mode:
        case "shell":
            return Task(
                solver=intervention_agent(mode),
                sandbox=("docker", "shell/compose.yaml"),
                approval="human" if approval else None,
            )
        case "computer":
            return Task(
                solver=intervention_agent(mode),
                sandbox=("docker", "computer/compose.yaml"),
                approval="computer/approval.yaml" if approval else None,
            )
        case _:
            return Task(
                solver=intervention_agent(mode),
                sandbox=("docker", "multi_tool/compose.yaml"),
                approval="human" if approval else None,
            )


@solver
def intervention_agent(mode: Mode) -> Solver:
    match mode:
        case "shell":
            return chain(
                system_message(SHELL_PROMPT),
                user_prompt(),
                use_tools([bash(), python()]),
                agent_loop(),
            )
        case "computer":
            return chain(
                system_message(COMPUTER_PROMPT),
                user_prompt(),
                use_tools([computer()]),
                agent_loop(),
            )
        case _:
            return chain(
                system_message(MULTI_TOOL_PROMPT),
                user_prompt(),
                use_tools([bash_session(), text_editor()] + web_browser()),
                agent_loop(),
            )


SHELL_PROMPT = dedent("""
    You are an extremely capable general purpose agent. Your task is to take instructions from the user and accomplish tasks without human input.

    You will first take instructions from the user, make a plan, and then accomplish the plan autonomously.

    You are in a full Ubuntu environment connected to the internet. You have access to a wide range of tools and libraries and can install more if necessary. You do not need access to sudo to run apt-get or anything else.

    Your "python" tool will execute a given script. It isn't saved and you aren't able to interact with the script to provide input or anything like that. Note that the Python tool isn't like a notebook - you need to print out the values and cannot just return them to be printed. If you do this, nothing will be returned, so make sure you print whatever variables you want returned in the output.

    If you do want a Python script to be persistent, you'll need to save it to a file using the bash tool. The bash tool also is not interactive, so you will need to interact with it in successive turns.

    You won't have many common tools installed by default, so you may need to install them yourself.

    Please reflect on what actions to take before you take them.
    """)

COMPUTER_PROMPT = dedent("""
    You are an extremely capable general purpose agent. Your task is to take instructions from the user and accomplish tasks without human input.

    You are in a full Ubuntu environment connected to the internet.

    Please reflect on what actions to take before you take them.

    After each step carefully evaluate if you have achieved the right outcome. Explicitly show your thinking: "I have evaluated step X..." If not correct, try again. Only when you confirm a step was executed correctly should you move on to the next one.
    """)


MULTI_TOOL_PROMPT = dedent("""
    You are an extremely capable general purpose agent. Your task is to take instructions from the user and accomplish tasks without human input.

    You are in a full Ubuntu environment connected to the internet. You have a bash_session tool, a text_editor tools, and a set of web browser tools.

    You won't have many common tools installed by default, so you may need to install them yourself.

    Please reflect on what actions to take before you take them.
    """)


@solver
def user_prompt() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        with input_screen("User Prompt") as console:
            state.user_prompt.content = Prompt.ask(
                "Please enter your initial prompt for the model:\n\n", console=console
            )

        return state

    return solve


@solver
def agent_loop() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        while True:
            # generate w/ tool calls, approvals, etc.
            state = await generate(state)

            # check for completed
            if state.completed:
                break

            # prompt for next action
            next_action = ask_for_next_action()
            with input_screen():
                match next_action.strip().lower():
                    case "exit":
                        break
                    case "":
                        state.messages.append(
                            ChatMessageUser(
                                content="Please continue working on this task."
                            )
                        )
                        continue
                    case _:
                        state.messages.append(ChatMessageUser(content=next_action))

        return state

    return solve


def ask_for_next_action() -> str:
    with input_screen("Next Action") as console:
        return Prompt.ask(
            dedent("""
                The agent has stopped calling tools. Please either:

                - Type a message to send to the agent
                - Type nothing and hit enter to ask the agent to continue
                - Type 'exit' to end the conversation
            """).strip()
            + "\n\n",
            default="",
            console=console,
        )
