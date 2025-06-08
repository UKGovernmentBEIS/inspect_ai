# inspect_ai


## Evaluation

### eval

Evaluate tasks using a Model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ffa0b49015ef14412d66dff6d3a0a8b77e3edf70/src/inspect_ai/_eval/eval.py#L70)

``` python
def eval(
    tasks: Tasks,
    model: str | Model | list[str] | list[Model] | None | NotGiven = NOT_GIVEN,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str = dict(),
    model_roles: dict[str, str | Model] | None = None,
    task_args: dict[str, Any] | str = dict(),
    sandbox: SandboxEnvironmentType | None = None,
    sandbox_cleanup: bool | None = None,
    solver: Solver | SolverSpec | Agent | list[Solver] | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    trace: bool | None = None,
    display: DisplayType | None = None,
    approval: str | list[ApprovalPolicy] | None = None,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    limit: int | tuple[int, int] | None = None,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    retry_on_error: int | None = None,
    debug_errors: bool | None = None,
    message_limit: int | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    working_limit: int | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    log_samples: bool | None = None,
    log_realtime: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
    log_shared: bool | int | None = None,
    log_header_only: bool | None = None,
    score: bool = True,
    score_display: bool | None = None,
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[EvalLog]
```

`tasks` [Tasks](inspect_ai.qmd#tasks)  
Task(s) to evaluate. If None, attempt to evaluate a task in the current
working directory

`model` str \| [Model](inspect_ai.model.qmd#model) \| list\[str\] \| list\[[Model](inspect_ai.model.qmd#model)\] \| None \| NotGiven  
Model(s) for evaluation. If not specified use the value of the
INSPECT_EVAL_MODEL environment variable. Specify `None` to define no
default model(s), which will leave model usage entirely up to tasks.

`model_base_url` str \| None  
Base URL for communicating with the model API.

`model_args` dict\[str, Any\] \| str  
Model creation args (as a dictionary or as a path to a JSON or YAML
config file)

`model_roles` dict\[str, str \| [Model](inspect_ai.model.qmd#model)\] \| None  
Named roles for use in `get_model()`.

`task_args` dict\[str, Any\] \| str  
Task creation arguments (as a dictionary or as a path to a JSON or YAML
config file)

`sandbox` SandboxEnvironmentType \| None  
Sandbox environment type (or optionally a str or tuple with a shorthand
spec)

`sandbox_cleanup` bool \| None  
Cleanup sandbox environments after task completes (defaults to True)

`solver` [Solver](inspect_ai.solver.qmd#solver) \| [SolverSpec](inspect_ai.solver.qmd#solverspec) \| [Agent](inspect_ai.agent.qmd#agent) \| list\[[Solver](inspect_ai.solver.qmd#solver)\] \| None  
Alternative solver for task(s). Optional (uses task solver by default).

`tags` list\[str\] \| None  
Tags to associate with this evaluation run.

`metadata` dict\[str, Any\] \| None  
Metadata to associate with this evaluation run.

`trace` bool \| None  
Trace message interactions with evaluated model to terminal.

`display` [DisplayType](inspect_ai.util.qmd#displaytype) \| None  
Task display type (defaults to ‘full’).

`approval` str \| list\[[ApprovalPolicy](inspect_ai.approval.qmd#approvalpolicy)\] \| None  
Tool use approval policies. Either a path to an approval policy config
file or a list of approval policies. Defaults to no approval policy.

`log_level` str \| None  
Level for logging to the console: “debug”, “http”, “sandbox”, “info”,
“warning”, “error”, or “critical” (defaults to “warning”)

`log_level_transcript` str \| None  
Level for logging to the log file (defaults to “info”)

`log_dir` str \| None  
Output path for logging results (defaults to file log in ./logs
directory).

`log_format` Literal\['eval', 'json'\] \| None  
Format for writing log files (defaults to “eval”, the native
high-performance format).

`limit` int \| tuple\[int, int\] \| None  
Limit evaluated samples (defaults to all samples).

`sample_id` str \| int \| list\[str\] \| list\[int\] \| list\[str \| int\] \| None  
Evaluate specific sample(s) from the dataset. Use plain ids or preface
with task names as required to disambiguate ids across tasks
(e.g. `popularity:10`).

`epochs` int \| [Epochs](inspect_ai.qmd#epochs) \| None  
Epochs to repeat samples for and optional score reducer function(s) used
to combine sample scores (defaults to “mean”)

`fail_on_error` bool \| float \| None  
`True` to fail on first sample error (default); `False` to never fail on
sample errors; Value between 0 and 1 to fail if a proportion of total
samples fails. Value greater than 1 to fail eval if a count of samples
fails.

`retry_on_error` int \| None  
Number of times to retry samples if they encounter errors (by default,
no retries occur).

`debug_errors` bool \| None  
Raise task errors (rather than logging them) so they can be debugged
(defaults to False).

`message_limit` int \| None  
Limit on total messages used for each sample.

`token_limit` int \| None  
Limit on total tokens used for each sample.

`time_limit` int \| None  
Limit on clock time (in seconds) for samples.

`working_limit` int \| None  
Limit on working time (in seconds) for sample. Working time includes
model generation, tool calls, etc. but does not include time spent
waiting on retries or shared resources.

`max_samples` int \| None  
Maximum number of samples to run in parallel (default is
max_connections)

`max_tasks` int \| None  
Maximum number of tasks to run in parallel (defaults to number of models
being evaluated)

`max_subprocesses` int \| None  
Maximum number of subprocesses to run in parallel (default is
os.cpu_count())

`max_sandboxes` int \| None  
Maximum number of sandboxes (per-provider) to run in parallel.

`log_samples` bool \| None  
Log detailed samples and scores (defaults to True)

`log_realtime` bool \| None  
Log events in realtime (enables live viewing of samples in inspect
view). Defaults to True.

`log_images` bool \| None  
Log base64 encoded version of images, even if specified as a filename or
URL (defaults to False)

`log_buffer` int \| None  
Number of samples to buffer before writing log file. If not specified,
an appropriate default for the format and filesystem is chosen (10 for
most all cases, 100 for JSON logs on remote filesystems).

`log_shared` bool \| int \| None  
Sync sample events to log directory so that users on other systems can
see log updates in realtime (defaults to no syncing). Specify `True` to
sync every 10 seconds, otherwise an integer to sync every `n` seconds.

`log_header_only` bool \| None  
If `True`, the function should return only log headers rather than full
logs with samples (defaults to `False`).

`score` bool  
Score output (defaults to True)

`score_display` bool \| None  
Show scoring metrics in realtime (defaults to True)

`**kwargs` Unpack\[[GenerateConfigArgs](inspect_ai.model.qmd#generateconfigargs)\]  
Model generation options.

### eval_retry

Retry a previously failed evaluation task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ffa0b49015ef14412d66dff6d3a0a8b77e3edf70/src/inspect_ai/_eval/eval.py#L566)

``` python
def eval_retry(
    tasks: str | EvalLogInfo | EvalLog | list[str] | list[EvalLogInfo] | list[EvalLog],
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    sandbox_cleanup: bool | None = None,
    trace: bool | None = None,
    display: DisplayType | None = None,
    fail_on_error: bool | float | None = None,
    retry_on_error: int | None = None,
    debug_errors: bool | None = None,
    log_samples: bool | None = None,
    log_realtime: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
    log_shared: bool | int | None = None,
    score: bool = True,
    score_display: bool | None = None,
    max_retries: int | None = None,
    timeout: int | None = None,
    max_connections: int | None = None,
) -> list[EvalLog]
```

`tasks` str \| [EvalLogInfo](inspect_ai.log.qmd#evalloginfo) \| [EvalLog](inspect_ai.log.qmd#evallog) \| list\[str\] \| list\[[EvalLogInfo](inspect_ai.log.qmd#evalloginfo)\] \| list\[[EvalLog](inspect_ai.log.qmd#evallog)\]  
Log files for task(s) to retry.

`log_level` str \| None  
Level for logging to the console: “debug”, “http”, “sandbox”, “info”,
“warning”, “error”, or “critical” (defaults to “warning”)

`log_level_transcript` str \| None  
Level for logging to the log file (defaults to “info”)

`log_dir` str \| None  
Output path for logging results (defaults to file log in ./logs
directory).

`log_format` Literal\['eval', 'json'\] \| None  
Format for writing log files (defaults to “eval”, the native
high-performance format).

`max_samples` int \| None  
Maximum number of samples to run in parallel (default is
max_connections)

`max_tasks` int \| None  
Maximum number of tasks to run in parallel (defaults to number of models
being evaluated)

`max_subprocesses` int \| None  
Maximum number of subprocesses to run in parallel (default is
os.cpu_count())

`max_sandboxes` int \| None  
Maximum number of sandboxes (per-provider) to run in parallel.

`sandbox_cleanup` bool \| None  
Cleanup sandbox environments after task completes (defaults to True)

`trace` bool \| None  
Trace message interactions with evaluated model to terminal.

`display` [DisplayType](inspect_ai.util.qmd#displaytype) \| None  
Task display type (defaults to ‘full’).

`fail_on_error` bool \| float \| None  
`True` to fail on first sample error (default); `False` to never fail on
sample errors; Value between 0 and 1 to fail if a proportion of total
samples fails. Value greater than 1 to fail eval if a count of samples
fails.

`retry_on_error` int \| None  
Number of times to retry samples if they encounter errors (by default,
no retries occur).

`debug_errors` bool \| None  
Raise task errors (rather than logging them) so they can be debugged
(defaults to False).

`log_samples` bool \| None  
Log detailed samples and scores (defaults to True)

`log_realtime` bool \| None  
Log events in realtime (enables live viewing of samples in inspect
view). Defaults to True.

`log_images` bool \| None  
Log base64 encoded version of images, even if specified as a filename or
URL (defaults to False)

`log_buffer` int \| None  
Number of samples to buffer before writing log file. If not specified,
an appropriate default for the format and filesystem is chosen (10 for
most all cases, 100 for JSON logs on remote filesystems).

`log_shared` bool \| int \| None  
Sync sample events to log directory so that users on other systems can
see log updates in realtime (defaults to no syncing). Specify `True` to
sync every 10 seconds, otherwise an integer to sync every `n` seconds.

`score` bool  
Score output (defaults to True)

`score_display` bool \| None  
Show scoring metrics in realtime (defaults to True)

`max_retries` int \| None  
Maximum number of times to retry request.

`timeout` int \| None  
Request timeout (in seconds)

`max_connections` int \| None  
Maximum number of concurrent connections to Model API (default is per
Model API)

### eval_set

Evaluate a set of tasks.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ffa0b49015ef14412d66dff6d3a0a8b77e3edf70/src/inspect_ai/_eval/evalset.py#L57)

``` python
def eval_set(
    tasks: Tasks,
    log_dir: str,
    retry_attempts: int | None = None,
    retry_wait: float | None = None,
    retry_connections: float | None = None,
    retry_cleanup: bool | None = None,
    model: str | Model | list[str] | list[Model] | None | NotGiven = NOT_GIVEN,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str = dict(),
    model_roles: dict[str, str | Model] | None = None,
    task_args: dict[str, Any] | str = dict(),
    sandbox: SandboxEnvironmentType | None = None,
    sandbox_cleanup: bool | None = None,
    solver: Solver | SolverSpec | Agent | list[Solver] | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    trace: bool | None = None,
    display: DisplayType | None = None,
    approval: str | list[ApprovalPolicy] | None = None,
    score: bool = True,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    limit: int | tuple[int, int] | None = None,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    retry_on_error: int | None = None,
    debug_errors: bool | None = None,
    message_limit: int | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    working_limit: int | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    log_samples: bool | None = None,
    log_realtime: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
    log_shared: bool | int | None = None,
    bundle_dir: str | None = None,
    bundle_overwrite: bool = False,
    **kwargs: Unpack[GenerateConfigArgs],
) -> tuple[bool, list[EvalLog]]
```

`tasks` [Tasks](inspect_ai.qmd#tasks)  
Task(s) to evaluate. If None, attempt to evaluate a task in the current
working directory

`log_dir` str  
Output path for logging results (required to ensure that a unique
storage scope is assigned for the set).

`retry_attempts` int \| None  
Maximum number of retry attempts before giving up (defaults to 10).

`retry_wait` float \| None  
Time to wait between attempts, increased exponentially. (defaults to 30,
resulting in waits of 30, 60, 120, 240, etc.). Wait time per-retry will
in no case by longer than 1 hour.

`retry_connections` float \| None  
Reduce max_connections at this rate with each retry (defaults to 0.5)

`retry_cleanup` bool \| None  
Cleanup failed log files after retries (defaults to True)

`model` str \| [Model](inspect_ai.model.qmd#model) \| list\[str\] \| list\[[Model](inspect_ai.model.qmd#model)\] \| None \| NotGiven  
Model(s) for evaluation. If not specified use the value of the
INSPECT_EVAL_MODEL environment variable. Specify `None` to define no
default model(s), which will leave model usage entirely up to tasks.

`model_base_url` str \| None  
Base URL for communicating with the model API.

`model_args` dict\[str, Any\] \| str  
Model creation args (as a dictionary or as a path to a JSON or YAML
config file)

`model_roles` dict\[str, str \| [Model](inspect_ai.model.qmd#model)\] \| None  
Named roles for use in `get_model()`.

`task_args` dict\[str, Any\] \| str  
Task creation arguments (as a dictionary or as a path to a JSON or YAML
config file)

`sandbox` SandboxEnvironmentType \| None  
Sandbox environment type (or optionally a str or tuple with a shorthand
spec)

`sandbox_cleanup` bool \| None  
Cleanup sandbox environments after task completes (defaults to True)

`solver` [Solver](inspect_ai.solver.qmd#solver) \| [SolverSpec](inspect_ai.solver.qmd#solverspec) \| [Agent](inspect_ai.agent.qmd#agent) \| list\[[Solver](inspect_ai.solver.qmd#solver)\] \| None  
Alternative solver(s) for evaluating task(s). ptional (uses task solver
by default).

`tags` list\[str\] \| None  
Tags to associate with this evaluation run.

`metadata` dict\[str, Any\] \| None  
Metadata to associate with this evaluation run.

`trace` bool \| None  
Trace message interactions with evaluated model to terminal.

`display` [DisplayType](inspect_ai.util.qmd#displaytype) \| None  
Task display type (defaults to ‘full’).

`approval` str \| list\[[ApprovalPolicy](inspect_ai.approval.qmd#approvalpolicy)\] \| None  
Tool use approval policies. Either a path to an approval policy config
file or a list of approval policies. Defaults to no approval policy.

`score` bool  
Score output (defaults to True)

`log_level` str \| None  
Level for logging to the console: “debug”, “http”, “sandbox”, “info”,
“warning”, “error”, or “critical” (defaults to “warning”)

`log_level_transcript` str \| None  
Level for logging to the log file (defaults to “info”)

`log_format` Literal\['eval', 'json'\] \| None  
Format for writing log files (defaults to “eval”, the native
high-performance format).

`limit` int \| tuple\[int, int\] \| None  
Limit evaluated samples (defaults to all samples).

`sample_id` str \| int \| list\[str\] \| list\[int\] \| list\[str \| int\] \| None  
Evaluate specific sample(s) from the dataset. Use plain ids or preface
with task names as required to disambiguate ids across tasks
(e.g. `popularity:10`).

`epochs` int \| [Epochs](inspect_ai.qmd#epochs) \| None  
Epochs to repeat samples for and optional score reducer function(s) used
to combine sample scores (defaults to “mean”)

`fail_on_error` bool \| float \| None  
`True` to fail on first sample error (default); `False` to never fail on
sample errors; Value between 0 and 1 to fail if a proportion of total
samples fails. Value greater than 1 to fail eval if a count of samples
fails.

`retry_on_error` int \| None  
Number of times to retry samples if they encounter errors (by default,
no retries occur).

`debug_errors` bool \| None  
Raise task errors (rather than logging them) so they can be debugged
(defaults to False).

`message_limit` int \| None  
Limit on total messages used for each sample.

`token_limit` int \| None  
Limit on total tokens used for each sample.

`time_limit` int \| None  
Limit on clock time (in seconds) for samples.

`working_limit` int \| None  
Limit on working time (in seconds) for sample. Working time includes
model generation, tool calls, etc. but does not include time spent
waiting on retries or shared resources.

`max_samples` int \| None  
Maximum number of samples to run in parallel (default is
max_connections)

`max_tasks` int \| None  
Maximum number of tasks to run in parallel (defaults to the greater of 4
and the number of models being evaluated)

`max_subprocesses` int \| None  
Maximum number of subprocesses to run in parallel (default is
os.cpu_count())

`max_sandboxes` int \| None  
Maximum number of sandboxes (per-provider) to run in parallel.

`log_samples` bool \| None  
Log detailed samples and scores (defaults to True)

`log_realtime` bool \| None  
Log events in realtime (enables live viewing of samples in inspect
view). Defaults to True.

`log_images` bool \| None  
Log base64 encoded version of images, even if specified as a filename or
URL (defaults to False)

`log_buffer` int \| None  
Number of samples to buffer before writing log file. If not specified,
an appropriate default for the format and filesystem is chosen (10 for
most all cases, 100 for JSON logs on remote filesystems).

`log_shared` bool \| int \| None  
Sync sample events to log directory so that users on other systems can
see log updates in realtime (defaults to no syncing). Specify `True` to
sync every 10 seconds, otherwise an integer to sync every `n` seconds.

`bundle_dir` str \| None  
If specified, the log viewer and logs generated by this eval set will be
bundled into this directory.

`bundle_overwrite` bool  
Whether to overwrite files in the bundle_dir. (defaults to False).

`**kwargs` Unpack\[[GenerateConfigArgs](inspect_ai.model.qmd#generateconfigargs)\]  
Model generation options.

### score

Score an evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ffa0b49015ef14412d66dff6d3a0a8b77e3edf70/src/inspect_ai/_eval/score.py#L37)

``` python
def score(
    log: EvalLog,
    scorers: Scorer | list[Scorer],
    epochs_reducer: ScoreReducers | None = None,
    action: ScoreAction | None = None,
) -> EvalLog
```

`log` [EvalLog](inspect_ai.log.qmd#evallog)  
Evaluation log.

`scorers` [Scorer](inspect_ai.scorer.qmd#scorer) \| list\[[Scorer](inspect_ai.scorer.qmd#scorer)\]  
List of Scorers to apply to log

`epochs_reducer` ScoreReducers \| None  
Reducer function(s) for aggregating scores in each sample. Defaults to
previously used reducer(s).

`action` ScoreAction \| None  
Whether to append or overwrite this score

## Tasks

### Task

Evaluation task.

Tasks are the basis for defining and running evaluations.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ffa0b49015ef14412d66dff6d3a0a8b77e3edf70/src/inspect_ai/_eval/task/task.py#L41)

``` python
class Task
```

#### Methods

\_\_init\_\_  
Create a task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ffa0b49015ef14412d66dff6d3a0a8b77e3edf70/src/inspect_ai/_eval/task/task.py#L47)

``` python
def __init__(
    self,
    dataset: Dataset | Sequence[Sample] | None = None,
    setup: Solver | list[Solver] | None = None,
    solver: Solver | Agent | list[Solver] = generate(),
    cleanup: Callable[[TaskState], Awaitable[None]] | None = None,
    scorer: Scorer | list[Scorer] | None = None,
    metrics: list[Metric] | dict[str, list[Metric]] | None = None,
    model: str | Model | None = None,
    config: GenerateConfig = GenerateConfig(),
    model_roles: dict[str, str | Model] | None = None,
    sandbox: SandboxEnvironmentType | None = None,
    approval: str | list[ApprovalPolicy] | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    message_limit: int | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    working_limit: int | None = None,
    name: str | None = None,
    version: int | str = 0,
    metadata: dict[str, Any] | None = None,
    **kwargs: Unpack[TaskDeprecatedArgs],
) -> None
```

`dataset` [Dataset](inspect_ai.dataset.qmd#dataset) \| Sequence\[[Sample](inspect_ai.dataset.qmd#sample)\] \| None  
Dataset to evaluate

`setup` [Solver](inspect_ai.solver.qmd#solver) \| list\[[Solver](inspect_ai.solver.qmd#solver)\] \| None  
Setup step (always run even when the main `solver` is replaced).

`solver` [Solver](inspect_ai.solver.qmd#solver) \| [Agent](inspect_ai.agent.qmd#agent) \| list\[[Solver](inspect_ai.solver.qmd#solver)\]  
Solver or list of solvers. Defaults to generate(), a normal call to the
model.

`cleanup` Callable\[\[[TaskState](inspect_ai.solver.qmd#taskstate)\], Awaitable\[None\]\] \| None  
Optional cleanup function for task. Called after all solvers have run
for each sample (including if an exception occurs during the run)

`scorer` [Scorer](inspect_ai.scorer.qmd#scorer) \| list\[[Scorer](inspect_ai.scorer.qmd#scorer)\] \| None  
Scorer used to evaluate model output.

`metrics` list\[[Metric](inspect_ai.scorer.qmd#metric)\] \| dict\[str, list\[[Metric](inspect_ai.scorer.qmd#metric)\]\] \| None  
Alternative metrics (overrides the metrics provided by the specified
scorer).

`model` str \| [Model](inspect_ai.model.qmd#model) \| None  
Default model for task (Optional, defaults to eval model).

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Model generation config for default model (does not apply to model
roles)

`model_roles` dict\[str, str \| [Model](inspect_ai.model.qmd#model)\] \| None  
Named roles for use in `get_model()`.

`sandbox` SandboxEnvironmentType \| None  
Sandbox environment type (or optionally a str or tuple with a shorthand
spec)

`approval` str \| list\[[ApprovalPolicy](inspect_ai.approval.qmd#approvalpolicy)\] \| None  
Tool use approval policies. Either a path to an approval policy config
file or a list of approval policies. Defaults to no approval policy.

`epochs` int \| [Epochs](inspect_ai.qmd#epochs) \| None  
Epochs to repeat samples for and optional score reducer function(s) used
to combine sample scores (defaults to “mean”)

`fail_on_error` bool \| float \| None  
`True` to fail on first sample error (default); `False` to never fail on
sample errors; Value between 0 and 1 to fail if a proportion of total
samples fails. Value greater than 1 to fail eval if a count of samples
fails.

`message_limit` int \| None  
Limit on total messages used for each sample.

`token_limit` int \| None  
Limit on total tokens used for each sample.

`time_limit` int \| None  
Limit on clock time (in seconds) for samples.

`working_limit` int \| None  
Limit on working time (in seconds) for sample. Working time includes
model generation, tool calls, etc. but does not include time spent
waiting on retries or shared resources.

`name` str \| None  
Task name. If not specified is automatically determined based on the
name of the task directory (or “task”) if its anonymous task
(e.g. created in a notebook and passed to eval() directly)

`version` int \| str  
Version of task (to distinguish evolutions of the task spec or breaking
changes to it)

`metadata` dict\[str, Any\] \| None  
Additional metadata to associate with the task.

`**kwargs` Unpack\[TaskDeprecatedArgs\]  
Deprecated arguments.

### task_with

Task adapted with alternate values for one or more options.

This function modifies the passed task in place and returns it. If you
want to create multiple variations of a single task using `task_with()`
you should create the underlying task multiple times.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ffa0b49015ef14412d66dff6d3a0a8b77e3edf70/src/inspect_ai/_eval/task/task.py#L180)

``` python
def task_with(
    task: Task,
    *,
    dataset: Dataset | Sequence[Sample] | None | NotGiven = NOT_GIVEN,
    setup: Solver | list[Solver] | None | NotGiven = NOT_GIVEN,
    solver: Solver | list[Solver] | NotGiven = NOT_GIVEN,
    cleanup: Callable[[TaskState], Awaitable[None]] | None | NotGiven = NOT_GIVEN,
    scorer: Scorer | list[Scorer] | None | NotGiven = NOT_GIVEN,
    metrics: list[Metric] | dict[str, list[Metric]] | None | NotGiven = NOT_GIVEN,
    model: str | Model | NotGiven = NOT_GIVEN,
    config: GenerateConfig | NotGiven = NOT_GIVEN,
    model_roles: dict[str, str | Model] | NotGiven = NOT_GIVEN,
    sandbox: SandboxEnvironmentType | None | NotGiven = NOT_GIVEN,
    approval: str | list[ApprovalPolicy] | None | NotGiven = NOT_GIVEN,
    epochs: int | Epochs | None | NotGiven = NOT_GIVEN,
    fail_on_error: bool | float | None | NotGiven = NOT_GIVEN,
    message_limit: int | None | NotGiven = NOT_GIVEN,
    token_limit: int | None | NotGiven = NOT_GIVEN,
    time_limit: int | None | NotGiven = NOT_GIVEN,
    working_limit: int | None | NotGiven = NOT_GIVEN,
    name: str | None | NotGiven = NOT_GIVEN,
    version: int | NotGiven = NOT_GIVEN,
    metadata: dict[str, Any] | None | NotGiven = NOT_GIVEN,
) -> Task
```

`task` [Task](inspect_ai.qmd#task)  
Task to adapt

`dataset` [Dataset](inspect_ai.dataset.qmd#dataset) \| Sequence\[[Sample](inspect_ai.dataset.qmd#sample)\] \| None \| NotGiven  
Dataset to evaluate

`setup` [Solver](inspect_ai.solver.qmd#solver) \| list\[[Solver](inspect_ai.solver.qmd#solver)\] \| None \| NotGiven  
Setup step (always run even when the main `solver` is replaced).

`solver` [Solver](inspect_ai.solver.qmd#solver) \| list\[[Solver](inspect_ai.solver.qmd#solver)\] \| NotGiven  
Solver or list of solvers. Defaults to generate(), a normal call to the
model.

`cleanup` Callable\[\[[TaskState](inspect_ai.solver.qmd#taskstate)\], Awaitable\[None\]\] \| None \| NotGiven  
Optional cleanup function for task. Called after all solvers have run
for each sample (including if an exception occurs during the run)

`scorer` [Scorer](inspect_ai.scorer.qmd#scorer) \| list\[[Scorer](inspect_ai.scorer.qmd#scorer)\] \| None \| NotGiven  
Scorer used to evaluate model output.

`metrics` list\[[Metric](inspect_ai.scorer.qmd#metric)\] \| dict\[str, list\[[Metric](inspect_ai.scorer.qmd#metric)\]\] \| None \| NotGiven  
Alternative metrics (overrides the metrics provided by the specified
scorer).

`model` str \| [Model](inspect_ai.model.qmd#model) \| NotGiven  
Default model for task (Optional, defaults to eval model).

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig) \| NotGiven  
Model generation config for default model (does not apply to model
roles)

`model_roles` dict\[str, str \| [Model](inspect_ai.model.qmd#model)\] \| NotGiven  
Named roles for use in `get_model()`.

`sandbox` SandboxEnvironmentType \| None \| NotGiven  
Sandbox environment type (or optionally a str or tuple with a shorthand
spec)

`approval` str \| list\[[ApprovalPolicy](inspect_ai.approval.qmd#approvalpolicy)\] \| None \| NotGiven  
Tool use approval policies. Either a path to an approval policy config
file or a list of approval policies. Defaults to no approval policy.

`epochs` int \| [Epochs](inspect_ai.qmd#epochs) \| None \| NotGiven  
Epochs to repeat samples for and optional score reducer function(s) used
to combine sample scores (defaults to “mean”)

`fail_on_error` bool \| float \| None \| NotGiven  
`True` to fail on first sample error (default); `False` to never fail on
sample errors; Value between 0 and 1 to fail if a proportion of total
samples fails. Value greater than 1 to fail eval if a count of samples
fails.

`message_limit` int \| None \| NotGiven  
Limit on total messages used for each sample.

`token_limit` int \| None \| NotGiven  
Limit on total tokens used for each sample.

`time_limit` int \| None \| NotGiven  
Limit on clock time (in seconds) for samples.

`working_limit` int \| None \| NotGiven  
Limit on working time (in seconds) for sample. Working time includes
model generation, tool calls, etc. but does not include time spent
waiting on retries or shared resources.

`name` str \| None \| NotGiven  
Task name. If not specified is automatically determined based on the
name of the task directory (or “task”) if its anonymous task
(e.g. created in a notebook and passed to eval() directly)

`version` int \| NotGiven  
Version of task (to distinguish evolutions of the task spec or breaking
changes to it)

`metadata` dict\[str, Any\] \| None \| NotGiven  
Additional metadata to associate with the task.

### Epochs

Task epochs.

Number of epochs to repeat samples over and optionally one or more
reducers used to combine scores from samples across epochs. If not
specified the “mean” score reducer is used.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ffa0b49015ef14412d66dff6d3a0a8b77e3edf70/src/inspect_ai/_eval/task/epochs.py#L4)

``` python
class Epochs
```

#### Methods

\_\_init\_\_  
Task epochs.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ffa0b49015ef14412d66dff6d3a0a8b77e3edf70/src/inspect_ai/_eval/task/epochs.py#L12)

``` python
def __init__(self, epochs: int, reducer: ScoreReducers | None = None) -> None
```

`epochs` int  
Number of epochs

`reducer` ScoreReducers \| None  
One or more reducers used to combine scores from samples across epochs
(defaults to “mean)

### TaskInfo

Task information (file, name, and attributes).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ffa0b49015ef14412d66dff6d3a0a8b77e3edf70/src/inspect_ai/_eval/task/task.py#L296)

``` python
class TaskInfo(BaseModel)
```

#### Attributes

`file` str  
File path where task was loaded from.

`name` str  
Task name (defaults to function name)

`attribs` dict\[str, Any\]  
Task attributes (arguments passed to `@task`)

### Tasks

One or more tasks.

Tasks to be evaluated. Many forms of task specification are supported
including directory names, task functions, task classes, and task
instances (a single task or list of tasks can be specified). None is a
request to read a task out of the current working directory.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ffa0b49015ef14412d66dff6d3a0a8b77e3edf70/src/inspect_ai/_eval/task/tasks.py#L6)

``` python
Tasks: TypeAlias = (
    str
    | PreviousTask
    | ResolvedTask
    | TaskInfo
    | Task
    | Callable[..., Task]
    | type[Task]
    | list[str]
    | list[PreviousTask]
    | list[ResolvedTask]
    | list[TaskInfo]
    | list[Task]
    | list[Callable[..., Task]]
    | list[type[Task]]
    | None
)
```

## View

### view

Run the Inspect View server.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ffa0b49015ef14412d66dff6d3a0a8b77e3edf70/src/inspect_ai/_view/view.py#L24)

``` python
def view(
    log_dir: str | None = None,
    recursive: bool = True,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_VIEW_PORT,
    authorization: str | None = None,
    log_level: str | None = None,
    fs_options: dict[str, Any] = {},
) -> None
```

`log_dir` str \| None  
Directory to view logs from.

`recursive` bool  
Recursively list files in `log_dir`.

`host` str  
Tcp/ip host (defaults to “127.0.0.1”).

`port` int  
Tcp/ip port (defaults to 7575).

`authorization` str \| None  
Validate requests by checking for this authorization header.

`log_level` str \| None  
Level for logging to the console: “debug”, “http”, “sandbox”, “info”,
“warning”, “error”, or “critical” (defaults to “warning”).

`fs_options` dict\[str, Any\]  
Additional arguments to pass through to the filesystem provider
(e.g. `S3FileSystem`). Use `{"anon": True }` if you are accessing a
public S3 bucket with no credentials.

## Decorators

### task

Decorator for registering tasks.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ffa0b49015ef14412d66dff6d3a0a8b77e3edf70/src/inspect_ai/_eval/registry.py#L97)

``` python
def task(*args: Any, name: str | None = None, **attribs: Any) -> Any
```

`*args` Any  
Function returning `Task` targeted by plain task decorator without
attributes (e.g. `@task`)

`name` str \| None  
Optional name for task. If the decorator has no name argument then the
name of the function will be used to automatically assign a name.

`**attribs` Any  
(dict\[str,Any\]): Additional task attributes.
