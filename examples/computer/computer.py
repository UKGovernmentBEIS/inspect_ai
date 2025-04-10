from inspect_ai import Task, task
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.tool import computer

SYSTEM_MESSAGE = """
Before each step, please clearly explain your intent for performing a tool action: "I expect tool command X to ...".

After each step, carefully evaluate the resulting screenshot to see if the command achieved the right outcome.

Explicitly show your thinking: "I have evaluated step X..." If not correct, try again. Only when
you confirm a step was executed correctly should you move on to the next one.

Note that launching applications from desktop icons requires a double click.
"""


@task
def computer_task():
    return Task(
        dataset=[
            Sample(
                input="Use the computer tool to find the contents of the file '/tmp/flag.txt'. When you've found it, report its contents.",
                target="Frunobulax",
                files={"/tmp/flag.txt": "Frunobulax"},
            ),
            Sample(
                input="Use the computer tool to launch a terminal. Type 'Trudging across the tundra. Mile after Mile.' into the terminal. Important: Make sure that the terminal window is active before typing. When you are done, please use the submit tool to record the result of hitting enter in the terminal after entering that text.",
                target="bash: Trudging: command not found",
            ),
            Sample(
                input="Use the computer tool to launch a calculator. Calculate 123 x 456. Report the result.",
                target="56088",
            ),
        ],
        solver=react(
            prompt=SYSTEM_MESSAGE,
            tools=[computer()],
        ),
        messsage_limit=100,
        scorer=includes(),
        sandbox="docker",
    )
