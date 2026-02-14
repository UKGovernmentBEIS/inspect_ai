from inspect_ai import Task, task
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match
from inspect_ai.tool import bash


@task
def binary_repro_react():
    return Task(
        dataset=[
            Sample(
                input=(
                    "Do these steps in order:\n\n"
                    "Step 1: Run: echo $((2+2))\n"
                    "Step 2: Run: cat /bin/ls | head -c 5000\n"
                    "Step 3: Run: cat /bin/cat | head -c 5000\n"
                    "Step 4: Run: cat /bin/cp | head -c 5000\n"
                    "Step 5: Run: cat /bin/mv | head -c 5000\n"
                    "Step 6: Run: cat /bin/rm | head -c 5000\n"
                    "Step 7: Run: cat /bin/chmod | head -c 5000\n"
                    "Step 8: Run: cat /bin/chown | head -c 5000\n"
                    "Step 9: Run: cat /bin/mkdir | head -c 5000\n"
                    "Step 10: Run: cat /usr/bin/head | head -c 5000\n"
                    "Step 11: Run: cat /usr/bin/tail | head -c 5000\n"
                    "\nAfter each command, briefly describe what you see. "
                    "Do all 11 steps, do not skip any."
                ),
                target="irrelevant",
            )
        ],
        solver=react(tools=[bash()]),
        scorer=match(),
        sandbox="docker",
    )
