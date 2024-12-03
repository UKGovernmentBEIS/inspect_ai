# Errors and Limits


## Overview

When developing more complex evaluations, its not uncommon to encounter
error conditions during development—these might occur due to a bug in a
solver or scorer, an unreliable or overloaded API, or a failure to
communicate with a sandbox environment. It’s also possible to end up
evals that don’t terminate properly because models continue running in a
tool calling loop even though they are “stuck” and very unlikely to make
additioanal progress.

This article covers various techniques for dealing with unexpected
errors and setting limits on evaluation tasks and samples. Topics
covered include:

1.  Retrying failed evaluations (while preserving the samples completed
    during the initial failed run).
2.  Establishing a threshold (count or percentage) of samples to
    tolerate errors for before failing an evaluation.
3.  Setting a maximum number of messages in a sample before forcing the
    model to give up.

## Errors and Retries

When an evaluation task fails due to an error or is otherwise
interrupted (e.g. by a Ctrl+C), an evaluation log is still written. In
many cases errors are transient (e.g. due to network connectivity or a
rate limit) and can be subsequently *retried*.

For these cases, Inspect includes an `eval-retry` command and
`eval_retry()` function that you can use to resume tasks interrupted by
errors (including [preserving
samples](eval-logs.qmd#sec-sample-preservation) already completed within
the original task). For example, if you had a failing task with log file
`logs/2024-05-29T12-38-43_math_Gprr29Mv.json`, you could retry it from
the shell with:

``` bash
$ inspect eval-retry logs/2024-05-29T12-38-43_math_43_math_Gprr29Mv.json
```

Or from Python with:

``` python
eval_retry("logs/2024-05-29T12-38-43_math_43_math_Gprr29Mv.json")
```

Note that retry only works for tasks that are created from `@task`
decorated functions (as if a `Task` is created dynamically outside of an
`@task` function Inspect does not know how to reconstruct it for the
retry).

Note also that `eval_retry()` does not overwrite the previous log file,
but rather creates a new one (preserving the `task_id` from the original
file).

Here’s an example of retrying a failed eval with a lower number of
`max_connections` (the theory being that too many concurrent connections
may have caused a rate limit error):

``` python
log = eval(my_task)[0]
if log.status != "success":
  eval_retry(log, max_connections = 3)
```

## Failure Threshold

In some cases you might wish to tolerate some number of errors without
failing the evaluation. This might be during development when errors are
more commonplace, or could be to deal with a particularly unreliable API
used in the evaluation. Add the `fail_on_error` option to your `Task`
definition to establish this threshold. For example, here we indicate
that we’ll tolerate errors in up to 10% of the total sample count before
failing:

``` python
@task
def intercode_ctf():
    return Task(
        dataset=read_dataset(),
        solver=[
            system_message("system.txt"),
            use_tools([bash(timeout=120)]),
            generate(),
        ],
        fail_on_error=0.1,
        scorer=includes(),
        sandbox="docker",
    )
```

Failed samples are *not scored* and a warning indicating that some
samples failed is both printed in the terminal and shown in Inspect View
when this occurs.

You can specify `fail_on_error` as a boolean (turning the behaviour on
and off entirely), as a number between 0 and 1 (indicating a proportion
of failures to tolerate), or a number greater than 1 to (indicating a
count of failures to tolerate):

<table>
<colgroup>
<col style="width: 40%" />
<col style="width: 60%" />
</colgroup>
<thead>
<tr class="header">
<th>Value</th>
<th>Behaviour</th>
</tr>
</thead>
<tbody>
<tr class="odd">
<td><code>fail_on_error=True</code></td>
<td>Fail eval immediately on sample errors (default).</td>
</tr>
<tr class="even">
<td><code>fail_on_error=False</code></td>
<td>Never fail eval on sample errors.</td>
</tr>
<tr class="odd">
<td><code>fail_on_error=0.1</code></td>
<td>Fail if more than 10% of total samples have errors.</td>
</tr>
<tr class="even">
<td><code>fail_on_error=5</code></td>
<td>Fail eval if more than 5 samples have errors.</td>
</tr>
</tbody>
</table>

While `fail_on_error` is typically specified at the `Task` level, you
can also override the task setting when calling `eval()` or
`inspect eval` from the CLI. For example:

``` python
eval("intercode_ctf.py", fail_on_error=False)
```

You might choose to do this if you want to tolerate a certain proportion
of errors during development but want to ensure there are never errors
when running in production.

## Sample Limits

In open-ended model conversations (for example, an agent evaluation with
tool usage) it’s possible that a model will get “stuck” attempting to
perform a task with no realistic prospect of completing it. Further,
sometimes models will call commands in a sandbox that take an extremely
long time (or worst case, hang indefinitely).

For this type of evaluation it’s normally a good idea to set sample
level limits on some combination of total time, total messages, and/or
tokens used. Sample limits don’t result in errors, but rather an early
exit from execution (samples that encounter limits are still scored,
albeit nearly always as “incorrect”).

### Time Limit

Here we set a `time_limit` of 15 minutes (15 x 60 seconds) for each
sample within a task:

``` python
@task
def intercode_ctf():
    return Task(
        dataset=read_dataset(),
        solver=[
            system_message("system.txt"),
            use_tools([bash(timeout=3 * 60)]),
            generate(),
        ],
        time_limit=15 * 60,
        scorer=includes(),
        sandbox="docker",
    )
```

Note that we also set a timeout of 3 minutes for the `bash()` command.
This isn’t required but is often a good idea so that a single wayward
bash command doesn’t consume the entire `time_limit`.

We can also specify a time limit at the CLI or when calling `eval()`:

``` bash
inspect eval ctf.py --time-limit 900
```

Appropriate timeouts will vary depending on the nature of your task so
please view the above as examples only rather than recommend values.

### Message Limit

Here we set a `message_limit` of 30 for each sample within a task:

``` python
@task
def intercode_ctf():
    return Task(
        dataset=read_dataset(),
        solver=[
            system_message("system.txt"),
            use_tools([bash(timeout=120)]),
            generate(),
        ],
        message_limit=30,
        scorer=includes(),
        sandbox="docker",
    )
```

This sets a limit of 30 total messages in a conversation before the
model is forced to give up. At that point, whatever `output` happens to
be in the `TaskState` will be scored (presumably leading to a score of
incorrect).

Note that its also possible for a solver to set the `message_limit`
directly on the `TaskState` (this is often done by agent solvers which
provide their own generate loop):

``` python
@solver
def agent_loop(message_limit: int = 50):
    async def solve(state: TaskState, generate: Generate):

        # establish message limit so we have a termination condition
        state.message_limit = message_limit

        ...
```

### Token Limit

Here we set a `token_limit` of 500K for each sample within a task:

``` python
@task
def intercode_ctf():
    return Task(
        dataset=read_dataset(),
        solver=[
            system_message("system.txt"),
            use_tools([bash(timeout=120)]),
            generate(),
        ],
        token_limit=(1024*500),
        scorer=includes(),
        sandbox="docker",
    )
```

As with `message_limit`, it’s also possible for a solver to set the
`token_limit` directly on the `TaskState`:

``` python
@solver
def agent_loop(token_limit: int = (1024 * 500)) -> Solver:
    async def solve(state: TaskState, generate: Generate):

        # establish token limit so we have a termination condition
        state.token_limit = token_limit

        ...
```

<div>

> **Important**
>
> It’s important to note that the `token_limit` is for all tokens used
> within the execution of a sample. If you want to limit the number of
> tokens that can be yielded from a single call to the model you should
> use the `max_tokens` generation option.

</div>

### Limit Checking

How and when are sample limits checked? Time limits are handled
automatically by the code that runs the sample. Message and token limits
are checked automatically when you access the `completed` property of
`TaskState`. For example, most agents will use `state.completed` as
their main loop condition:

``` python
while not state.completed:
    # call model
    output = await model.generate(state.messages, state.tools)
    
    ...
```

If you are writing an agent loop you should check `state.completed` so
that message and token limits can be enforced. Library code that calls a
series of solvers in succession should also check `state.completed`
(note that this is done automatically by the `chain()` function that is
used to compose together lists of solvers).
