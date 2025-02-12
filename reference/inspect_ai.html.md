# inspect_ai


<!-- TOOD: Main reference page? -->
<!-- TODO: CLI reference -->

## Evaluation

### eval

Evaluate tasks using a Model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/25e3bdc2cc7c299d7c72c87579d469c472b4b6b9/src/inspect_ai/_eval/eval.py#L53)

``` python
def eval(
    tasks: Tasks,
    model: str | Model | list[str] | list[Model] | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str = dict(),
    task_args: dict[str, Any] | str = dict(),
    sandbox: SandboxEnvironmentType | None = None,
    sandbox_cleanup: bool | None = None,
    solver: Solver | list[Solver] | SolverSpec | None = None,
    tags: list[str] | None = None,
    trace: bool | None = None,
    display: DisplayType | None = None,
    approval: str | list[ApprovalPolicy] | None = None,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    limit: int | tuple[int, int] | None = None,
    sample_id: str | int | list[str | int] | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    debug_errors: bool | None = None,
    message_limit: int | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    log_samples: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
    score: bool = True,
    score_display: bool | None = None,
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[EvalLog]
```

`tasks` [Tasks](inspect_ai.qmd#tasks)  
Task(s) to evaluate. If None, attempt to evaluate a task in the current
working directory

`model` str \| [Model](inspect_ai.model.qmd#model) \| list\[str\] \| list\[[Model](inspect_ai.model.qmd#model)\] \| None  
Model(s) for evaluation. If not specified use the value of the
INSPECT_EVAL_MODEL environment variable.

`model_base_url` str \| None  
Base URL for communicating with the model API.

`model_args` dict\[str, Any\] \| str  
Model creation args (as a dictionary or as a path to a JSON or YAML
config file)

`task_args` dict\[str, Any\] \| str  
Task creation arguments (as a dictionary or as a path to a JSON or YAML
config file)

`sandbox` SandboxEnvironmentType \| None  
Sandbox environment type (or optionally a str or tuple with a shorthand
spec)

`sandbox_cleanup` bool \| None  
Cleanup sandbox environments after task completes (defaults to True)

`solver` [Solver](inspect_ai.solver.qmd#solver) \| list\[[Solver](inspect_ai.solver.qmd#solver)\] \| [SolverSpec](inspect_ai.solver.qmd#solverspec) \| None  
Alternative solver for task(s). Optional (uses task solver by default).

`tags` list\[str\] \| None  
Tags to associate with this evaluation run.

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

`sample_id` str \| int \| list\[str \| int\] \| None  
Evaluate specific sample(s) from the dataset.

`epochs` int \| [Epochs](inspect_ai.qmd#epochs) \| None  
Epochs to repeat samples for and optional score reducer function(s) used
to combine sample scores (defaults to “mean”)

`fail_on_error` bool \| float \| None  
`True` to fail on first sample error (default); `False` to never fail on
sample errors; Value between 0 and 1 to fail if a proportion of total
samples fails. Value greater than 1 to fail eval if a count of samples
fails.

`debug_errors` bool \| None  
Raise task errors (rather than logging them) so they can be debugged
(defaults to False).

`message_limit` int \| None  
Limit on total messages used for each sample.

`token_limit` int \| None  
Limit on total tokens used for each sample.

`time_limit` int \| None  
Limit on time (in seconds) for execution of each sample.

`max_samples` int \| None  
Maximum number of samples to run in parallel (default is
max_connections)

`max_tasks` int \| None  
Maximum number of tasks to run in parallel (default is 1)

`max_subprocesses` int \| None  
Maximum number of subprocesses to run in parallel (default is
os.cpu_count())

`max_sandboxes` int \| None  
Maximum number of sandboxes (per-provider) to run in parallel.

`log_samples` bool \| None  
Log detailed samples and scores (defaults to True)

`log_images` bool \| None  
Log base64 encoded version of images, even if specified as a filename or
URL (defaults to False)

`log_buffer` int \| None  
Number of samples to buffer before writing log file. If not specified,
an appropriate default for the format and filesystem is chosen (10 for
most all cases, 100 for JSON logs on remote filesystems).

`score` bool  
Score output (defaults to True)

`score_display` bool \| None  
Show scoring metrics in realtime (defaults to True)

`**kwargs` Unpack\[[GenerateConfigArgs](inspect_ai.model.qmd#generateconfigargs)\]  
Model generation options.

### eval_retry

Retry a previously failed evaluation task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/25e3bdc2cc7c299d7c72c87579d469c472b4b6b9/src/inspect_ai/_eval/eval.py#L472)

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
    debug_errors: bool | None = None,
    log_samples: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
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
Maximum number of tasks to run in parallel (default is 1)

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

`debug_errors` bool \| None  
Raise task errors (rather than logging them) so they can be debugged
(defaults to False).

`log_samples` bool \| None  
Log detailed samples and scores (defaults to True)

`log_images` bool \| None  
Log base64 encoded version of images, even if specified as a filename or
URL (defaults to False)

`log_buffer` int \| None  
Number of samples to buffer before writing log file. If not specified,
an appropriate default for the format and filesystem is chosen (10 for
most all cases, 100 for JSON logs on remote filesystems).

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/25e3bdc2cc7c299d7c72c87579d469c472b4b6b9/src/inspect_ai/_eval/evalset.py#L52)

``` python
def eval_set(
    tasks: Tasks,
    log_dir: str,
    retry_attempts: int | None = None,
    retry_wait: float | None = None,
    retry_connections: float | None = None,
    retry_cleanup: bool | None = None,
    model: str | Model | list[str] | list[Model] | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str = dict(),
    task_args: dict[str, Any] | str = dict(),
    sandbox: SandboxEnvironmentType | None = None,
    sandbox_cleanup: bool | None = None,
    solver: Solver | list[Solver] | SolverSpec | None = None,
    tags: list[str] | None = None,
    trace: bool | None = None,
    display: DisplayType | None = None,
    approval: str | list[ApprovalPolicy] | None = None,
    score: bool = True,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    limit: int | tuple[int, int] | None = None,
    sample_id: str | int | list[str | int] | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    debug_errors: bool | None = None,
    message_limit: int | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    log_samples: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
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

`model` str \| [Model](inspect_ai.model.qmd#model) \| list\[str\] \| list\[[Model](inspect_ai.model.qmd#model)\] \| None  
Model(s) for evaluation. If not specified use the value of the
INSPECT_EVAL_MODEL environment variable.

`model_base_url` str \| None  
Base URL for communicating with the model API.

`model_args` dict\[str, Any\] \| str  
Model creation args (as a dictionary or as a path to a JSON or YAML
config file)

`task_args` dict\[str, Any\] \| str  
Task creation arguments (as a dictionary or as a path to a JSON or YAML
config file)

`sandbox` SandboxEnvironmentType \| None  
Sandbox environment type (or optionally a str or tuple with a shorthand
spec)

`sandbox_cleanup` bool \| None  
Cleanup sandbox environments after task completes (defaults to True)

`solver` [Solver](inspect_ai.solver.qmd#solver) \| list\[[Solver](inspect_ai.solver.qmd#solver)\] \| [SolverSpec](inspect_ai.solver.qmd#solverspec) \| None  
Alternative solver(s) for evaluating task(s). ptional (uses task solver
by default).

`tags` list\[str\] \| None  
Tags to associate with this evaluation run.

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

`sample_id` str \| int \| list\[str \| int\] \| None  
Evaluate specific sample(s) from the dataset.

`epochs` int \| [Epochs](inspect_ai.qmd#epochs) \| None  
Epochs to repeat samples for and optional score reducer function(s) used
to combine sample scores (defaults to “mean”)

`fail_on_error` bool \| float \| None  
`True` to fail on first sample error (default); `False` to never fail on
sample errors; Value between 0 and 1 to fail if a proportion of total
samples fails. Value greater than 1 to fail eval if a count of samples
fails.

`debug_errors` bool \| None  
Raise task errors (rather than logging them) so they can be debugged
(defaults to False).

`message_limit` int \| None  
Limit on total messages used for each sample.

`token_limit` int \| None  
Limit on total tokens used for each sample.

`time_limit` int \| None  
Limit on time (in seconds) for execution of each sample.

`max_samples` int \| None  
Maximum number of samples to run in parallel (default is
max_connections)

`max_tasks` int \| None  
Maximum number of tasks to run in parallel (default is 1)

`max_subprocesses` int \| None  
Maximum number of subprocesses to run in parallel (default is
os.cpu_count())

`max_sandboxes` int \| None  
Maximum number of sandboxes (per-provider) to run in parallel.

`log_samples` bool \| None  
Log detailed samples and scores (defaults to True)

`log_images` bool \| None  
Log base64 encoded version of images, even if specified as a filename or
URL (defaults to False)

`log_buffer` int \| None  
Number of samples to buffer before writing log file. If not specified,
an appropriate default for the format and filesystem is chosen (10 for
most all cases, 100 for JSON logs on remote filesystems).

`bundle_dir` str \| None  
If specified, the log viewer and logs generated by this eval set will be
bundled into this directory.

`bundle_overwrite` bool  
Whether to overwrite files in the bundle_dir. (defaults to False).

`**kwargs` Unpack\[[GenerateConfigArgs](inspect_ai.model.qmd#generateconfigargs)\]  
Model generation options.

### score

Score an evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/25e3bdc2cc7c299d7c72c87579d469c472b4b6b9/src/inspect_ai/_eval/score.py#L31)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/25e3bdc2cc7c299d7c72c87579d469c472b4b6b9/src/inspect_ai/_eval/task/task.py#L38)

``` python
class Task
```

#### Methods

\_\_init\_\_  
Create a task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/25e3bdc2cc7c299d7c72c87579d469c472b4b6b9/src/inspect_ai/_eval/task/task.py#L44)

``` python
def __init__(
    self,
    dataset: Dataset | Sequence[Sample] | None = None,
    setup: Solver | list[Solver] | None = None,
    solver: Solver | list[Solver] = generate(),
    scorer: Scorer | list[Scorer] | None = None,
    metrics: list[Metric] | dict[str, list[Metric]] | None = None,
    config: GenerateConfig = GenerateConfig(),
    sandbox: SandboxEnvironmentType | None = None,
    approval: str | list[ApprovalPolicy] | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    message_limit: int | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    name: str | None = None,
    version: int = 0,
    metadata: dict[str, Any] | None = None,
    **kwargs: Unpack[TaskDeprecatedArgs],
) -> None
```

`dataset` [Dataset](inspect_ai.dataset.qmd#dataset) \| Sequence\[[Sample](inspect_ai.dataset.qmd#sample)\] \| None  
Dataset to evaluate

`setup` [Solver](inspect_ai.solver.qmd#solver) \| list\[[Solver](inspect_ai.solver.qmd#solver)\] \| None  
(Solver \| list\[Solver\] \| None): Setup step (always run even when the
main `solver` is replaced).

`solver` [Solver](inspect_ai.solver.qmd#solver) \| list\[[Solver](inspect_ai.solver.qmd#solver)\]  
(Solver \| list\[Solver\]): Solver or list of solvers. Defaults to
generate(), a normal call to the model.

`scorer` [Scorer](inspect_ai.scorer.qmd#scorer) \| list\[[Scorer](inspect_ai.scorer.qmd#scorer)\] \| None  
(Scorer \| list\[Scorer\] \| None): Scorer used to evaluate model
output.

`metrics` list\[[Metric](inspect_ai.scorer.qmd#metric)\] \| dict\[str, list\[[Metric](inspect_ai.scorer.qmd#metric)\]\] \| None  
Alternative metrics (overrides the metrics provided by the specified
scorer).

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Model generation config.

`sandbox` SandboxEnvironmentType \| None  
Sandbox environment type (or optionally a str or tuple with a shorthand
spec)

`approval` str \| list\[[ApprovalPolicy](inspect_ai.approval.qmd#approvalpolicy)\] \| None  
(str \| list\[ApprovalPolicy\] \| None): Tool use approval policies.
Either a path to an approval policy config file or a list of approval
policies. Defaults to no approval policy.

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
Limit on time (in seconds) for execution of each sample.

`name` str \| None  
(str \| None): Task name. If not specified is automatically determined
based on the name of the task directory (or “task”) if its anonymous
task (e.g. created in a notebook and passed to eval() directly)

`version` int  
(int): Version of task (to distinguish evolutions of the task spec or
breaking changes to it)

`metadata` dict\[str, Any\] \| None  
(dict\[str, Any\] \| None): Additional metadata to associate with the
task.

`**kwargs` Unpack\[TaskDeprecatedArgs\]  
Deprecated arguments.

### task_with

Task adapted with alternate values for one or more options.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/25e3bdc2cc7c299d7c72c87579d469c472b4b6b9/src/inspect_ai/_eval/task/task.py#L159)

``` python
def task_with(
    task: Task,
    *,
    dataset: Dataset | Sequence[Sample] | None | NotGiven = NOT_GIVEN,
    setup: Solver | list[Solver] | None | NotGiven = NOT_GIVEN,
    solver: Solver | list[Solver] | NotGiven = NOT_GIVEN,
    scorer: Scorer | list[Scorer] | None | NotGiven = NOT_GIVEN,
    metrics: list[Metric] | dict[str, list[Metric]] | None | NotGiven = NOT_GIVEN,
    config: GenerateConfig | NotGiven = NOT_GIVEN,
    sandbox: SandboxEnvironmentType | None | NotGiven = NOT_GIVEN,
    approval: str | list[ApprovalPolicy] | None | NotGiven = NOT_GIVEN,
    epochs: int | Epochs | None | NotGiven = NOT_GIVEN,
    fail_on_error: bool | float | None | NotGiven = NOT_GIVEN,
    message_limit: int | None | NotGiven = NOT_GIVEN,
    token_limit: int | None | NotGiven = NOT_GIVEN,
    time_limit: int | None | NotGiven = NOT_GIVEN,
    name: str | None | NotGiven = NOT_GIVEN,
    version: int | NotGiven = NOT_GIVEN,
    metadata: dict[str, Any] | None | NotGiven = NOT_GIVEN,
) -> Task
```

`task` [Task](inspect_ai.qmd#task)  
Task to adapt (it is deep copied prior to mutating options)

`dataset` [Dataset](inspect_ai.dataset.qmd#dataset) \| Sequence\[[Sample](inspect_ai.dataset.qmd#sample)\] \| None \| NotGiven  
Dataset to evaluate

`setup` [Solver](inspect_ai.solver.qmd#solver) \| list\[[Solver](inspect_ai.solver.qmd#solver)\] \| None \| NotGiven  
(Solver \| list\[Solver\] \| None): Setup step (always run even when the
main `solver` is replaced).

`solver` [Solver](inspect_ai.solver.qmd#solver) \| list\[[Solver](inspect_ai.solver.qmd#solver)\] \| NotGiven  
(Solver \| list\[Solver\]): Solver or list of solvers. Defaults to
generate(), a normal call to the model.

`scorer` [Scorer](inspect_ai.scorer.qmd#scorer) \| list\[[Scorer](inspect_ai.scorer.qmd#scorer)\] \| None \| NotGiven  
(Scorer \| list\[Scorer\] \| None): Scorer used to evaluate model
output.

`metrics` list\[[Metric](inspect_ai.scorer.qmd#metric)\] \| dict\[str, list\[[Metric](inspect_ai.scorer.qmd#metric)\]\] \| None \| NotGiven  
Alternative metrics (overrides the metrics provided by the specified
scorer).

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig) \| NotGiven  
Model generation config.

`sandbox` SandboxEnvironmentType \| None \| NotGiven  
Sandbox environment type (or optionally a str or tuple with a shorthand
spec)

`approval` str \| list\[[ApprovalPolicy](inspect_ai.approval.qmd#approvalpolicy)\] \| None \| NotGiven  
(str \| list\[ApprovalPolicy\] \| None): Tool use approval policies.
Either a path to an approval policy config file or a list of approval
policies. Defaults to no approval policy.

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
Limit on time (in seconds) for execution of each sample.

`name` str \| None \| NotGiven  
(str \| None): Task name. If not specified is automatically determined
based on the name of the task directory (or “task”) if its anonymous
task (e.g. created in a notebook and passed to eval() directly)

`version` int \| NotGiven  
(int): Version of task (to distinguish evolutions of the task spec or
breaking changes to it)

`metadata` dict\[str, Any\] \| None \| NotGiven  
(dict\[str, Any\] \| None): Additional metadata to associate with the
task.

### Epochs

Task epochs.

Number of epochs to repeat samples over and optionally one or more
reducers used to combine scores from samples across epochs. If not
specified the “mean” score reducer is used.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/25e3bdc2cc7c299d7c72c87579d469c472b4b6b9/src/inspect_ai/_eval/task/epochs.py#L4)

``` python
class Epochs
```

#### Methods

\_\_init\_\_  
Task epochs.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/25e3bdc2cc7c299d7c72c87579d469c472b4b6b9/src/inspect_ai/_eval/task/epochs.py#L12)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/25e3bdc2cc7c299d7c72c87579d469c472b4b6b9/src/inspect_ai/_eval/task/task.py#L259)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/25e3bdc2cc7c299d7c72c87579d469c472b4b6b9/src/inspect_ai/_eval/task/task.py#L290)

``` python
Tasks = (
    str
    | PreviousTask
    | TaskInfo
    | Task
    | Callable[..., Task]
    | type[Task]
    | list[str]
    | list[PreviousTask]
    | list[TaskInfo]
    | list[Task]
    | list[Callable[..., Task]]
    | list[type[Task]]
    | None
)
```

## Decorators

### task

Decorator for registering tasks.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/25e3bdc2cc7c299d7c72c87579d469c472b4b6b9/src/inspect_ai/_eval/registry.py#L107)

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
