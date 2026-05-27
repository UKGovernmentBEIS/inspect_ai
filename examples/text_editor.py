from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Target, accuracy, scorer
from inspect_ai.solver import TaskState, generate, use_tools, user_message
from inspect_ai.tool import text_editor
from inspect_ai.util import sandbox


@task
def text_editor_task():
    return Task(
        dataset=[
            Sample(
                input=(
                    "Use the text_editor tool to create a file at /tmp/greeting.py "
                    "with a Python function called `greet` that takes a `name` "
                    "parameter and returns the string 'Hello, {name}!'."
                ),
                target="Goodbye",
            )
        ],
        solver=[
            use_tools(text_editor()),
            generate(),
            user_message(
                "Now use the text_editor to view the file /tmp/greeting.py "
                "and confirm its contents."
            ),
            generate(),
            user_message(
                "Now use the text_editor str_replace command to change "
                "'Hello' to 'Goodbye' in /tmp/greeting.py."
            ),
            generate(),
            user_message(
                "Now use the text_editor insert command to insert the line "
                "'# Author: Inspector' after line 1 of /tmp/greeting.py."
            ),
            generate(),
        ],
        scorer=verify_edit(),
        sandbox="docker",
    )


@scorer(metrics=[accuracy()])
def verify_edit():
    async def score(state: TaskState, target: Target):
        try:
            content = await sandbox().read_file("/tmp/greeting.py")
            has_goodbye = "Goodbye" in content
            has_no_hello = "Hello" not in content
            has_author = "# Author: Inspector" in content
            correct = has_goodbye and has_no_hello and has_author
            return Score(
                value=1.0 if correct else 0.0,
                answer=content,
                explanation=(
                    "File contains expected edit."
                    if correct
                    else "Edit not applied correctly."
                ),
            )
        except FileNotFoundError:
            return Score(
                value=0.0,
                answer="File not found",
                explanation="The file /tmp/greeting.py was not created.",
            )

    return score
