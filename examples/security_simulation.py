from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match
from inspect_ai.solver import generate, system_message

SYSTEM_MESSAGE = """
You are a security analyst helping to triage a simulated incident.
Answer exactly Yes or No.
"""


@task
def security_simulation():
    return Task(
        dataset=[
            Sample(
                input=(
                    "A web server saw 500 login attempts from one IP in one minute. "
                    "Is this suspicious?"
                ),
                target="Yes",
            )
        ],
        solver=[system_message(SYSTEM_MESSAGE), generate()],
        scorer=match(),
    )
