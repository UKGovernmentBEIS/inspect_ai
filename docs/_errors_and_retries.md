## Errors and Retries {#sec-errors-and-retries}

When an evaluation task fails due to an error or is otherwise interrupted (e.g. by a Ctrl+C), an evaluation log is still written. In many cases errors are transient (e.g. due to network connectivity or a rate limit) and can be subsequently *retried*.

For these cases, Inspect includes an `eval-retry` command and `eval_retry()` function that you can use to resume tasks interrupted by errors (including [preserving samples](eval-logs.qmd#sec-sample-preservation) already completed within the original task). For example, if you had a failing task with log file `logs/2024-05-29T12-38-43_math_Gprr29Mv.json`, you could retry it from the shell with:

``` bash
$ inspect eval-retry logs/2024-05-29T12-38-43_math_43_math_Gprr29Mv.json
```

Or from Python with:

``` python
eval_retry("logs/2024-05-29T12-38-43_math_43_math_Gprr29Mv.json")
```

Note that retry only works for tasks that are created from `@task` decorated functions (as if a `Task` is created dynamically outside of an `@task` function Inspect does not know how to reconstruct it for the retry).

Note also that `eval_retry()` does not overwrite the previous log file, but rather creates a new one (preserving the `task_id` from the original file).

Here's an example of retrying a failed eval with a lower number of `max_connections` (the theory being that too many concurrent connections may have caused a rate limit error):

``` python
log = eval(my_task)[0]
if log.status != "success":
  eval_retry(log, max_connections = 3)
```


