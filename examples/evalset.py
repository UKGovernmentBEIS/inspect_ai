"""
This example demonstrates creating and running an Inspect eval set.

Eval sets take multiple tasks (possibly evaluated against multiple
models) and run them together, automatically retrying failed samples
as tasks as required. If an initial pass + retries is not successful,
eval set scripts can be run repeatedly until all of the tasks have
successfully completed.

Eval sets track their progress over multiple invocations using a
dedicated log directory (i.e. you should create a new log directory
for each run of an eval set).

Below we demonstrate a basic wrapper script for eval_set:

1) We define a core run() function that accepts a log_dir and
   any other relevant parameters.

2) We provide a CLI wrapper for run() using the click library.

3) The script exit with success only if all of the tasks
   were successfully completed.

This script enables customizsation of the number of retry attempts
(defaulting to 10). It accepts the following other eval_set defaults,
but your own script might want to customise these further:

- retry_wait: 30 seconds, increasing exponentially to no more than 1hr
- retry_connections: 0.5, halfing the max_connections with every retry
- retry_cleanup: True, automatically removing logs for failed tasks
"""

import sys

import click
from security_guide import security_guide
from theory_of_mind import theory_of_mind

from inspect_ai import eval_set


@click.command()
@click.option("--log-dir", type=str, required=True)
@click.option("--retry-attempts", default=10)
def run(log_dir: str, retry_attempts: int):
    """Run 2 tasks on 2 models, retrying as required if errors occur.

    Args:
       log_dir: Log directory for eval set (required).
       retry_attempts: Number of retry attempts (defaults to 10)

    Returns:
       Tuple of bool, list[EvalLog] with sucess status and final logs
    """
    # run eval_set
    return eval_set(
        tasks=[security_guide(), theory_of_mind()],
        model=["openai/gpt-4o", "anthropic/claude-3-5-sonnet-20240620"],
        log_dir=log_dir,
        retry_attempts=retry_attempts,
    )


# enable invocation as a script
if __name__ == "__main__":
    success, _ = run()
    sys.exit(0 if success else 1)
