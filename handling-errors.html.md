# Handling Errors – Inspect

## Overview

Errors during evaluation fall into two distinct categories:

1.  **Runtime Errors** — A Python exception occurs during eval execution (e.g. a bug in a solver, an unreliable API, or a sandbox failure). The process terminates normally and the eval log is written with status `"error"`, preserving all completed samples.

2.  **Crash Recovery** — The eval process dies unexpectedly (e.g. out-of-memory, segfault, power failure, or `kill -9`). The eval log is incomplete — status remains `"started"`, and samples that were completed but not yet flushed to disk are missing from the log.

The sections below cover techniques for handling both scenarios.

## Runtime Errors

Runtime errors result in a log with status `"error"` that contains all samples completed before the error occurred. These logs can be retried to re-run only the failed samples.

## Eval Retries

When an evaluation task fails due to an error or is otherwise interrupted (e.g. by a Ctrl+C), an evaluation log is still written. In many cases errors are transient (e.g. due to network connectivity or a rate limit) and can be subsequently *retried*.

For these cases, Inspect includes an `eval-retry` command and [eval_retry()](./reference/inspect_ai.html.md#eval_retry) function that you can use to resume tasks interrupted by errors (including [preserving samples](./eval-logs.html.md#sec-sample-preservation) already completed within the original task). For example, if you had a failing task with log file `logs/2024-05-29T12-38-43_math_Gprr29Mv.json`, you could retry it from the shell with:

``` bash
$ inspect eval-retry logs/2024-05-29T12-38-43_math_43_math_Gprr29Mv.json
```

Or from Python with:

``` python
eval_retry("logs/2024-05-29T12-38-43_math_43_math_Gprr29Mv.json")
```

Note that retry only works for tasks that are created from `@task` decorated functions (as if a [Task](./reference/inspect_ai.html.md#task) is created dynamically outside of an `@task` function Inspect does not know how to reconstruct it for the retry).

Note also that [eval_retry()](./reference/inspect_ai.html.md#eval_retry) does not overwrite the previous log file, but rather creates a new one (preserving the `task_id` from the original file).

Here’s an example of retrying a failed eval with a lower number of `max_connections` (the theory being that too many concurrent connections may have caused a rate limit error):

``` python
log = eval(my_task)[0]
if log.status != "success":
  eval_retry(log, max_connections = 3)
```

## Failure Threshold

In some cases you might wish to tolerate some number of errors without failing the evaluation. This might be during development when errors are more commonplace, or could be to deal with a particularly unreliable API used in the evaluation. Add the `fail_on_error` option to your [Task](./reference/inspect_ai.html.md#task) definition to establish this threshold. For example, here we indicate that we’ll tolerate errors in up to 10% of the total sample count before failing:

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

Failed samples are *not scored* and a warning indicating that some samples failed is both printed in the terminal and shown in Inspect View when this occurs.

You can specify `fail_on_error` as a boolean (turning the behaviour on and off entirely), as a number between 0 and 1 (indicating a proportion of failures to tolerate), or a number greater than 1 to (indicating a count of failures to tolerate):

| Value                 | Behaviour                                           |
|-----------------------|-----------------------------------------------------|
| `fail_on_error=True`  | Fail eval immediately on sample errors (default).   |
| `fail_on_error=False` | Never fail eval on sample errors.                   |
| `fail_on_error=0.1`   | Fail if more than 10% of total samples have errors. |
| `fail_on_error=5`     | Fail eval if more than 5 samples have errors.       |

While `fail_on_error` is typically specified at the [Task](./reference/inspect_ai.html.md#task) level, you can also override the task setting when calling [eval()](./reference/inspect_ai.html.md#eval) or `inspect eval` from the CLI. For example:

``` python
eval("intercode_ctf.py", fail_on_error=False)
```

You might choose to do this if you want to tolerate a certain proportion of errors during development but want to ensure there are never errors when running in production.

## Sample Retries

The `retry_on_error` option enables retrying samples with errors some number of times before they are considered failed (and subject to `fail_on_error` processing as described above). For example:

``` bash
inspect eval ctf.py --retry-on-error    # retry 1 time
inspect eval ctf.py --retry-on-error=3  # retry up to 3 times
```

Or from Python:

``` python
eval("ctf.py", retry_on_error=1)
```

If a sample is retried, the original error(s) that induced the retries will be recorded in its `error_retries` field.

> **WARNING: WarningRetries and Distribution Shift**
>
> While sample retries enable improved recovery from transient infrastructure errors, they also carry with them some risk of distribution shift. For example, imagine that the error being retried is a bug in one of your agents that is triggered by only certain classes of input. These classes of input could then potentially have a higher chance of success because they will be “re-rolled” more frequently.
>
> Consequently, when enabling `retry_on_error` you should do some post-hoc analysis to ensure that retried samples don’t have significantly different results than samples which are not retried.

## Scoring Errored Samples

Some evaluations are designed so that an error during the agent run is itself a meaningful (often failing) outcome — for example, a tool-using agent that crashes after producing partial state, or a benchmark where “the model errored” should count as a scoreable result rather than as missing data.

The `score_on_error` option causes errored samples to be scored anyway (using whatever [TaskState](./reference/inspect_ai.solver.html.md#taskstate) was reached before the error), and prevents `fail_on_error` from crashing the eval mid-run:

``` bash
inspect eval ctf.py --score-on-error
```

Or from Python:

``` python
eval("ctf.py", score_on_error=True)
```

When enabled:

- Each errored sample is recorded with both its `error` (so the viewer’s per-sample display, traceback, and error indicators behave exactly as before) **and** its `scores` (so the sample contributes to metrics).

- `score_on_error` only fires after retries (if any) are exhausted, so it composes with `retry_on_error` — intermediate failed retries are not scored, only the final attempt is.

- Errors are still counted toward the `fail_on_error` threshold for marking the eval log status. So `--score-on-error --fail-on-error=0.1` will score every errored sample but mark the log as `"error"` if more than 10% of samples errored. `--score-on-error --no-fail-on-error` always finalises as `"success"`.

- When used inside [eval_set()](./reference/inspect_ai.html.md#eval_set), errored-but-scored samples are still re-run on task-level retries (the previously-successful samples are reused as usual).

> **NOTE:**
>
> Your scorer must be able to run on a partial [TaskState](./reference/inspect_ai.solver.html.md#taskstate). The state passed to scorers reflects whatever was populated before the error was raised — it may not have a model output, may have an incomplete message history, etc. If your scorer would itself raise on a partial state, the sample will end up with an error and no score (the same as if `score_on_error` were off).

## Crash Recovery

When an eval process dies unexpectedly (out-of-memory, segfault, `kill`, power failure, etc.), the eval log is left in an incomplete state:

- The log has status `"started"` (the process never got to write the final status).
- Samples that were completed but not yet flushed to the log file are missing.
- Samples that were still running at the time of the crash are missing.

However, Inspect maintains a separate sample buffer database during evaluation. This database persists on disk after a crash and contains the unflushed sample data. Crash recovery combines the data from the incomplete log file with the sample buffer database to produce a complete recovered log.

### Manual Recovery

You can also recover crashed logs manually using the CLI. You might want to do this if you aren’t running in a retry loop like [eval_set()](./reference/inspect_ai.html.md#eval_set) or for the purpose of investigating the cause of crashes (note that samples not yet completed will still appear in the recovered log so you can view what happened prior to the crash).

To list all recoverable logs in the current log directory:

``` bash
inspect log recover --list
```

To recover a specific log:

``` bash
inspect log recover path/to/crashed.eval
```

This creates a new file `path/to/crashed-recovered.eval` containing the recovered samples. To overwrite the original file instead:

``` bash
inspect log recover path/to/crashed.eval --overwrite
```

After recovery, if there are cancelled or failed samples, the CLI will suggest running `eval-retry` to re-run them:

    Recovered 47 samples to path/to/crashed-recovered.eval
      status: error

    To re-run the 5 failed/cancelled samples:
      inspect eval-retry path/to/crashed-recovered.eval

> **NOTE:**
>
> The sample buffer database is retained for 3 days after the eval process exits. Recovery should be performed soon after a crash to ensure the data is still available.

### Automatic Recovery

When using [eval_set()](./reference/inspect_ai.html.md#eval_set) or [eval_retry()](./reference/inspect_ai.html.md#eval_retry), crash recovery is performed automatically. If a log with status `"started"` is encountered during retry, Inspect will opportunistically attempt to recover unflushed samples from the buffer database before re-running the evaluation. This maximizes sample reuse—completed samples recovered from the buffer are not re-run.

No user action is needed. If the buffer database is no longer available (e.g. the crash happened more than 3 days ago), the retry proceeds with only the samples that were flushed to the log file.

#### Post-Mortem Debugging

After a successful automatic retry, you may want to investigate what caused the original crash. The “started” logs from crashed tasks are preserved (not cleaned up), and the sample buffer database is also retained during automatic recovery so it remains available for investigation.

To find and recover crashed logs for analysis:

``` bash
# List logs with "started" status (crashed tasks)
inspect log list --status started

# Recover a crashed log for investigation (write outside the eval set directory)
inspect log recover path/to/started.eval --output ~/recovered/started-recovered.eval
```

### Resolving Stalled Samples

By default, samples that were still in progress at the time of the crash are recovered as cancelled errors, and the recovered log keeps status `"error"` — so [eval_set()](./reference/inspect_ai.html.md#eval_set) and `eval-retry` will re-run them. For agentic evals this can loop forever: a handful of samples hang, the process is killed, and the retry re-runs the same samples only for them to hang again.

The `--incomplete-action` option resolves this by letting you choose the disposition for in-progress samples:

- `retry` (the default) marks them as cancelled errors that a later retry re-runs.
- `error` resolves them as operator terminations. When every expected sample is then final, the recovered log is finalized with status `"success"` and full results — nothing will retry it. If expected samples are missing entirely (never started), the log keeps status `"error"` and stays retryable. Expected samples are matched by id and epoch against the ids recorded in the log, so for a task with a dynamic `sample_source` (whose log records only the seed samples’ ids) finalization happens only when the written samples are exactly the seed samples; once produced samples have been written, the log stays retryable. Finalization also requires the eval’s metrics to be recomputed, so if a scorer or metric cannot be resolved in the recovery process (for example, a custom metric from a package that is not installed there) the log is not finalized either. Whenever `error` does not finalize, `inspect log recover` prints a `not finalized:` line giving the reason.

Note that finalization freezes *every* errored sample in the recovered log, not only the ones resolved during recovery: samples that had already failed before the crash (within the eval’s `fail_on_error` tolerance, or with `fail_on_error=False`) are recorded as errors in the finalized log rather than re-run — the same outcome the eval would have reached had it not crashed. An explicit `inspect eval-retry` on the finalized log can still re-run its errored samples later.

For example, to bring a crashed eval with a few hung samples to a terminal state:

``` bash
inspect log recover path/to/crashed.eval --incomplete-action error
```

The `--incomplete-max` option guards against silently completing a systemic failure (e.g. a provider outage that left *most* samples in progress). Specify a count (a value of 1 or more), or a proportion of expected samples (a value strictly less than 1, so `1.0` means one sample rather than 100%; negative values are rejected); when more samples are in progress than the threshold allows, manual recovery refuses without writing anything:

``` bash
inspect log recover path/to/crashed.eval --incomplete-action error --incomplete-max 0.1
```

The same options are available on `inspect eval-retry` and `inspect eval-set` (and the [eval_retry()](./reference/inspect_ai.html.md#eval_retry) and [eval_set()](./reference/inspect_ai.html.md#eval_set) functions), where they apply to the automatic recovery of crashed logs. There, exceeding `--incomplete-max` falls back to the default recover-and-retry behavior rather than failing. You can also set these via the `INSPECT_EVAL_INCOMPLETE_ACTION` and `INSPECT_EVAL_INCOMPLETE_MAX` environment variables. On every surface `--incomplete-max` only guards a resolving disposition: with the default `retry` it has no effect, and a warning is logged so the mismatch is visible.

### Python API

You can also use the Python API perform recovery actions:

``` python
from inspect_ai.log import recover_eval_log, recoverable_eval_logs

# List recoverable logs
logs = recoverable_eval_logs()

# Recover a specific log
log = recover_eval_log("path/to/crashed.eval")

# Recover, resolving in-progress samples so nothing retries them
log = recover_eval_log(
    "path/to/crashed.eval",
    incomplete_action="error",
    incomplete_max=0.1,
)
```
