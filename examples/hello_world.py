from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import exact
from inspect_ai.solver import generate

# This is the simplest possible Inspect eval, useful for testing your configuration / network / platform etc.

# Thank you for getting to the bottom of this! I think there are few remedies possible here:
# This logging is actually for supporting "realtime" view of logs in the viewer. We could simply allow this to be disabled (samples would still be logged as normal just no realtime view).
# Knowing this is a potential issue we could proactively disable realtime views for very large numbers of samples.
# We could do time based buffering of the database inserts (note that the buffer you experimented with is for writing to the .eval file not for the db, which does not currently do any buffering)
# Note that the Python sqlite interface is sync but I am not at all sure this is the main issue. There are async sqlite wrappers that use threads under the hood, but these don't work w/ Trio (and we are committed to allowing users to choose either asyncio or trio as their async backend). It's also not clear whether this yields any perf benefit (e.g. see https://github.com/simonw/datasette/issues/1727).


@task
def hello_world():
    return Task(
        dataset=[
            Sample(
                input="Just reply with Hello World",
                target="Hello World",
            )
        ],
        solver=[
            generate(cache=True),
        ],
        scorer=exact(),
    )


def main():
    eval_logs = eval(
        hello_world(),
        max_samples=900,
        max_connections=900,
        model="openai/gpt-4.1-nano",
        epochs=2000,
        log_samples=True,
        display="plain",
        log_buffer=50,
    )
    print(eval_logs)


if __name__ == "__main__":
    main()
