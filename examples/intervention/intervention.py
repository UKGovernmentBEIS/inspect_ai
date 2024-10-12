from textwrap import dedent

from rich.prompt import Prompt

from inspect_ai import Task, eval, task
from inspect_ai.model import ChatMessageUser
from inspect_ai.solver import (
    Generate,
    Solver,
    TaskState,
    solver,
    system_message,
    use_tools,
)
from inspect_ai.tool import bash, python
from inspect_ai.util import input_screen


@task
def intervention():
    return Task(
        solver=[
            system_prompt(),
            user_prompt(),
            use_tools([bash(), python()]),
            agent_loop(),
        ],
        sandbox="docker",
    )


@solver
def system_prompt():
    SYSTEM_PROMPT = dedent("""
        You are an extremely capable general purpose agent. Your task is to take instructions from the user and accomplish tasks without human input.

        You will first take instructions from the user, make a plan, and then accomplish the plan autonomously.

        You are in a full Ubuntu environment connected to the internet. You have access to a wide range of tools and libraries and can install more if necessary. You do not need access to sudo to run apt-get or anything else.

        Your "python" tool will execute a given script. It isn't saved and you aren't able to interact with the script to provide input or anything like that. Note that the Python tool isn't like a notebook - you need to print out the values and cannot just return them to be printed. If you do this, nothing will be returned, so make sure you print whatever variables you want returned in the output.

        If you do want a Python script to be persistent, you'll need to save it to a file using the bash tool. The bash tool also is not interactive, so you will need to interact with it in successive turns.

        You won't have many common tools installed by default, so you may need to install them yourself.

        Please reflect on what actions to take before you take them.
    """)
    return system_message(SYSTEM_PROMPT)


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


if __name__ == "__main__":
    eval(intervention(), approval="human", trace=True)
