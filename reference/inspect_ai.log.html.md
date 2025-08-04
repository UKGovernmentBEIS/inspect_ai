# inspect_ai.log


## Eval Log Files

### list_eval_logs

List all eval logs in a directory.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_file.py#L78)

``` python
def list_eval_logs(
    log_dir: str = os.environ.get("INSPECT_LOG_DIR", "./logs"),
    formats: list[Literal["eval", "json"]] | None = None,
    filter: Callable[[EvalLog], bool] | None = None,
    recursive: bool = True,
    descending: bool = True,
    fs_options: dict[str, Any] = {},
) -> list[EvalLogInfo]
```

`log_dir` str  
Log directory (defaults to INSPECT_LOG_DIR)

`formats` list\[Literal\['eval', 'json'\]\] \| None  
Formats to list (default to listing all formats)

`filter` Callable\[\[[EvalLog](inspect_ai.log.qmd#evallog)\], bool\] \| None  
Filter to limit logs returned. Note that the EvalLog instance passed to
the filter has only the EvalLog header (i.e. does not have the samples
or logging output).

`recursive` bool  
List log files recursively (defaults to True).

`descending` bool  
List in descending order.

`fs_options` dict\[str, Any\]  
Optional. Additional arguments to pass through to the filesystem
provider (e.g. `S3FileSystem`).

### write_eval_log

Write an evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_file.py#L126)

``` python
def write_eval_log(
    log: EvalLog,
    location: str | Path | FileInfo | None = None,
    format: Literal["eval", "json", "auto"] = "auto",
) -> None
```

`log` [EvalLog](inspect_ai.log.qmd#evallog)  
Evaluation log to write.

`location` str \| Path \| FileInfo \| None  
Location to write log to.

`format` Literal\['eval', 'json', 'auto'\]  
Write to format (defaults to ‘auto’ based on `log_file` extension)

### write_eval_log_async

Write an evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_file.py#L150)

``` python
async def write_eval_log_async(
    log: EvalLog,
    location: str | Path | FileInfo | None = None,
    format: Literal["eval", "json", "auto"] = "auto",
) -> None
```

`log` [EvalLog](inspect_ai.log.qmd#evallog)  
Evaluation log to write.

`location` str \| Path \| FileInfo \| None  
Location to write log to.

`format` Literal\['eval', 'json', 'auto'\]  
Write to format (defaults to ‘auto’ based on `log_file` extension)

### read_eval_log

Read an evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_file.py#L238)

``` python
def read_eval_log(
    log_file: str | Path | EvalLogInfo,
    header_only: bool = False,
    resolve_attachments: bool = False,
    format: Literal["eval", "json", "auto"] = "auto",
) -> EvalLog
```

`log_file` str \| Path \| [EvalLogInfo](inspect_ai.log.qmd#evalloginfo)  
Log file to read.

`header_only` bool  
Read only the header (i.e. exclude the “samples” and “logging” fields).
Defaults to False.

`resolve_attachments` bool  
Resolve attachments (e.g. images) to their full content.

`format` Literal\['eval', 'json', 'auto'\]  
Read from format (defaults to ‘auto’ based on `log_file` extension)

### read_eval_log_async

Read an evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_file.py#L276)

``` python
async def read_eval_log_async(
    log_file: str | Path | EvalLogInfo,
    header_only: bool = False,
    resolve_attachments: bool = False,
    format: Literal["eval", "json", "auto"] = "auto",
) -> EvalLog
```

`log_file` str \| Path \| [EvalLogInfo](inspect_ai.log.qmd#evalloginfo)  
Log file to read.

`header_only` bool  
Read only the header (i.e. exclude the “samples” and “logging” fields).
Defaults to False.

`resolve_attachments` bool  
Resolve attachments (e.g. images) to their full content.

`format` Literal\['eval', 'json', 'auto'\]  
Read from format (defaults to ‘auto’ based on `log_file` extension)

### read_eval_log_sample

Read a sample from an evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_file.py#L346)

``` python
def read_eval_log_sample(
    log_file: str | Path | EvalLogInfo,
    id: int | str | None = None,
    epoch: int = 1,
    uuid: str | None = None,
    resolve_attachments: bool = False,
    format: Literal["eval", "json", "auto"] = "auto",
) -> EvalSample
```

`log_file` str \| Path \| [EvalLogInfo](inspect_ai.log.qmd#evalloginfo)  
Log file to read.

`id` int \| str \| None  
Sample id to read. Optional, alternatively specify `uuid` (you must
specify `id` or `uuid`)

`epoch` int  
Epoch for sample id (defaults to 1)

`uuid` str \| None  
Sample uuid to read. Optional, alternatively specify `id` and `epoch`
(you must specify either `uuid` or `id`)

`resolve_attachments` bool  
Resolve attachments (e.g. images) to their full content.

`format` Literal\['eval', 'json', 'auto'\]  
Read from format (defaults to ‘auto’ based on `log_file` extension)

### read_eval_log_samples

Read all samples from an evaluation log incrementally.

Generator for samples in a log file. Only one sample at a time will be
read into memory and yielded to the caller.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_file.py#L497)

``` python
def read_eval_log_samples(
    log_file: str | Path | EvalLogInfo,
    all_samples_required: bool = True,
    resolve_attachments: bool = False,
    format: Literal["eval", "json", "auto"] = "auto",
) -> Generator[EvalSample, None, None]
```

`log_file` str \| Path \| [EvalLogInfo](inspect_ai.log.qmd#evalloginfo)  
Log file to read.

`all_samples_required` bool  
All samples must be included in the file or an IndexError is thrown.

`resolve_attachments` bool  
Resolve attachments (e.g. images) to their full content.

`format` Literal\['eval', 'json', 'auto'\]  
Read from format (defaults to ‘auto’ based on `log_file` extension)

### read_eval_log_sample_summaries

Read sample summaries from an eval log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_file.py#L442)

``` python
def read_eval_log_sample_summaries(
    log_file: str | Path | EvalLogInfo,
    format: Literal["eval", "json", "auto"] = "auto",
) -> list[EvalSampleSummary]
```

`log_file` str \| Path \| [EvalLogInfo](inspect_ai.log.qmd#evalloginfo)  
Log file to read.

`format` Literal\['eval', 'json', 'auto'\]  
Read from format (defaults to ‘auto’ based on `log_file` extension)

### convert_eval_logs

Convert between log file formats.

Convert log file(s) to a target format. If a file is already in the
target format it will just be copied to the output dir.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_convert.py#L13)

``` python
def convert_eval_logs(
    path: str, to: Literal["eval", "json"], output_dir: str, overwrite: bool = False
) -> None
```

`path` str  
Path to source log file(s). Should be either a single log file or a
directory containing log files.

`to` Literal\['eval', 'json'\]  
Format to convert to. If a file is already in the target format it will
just be copied to the output dir.

`output_dir` str  
Output directory to write converted log file(s) to.

`overwrite` bool  
Overwrite existing log files (defaults to `False`, raising an error if
the output file path already exists).

### bundle_log_dir

Bundle a log_dir into a statically deployable viewer

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_bundle.py#L23)

``` python
def bundle_log_dir(
    log_dir: str | None = None,
    output_dir: str | None = None,
    overwrite: bool = False,
    fs_options: dict[str, Any] = {},
) -> None
```

`log_dir` str \| None  
(str \| None): The log_dir to bundle

`output_dir` str \| None  
(str \| None): The directory to place bundled output. If no directory is
specified, the env variable `INSPECT_VIEW_BUNDLE_OUTPUT_DIR` will be
used.

`overwrite` bool  
(bool): Optional. Whether to overwrite files in the output directory.
Defaults to False.

`fs_options` dict\[str, Any\]  
Optional. Additional arguments to pass through to the filesystem
provider (e.g. `S3FileSystem`).

### write_log_dir_manifest

Write a manifest for a log directory.

A log directory manifest is a dictionary of EvalLog headers (EvalLog w/o
samples) keyed by log file names (names are relative to the log
directory)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_file.py#L191)

``` python
def write_log_dir_manifest(
    log_dir: str,
    *,
    filename: str = "logs.json",
    output_dir: str | None = None,
    fs_options: dict[str, Any] = {},
) -> None
```

`log_dir` str  
Log directory to write manifest for.

`filename` str  
Manifest filename (defaults to “logs.json”)

`output_dir` str \| None  
Output directory for manifest (defaults to log_dir)

`fs_options` dict\[str, Any\]  
Optional. Additional arguments to pass through to the filesystem
provider (e.g. `S3FileSystem`).

### retryable_eval_logs

Extract the list of retryable logs from a list of logs.

Retryable logs are logs with status “error” or “cancelled” that do not
have a corresponding log with status “success” (indicating they were
subsequently retried and completed)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_retry.py#L10)

``` python
def retryable_eval_logs(logs: list[EvalLogInfo]) -> list[EvalLogInfo]
```

`logs` list\[[EvalLogInfo](inspect_ai.log.qmd#evalloginfo)\]  
List of logs to examine.

### EvalLogInfo

File info and task identifiers for eval log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_file.py#L31)

``` python
class EvalLogInfo(BaseModel)
```

#### Attributes

`name` str  
Name of file.

`type` str  
Type of file (file or directory)

`size` int  
File size in bytes.

`mtime` float \| None  
File modification time (None if the file is a directory on S3).

`task` str  
Task name.

`task_id` str  
Task id.

`suffix` str \| None  
Log file suffix (e.g. “-scored”)

## Eval Log API

### EvalLog

Evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L916)

``` python
class EvalLog(BaseModel)
```

#### Attributes

`version` int  
Eval log file format version.

`status` Literal\['started', 'success', 'cancelled', 'error'\]  
Status of evaluation (did it succeed or fail).

`eval` [EvalSpec](inspect_ai.log.qmd#evalspec)  
Eval identity and configuration.

`plan` [EvalPlan](inspect_ai.log.qmd#evalplan)  
Eval plan (solvers and config)

`results` [EvalResults](inspect_ai.analysis.qmd#evalresults) \| None  
Eval results (scores and metrics).

`stats` [EvalStats](inspect_ai.log.qmd#evalstats)  
Eval stats (runtime, model usage)

`error` [EvalError](inspect_ai.log.qmd#evalerror) \| None  
Error that halted eval (if status==“error”)

`samples` list\[[EvalSample](inspect_ai.log.qmd#evalsample)\] \| None  
Samples processed by eval.

`reductions` list\[[EvalSampleReductions](inspect_ai.log.qmd#evalsamplereductions)\] \| None  
Reduced sample values

`location` str  
Location that the log file was read from.

### EvalSpec

Eval target and configuration.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L689)

``` python
class EvalSpec(BaseModel)
```

#### Attributes

`eval_id` str  
Globally unique id for eval.

`run_id` str  
Unique run id

`created` str  
Time created.

`task` str  
Task name.

`task_id` str  
Unique task id.

`task_version` int \| str  
Task version.

`task_file` str \| None  
Task source file.

`task_display_name` str \| None  
Task display name.

`task_registry_name` str \| None  
Task registry name.

`task_attribs` dict\[str, Any\]  
Attributes of the @task decorator.

`task_args` dict\[str, Any\]  
Arguments used for invoking the task (including defaults).

`task_args_passed` dict\[str, Any\]  
Arguments explicitly passed by caller for invoking the task.

`solver` str \| None  
Solver name.

`solver_args` dict\[str, Any\] \| None  
Arguments used for invoking the solver.

`tags` list\[str\] \| None  
Tags associated with evaluation run.

`dataset` [EvalDataset](inspect_ai.log.qmd#evaldataset)  
Dataset used for eval.

`sandbox` SandboxEnvironmentSpec \| None  
Sandbox environment type and optional config file.

`model` str  
Model used for eval.

`model_generate_config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Generate config specified for model instance.

`model_base_url` str \| None  
Optional override of model base url

`model_args` dict\[str, Any\]  
Model specific arguments.

`model_roles` dict\[str, [EvalModelConfig](inspect_ai.log.qmd#evalmodelconfig)\] \| None  
Model roles.

`config` [EvalConfig](inspect_ai.log.qmd#evalconfig)  
Configuration values for eval.

`revision` [EvalRevision](inspect_ai.log.qmd#evalrevision) \| None  
Source revision of eval.

`packages` dict\[str, str\]  
Package versions for eval.

`metadata` dict\[str, Any\] \| None  
Additional eval metadata.

`scorers` list\[EvalScorer\] \| None  
Scorers and args for this eval

`metrics` list\[EvalMetricDefinition\] \| dict\[str, list\[EvalMetricDefinition\]\] \| None  
metrics and args for this eval

### EvalDataset

Dataset used for evaluation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L617)

``` python
class EvalDataset(BaseModel)
```

#### Attributes

`name` str \| None  
Dataset name.

`location` str \| None  
Dataset location (file path or remote URL)

`samples` int \| None  
Number of samples in the dataset.

`sample_ids` list\[str\] \| list\[int\] \| list\[str \| int\] \| None  
IDs of samples in the dataset.

`shuffled` bool \| None  
Was the dataset shuffled after reading.

### EvalConfig

Configuration used for evaluation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L67)

``` python
class EvalConfig(BaseModel)
```

#### Attributes

`limit` int \| tuple\[int, int\] \| None  
Sample limit (number of samples or range of samples).

`sample_id` str \| int \| list\[str\] \| list\[int\] \| list\[str \| int\] \| None  
Evaluate specific sample(s).

`sample_shuffle` bool \| int \| None  
Shuffle order of samples.

`epochs` int \| None  
Number of epochs to run samples over.

`epochs_reducer` list\[str\] \| None  
Reducers for aggregating per-sample scores.

`approval` ApprovalPolicyConfig \| None  
Approval policy for tool use.

`fail_on_error` bool \| float \| None  
Fail eval when sample errors occur.

`True` to fail on first sample error (default); `False` to never fail on
sample errors; Value between 0 and 1 to fail if a proportion of total
samples fails. Value greater than 1 to fail eval if a count of samples
fails.

`retry_on_error` int \| None  
Number of times to retry samples if they encounter errors.

`message_limit` int \| None  
Maximum messages to allow per sample.

`token_limit` int \| None  
Maximum tokens usage per sample.

`time_limit` int \| None  
Maximum clock time per sample.

`working_limit` int \| None  
Meximum working time per sample.

`max_samples` int \| None  
Maximum number of samples to run in parallel.

`max_tasks` int \| None  
Maximum number of tasks to run in parallel.

`max_subprocesses` int \| None  
Maximum number of subprocesses to run concurrently.

`max_sandboxes` int \| None  
Maximum number of sandboxes to run concurrently.

`sandbox_cleanup` bool \| None  
Cleanup sandbox environments after task completes.

`log_samples` bool \| None  
Log detailed information on each sample.

`log_realtime` bool \| None  
Log events in realtime (enables live viewing of samples in inspect
view).

`log_images` bool \| None  
Log base64 encoded versions of images.

`log_buffer` int \| None  
Number of samples to buffer before writing log file.

`log_shared` int \| None  
Interval (in seconds) for syncing sample events to log directory.

`score_display` bool \| None  
Display scoring metrics realtime.

### EvalModelConfig

Model config.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L673)

``` python
class EvalModelConfig(BaseModel)
```

#### Attributes

`model` str  
Model name.

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Generate config

`base_url` str \| None  
Model base url.

`args` dict\[str, Any\]  
Model specific arguments.

### EvalRevision

Git revision for evaluation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L660)

``` python
class EvalRevision(BaseModel)
```

#### Attributes

`type` Literal\['git'\]  
Type of revision (currently only “git”)

`origin` str  
Revision origin server

`commit` str  
Revision commit.

### EvalPlan

Plan (solvers) used in evaluation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L453)

``` python
class EvalPlan(BaseModel)
```

#### Attributes

`name` str  
Plan name.

`steps` list\[[EvalPlanStep](inspect_ai.log.qmd#evalplanstep)\]  
Steps in plan.

`finish` [EvalPlanStep](inspect_ai.log.qmd#evalplanstep) \| None  
Step to always run at the end.

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Generation config.

### EvalPlanStep

Solver step.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L443)

``` python
class EvalPlanStep(BaseModel)
```

#### Attributes

`solver` str  
Name of solver.

`params` dict\[str, Any\]  
Parameters used to instantiate solver.

### EvalResults

Scoring results from evaluation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L533)

``` python
class EvalResults(BaseModel)
```

#### Attributes

`total_samples` int  
Total samples in eval (dataset samples \* epochs)

`completed_samples` int  
Samples completed without error.

Will be equal to total_samples except when –fail-on-error is enabled.

`scores` list\[[EvalScore](inspect_ai.log.qmd#evalscore)\]  
Scorers used to compute results

`metadata` dict\[str, Any\] \| None  
Additional results metadata.

`sample_reductions` list\[[EvalSampleReductions](inspect_ai.log.qmd#evalsamplereductions)\] \| None  
List of per sample scores reduced across epochs

### EvalScore

Score for evaluation task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L485)

``` python
class EvalScore(BaseModel)
```

#### Attributes

`name` str  
Score name.

`scorer` str  
Scorer name.

`reducer` str \| None  
Reducer name.

`scored_samples` int \| None  
Number of samples scored by this scorer.

`unscored_samples` int \| None  
Number of samples not scored by this scorer.

`params` dict\[str, Any\]  
Parameters specified when creating scorer.

`metrics` dict\[str, [EvalMetric](inspect_ai.log.qmd#evalmetric)\]  
Metrics computed for this scorer.

`metadata` dict\[str, Any\] \| None  
Additional scorer metadata.

### EvalMetric

Metric for evaluation score.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L469)

``` python
class EvalMetric(BaseModel)
```

#### Attributes

`name` str  
Metric name.

`value` int \| float  
Metric value.

`params` dict\[str, Any\]  
Params specified when creating metric.

`metadata` dict\[str, Any\] \| None  
Additional metadata associated with metric.

### EvalSampleReductions

Score reductions.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L520)

``` python
class EvalSampleReductions(BaseModel)
```

#### Attributes

`scorer` str  
Name the of scorer

`reducer` str \| None  
Name the of reducer

`samples` list\[[EvalSampleScore](inspect_ai.log.qmd#evalsamplescore)\]  
List of reduced scores

### EvalStats

Timing and usage statistics.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L900)

``` python
class EvalStats(BaseModel)
```

#### Attributes

`started_at` str  
Evaluation start time.

`completed_at` str  
Evaluation completion time.

`model_usage` dict\[str, [ModelUsage](inspect_ai.model.qmd#modelusage)\]  
Model token usage for evaluation.

### EvalError

Eval error details.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/_util/error.py#L11)

``` python
class EvalError(BaseModel)
```

#### Attributes

`message` str  
Error message.

`traceback` str  
Error traceback.

`traceback_ansi` str  
Error traceback with ANSI color codes.

### EvalSample

Sample from evaluation task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L240)

``` python
class EvalSample(BaseModel)
```

#### Attributes

`id` int \| str  
Unique id for sample.

`epoch` int  
Epoch number for sample.

`input` str \| list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Sample input.

`choices` list\[str\] \| None  
Sample choices.

`target` str \| list\[str\]  
Sample target value(s)

`sandbox` SandboxEnvironmentSpec \| None  
Sandbox environment type and optional config file.

`files` list\[str\] \| None  
Files that go along with the sample (copied to SandboxEnvironment)

`setup` str \| None  
Setup script to run for sample (run within default SandboxEnvironment).

`messages` list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Chat conversation history for sample.

`output` [ModelOutput](inspect_ai.model.qmd#modeloutput)  
Model output from sample.

`scores` dict\[str, [Score](inspect_ai.scorer.qmd#score)\] \| None  
Scores for sample.

`metadata` dict\[str, Any\]  
Additional sample metadata.

`store` dict\[str, Any\]  
State at end of sample execution.

`events` list\[[Event](inspect_ai.log.qmd#event)\]  
Events that occurred during sample execution.

`model_usage` dict\[str, [ModelUsage](inspect_ai.model.qmd#modelusage)\]  
Model token usage for sample.

`total_time` float \| None  
Total time that the sample was running.

`working_time` float \| None  
Time spent working (model generation, sandbox calls, etc.)

`uuid` str \| None  
Globally unique identifier for sample run (exists for samples created in
Inspect \>= 0.3.70)

`error` [EvalError](inspect_ai.log.qmd#evalerror) \| None  
Error that halted sample.

`error_retries` list\[[EvalError](inspect_ai.log.qmd#evalerror)\] \| None  
Errors that were retried for this sample.

`attachments` dict\[str, str\]  
Attachments referenced from messages and events.

Resolve attachments for a sample (replacing <attachment://>\* references
with attachment content) by passing `resolve_attachments=True` to log
reading functions.

`limit` [EvalSampleLimit](inspect_ai.log.qmd#evalsamplelimit) \| None  
The limit that halted the sample

#### Methods

metadata_as  
Pydantic model interface to metadata.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L279)

``` python
def metadata_as(self, metadata_cls: Type[MT]) -> MT
```

`metadata_cls` Type\[MT\]  
Pydantic model type

store_as  
Pydantic model interface to the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L293)

``` python
def store_as(self, model_cls: Type[SMT], instance: str | None = None) -> SMT
```

`model_cls` Type\[SMT\]  
Pydantic model type (must derive from StoreModel)

`instance` str \| None  
Optional instances name for store (enables multiple instances of a given
StoreModel type within a single sample)

summary  
Summary of sample.

The summary excludes potentially large fields like messages, output,
events, store, and metadata so that it is always fast to load.

If there are images, audio, or video in the input, they are replaced
with a placeholder.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L350)

``` python
def summary(self) -> EvalSampleSummary
```

### EvalSampleSummary

Summary information (including scoring) for a sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L176)

``` python
class EvalSampleSummary(BaseModel)
```

#### Attributes

`id` int \| str  
Unique id for sample.

`epoch` int  
Epoch number for sample.

`input` str \| list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Sample input (text inputs only).

`target` str \| list\[str\]  
Sample target value(s)

`metadata` dict\[str, Any\]  
Sample metadata (scalar types only, strings truncated to 1k).

`scores` dict\[str, [Score](inspect_ai.scorer.qmd#score)\] \| None  
Scores for sample (score values only, no answers, explanations, or
metadata).

`model_usage` dict\[str, [ModelUsage](inspect_ai.model.qmd#modelusage)\]  
Model token usage for sample.

`total_time` float \| None  
Total time that the sample was running.

`working_time` float \| None  
Time spent working (model generation, sandbox calls, etc.)

`uuid` str \| None  
Globally unique identifier for sample run (exists for samples created in
Inspect \>= 0.3.70)

`error` str \| None  
Error that halted sample.

`limit` str \| None  
Limit that halted the sample

`retries` int \| None  
Number of retries for the sample.

`completed` bool  
Is the sample complete.

### EvalSampleLimit

Limit encountered by sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L164)

``` python
class EvalSampleLimit(BaseModel)
```

#### Attributes

`type` Literal\['context', 'time', 'working', 'message', 'token', 'operator', 'custom'\]  
The type of limit

`limit` float  
The limit value

### EvalSampleReductions

Score reductions.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L520)

``` python
class EvalSampleReductions(BaseModel)
```

#### Attributes

`scorer` str  
Name the of scorer

`reducer` str \| None  
Name the of reducer

`samples` list\[[EvalSampleScore](inspect_ai.log.qmd#evalsamplescore)\]  
List of reduced scores

### EvalSampleScore

Score and sample_id scored.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_log.py#L513)

``` python
class EvalSampleScore(Score)
```

#### Attributes

`sample_id` str \| int \| None  
Sample ID.

## Transcript API

### transcript

Get the current `Transcript`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L603)

``` python
def transcript() -> Transcript
```

### Transcript

Transcript of events.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L543)

``` python
class Transcript
```

#### Methods

info  
Add an `InfoEvent` to the transcript.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L552)

``` python
def info(self, data: JsonValue, *, source: str | None = None) -> None
```

`data` JsonValue  
Data associated with the event.

`source` str \| None  
Optional event source.

step  
Context manager for recording StepEvent.

The `step()` context manager is deprecated and will be removed in a
future version. Please use the `span()` context manager instead.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L561)

``` python
@contextlib.contextmanager
def step(self, name: str, type: str | None = None) -> Iterator[None]
```

`name` str  
Step name.

`type` str \| None  
Optional step type.

### Event

Event in a transcript.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L518)

``` python
Event: TypeAlias = Union[
    SampleInitEvent
    | SampleLimitEvent
    | SandboxEvent
    | StateEvent
    | StoreEvent
    | ModelEvent
    | ToolEvent
    | SandboxEvent
    | ApprovalEvent
    | InputEvent
    | ScoreEvent
    | ErrorEvent
    | LoggerEvent
    | InfoEvent
    | SpanBeginEvent
    | SpanEndEvent
    | StepEvent
    | SubtaskEvent,
]
```

### event_tree

Build a tree representation of a sequence of events.

Organize events heirarchially into event spans.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_tree.py#L42)

``` python
def event_tree(events: Sequence[Event]) -> EventTree
```

`events` Sequence\[[Event](inspect_ai.log.qmd#event)\]  
Sequence of `Event`.

### event_sequence

Flatten a span forest back into a properly ordered seqeunce.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_tree.py#L93)

``` python
def event_sequence(tree: EventTree) -> Iterable[Event]
```

`tree` [EventTree](inspect_ai.log.qmd#eventtree)  
Event tree

### EventTree

Tree of events (has invividual events and event spans).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_tree.py#L12)

``` python
EventTree: TypeAlias = list[EventNode]
```

### EventNode

Node in an event tree.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_tree.py#L9)

``` python
EventNode: TypeAlias = "SpanNode" | Event
```

### SpanNode

Event tree node representing a span of events.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_tree.py#L16)

``` python
@dataclass
class SpanNode
```

#### Attributes

`id` str  
Span id.

`parent_id` str \| None  
Parent span id.

`type` str \| None  
Optional ‘type’ field for span.

`name` str  
Span name.

`begin` [SpanBeginEvent](inspect_ai.log.qmd#spanbeginevent)  
Span begin event.

`end` [SpanEndEvent](inspect_ai.log.qmd#spanendevent) \| None  
Span end event (if any).

`children` list\[[EventNode](inspect_ai.log.qmd#eventnode)\]  
Children in the span.

### SampleInitEvent

Beginning of processing a Sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L90)

``` python
class SampleInitEvent(BaseEvent)
```

#### Attributes

`event` Literal\['sample_init'\]  
Event type.

`sample` [Sample](inspect_ai.dataset.qmd#sample)  
Sample.

`state` JsonValue  
Initial state.

### SampleLimitEvent

The sample was unable to finish processing due to a limit

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L103)

``` python
class SampleLimitEvent(BaseEvent)
```

#### Attributes

`event` Literal\['sample_limit'\]  
Event type.

`type` Literal\['message', 'time', 'working', 'token', 'operator', 'custom'\]  
Type of limit that halted processing

`message` str  
A message associated with this limit

`limit` float \| None  
The limit value (if any)

### StateEvent

Change to the current `TaskState`

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L129)

``` python
class StateEvent(BaseEvent)
```

#### Attributes

`event` Literal\['state'\]  
Event type.

`changes` list\[JsonChange\]  
List of changes to the `TaskState`

### StoreEvent

Change to data within the current `Store`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L119)

``` python
class StoreEvent(BaseEvent)
```

#### Attributes

`event` Literal\['store'\]  
Event type.

`changes` list\[JsonChange\]  
List of changes to the `Store`.

### ModelEvent

Call to a language model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L139)

``` python
class ModelEvent(BaseEvent)
```

#### Attributes

`event` Literal\['model'\]  
Event type.

`model` str  
Model name.

`role` str \| None  
Model role.

`input` list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Model input (list of messages).

`tools` list\[[ToolInfo](inspect_ai.tool.qmd#toolinfo)\]  
Tools available to the model.

`tool_choice` [ToolChoice](inspect_ai.tool.qmd#toolchoice)  
Directive to the model which tools to prefer.

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Generate config used for call to model.

`output` [ModelOutput](inspect_ai.model.qmd#modeloutput)  
Output from model.

`retries` int \| None  
Retries for the model API request.

`error` str \| None  
Error which occurred during model call.

`cache` Literal\['read', 'write'\] \| None  
Was this a cache read or write.

`call` [ModelCall](inspect_ai.model.qmd#modelcall) \| None  
Raw call made to model API.

`completed` datetime \| None  
Time that model call completed (see `timestamp` for started)

`working_time` float \| None  
working time for model call that succeeded (i.e. was not retried).

### ToolEvent

Call to a tool.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L191)

``` python
class ToolEvent(BaseEvent)
```

#### Attributes

`event` Literal\['tool'\]  
Event type.

`type` Literal\['function'\]  
Type of tool call (currently only ‘function’)

`id` str  
Unique identifier for tool call.

`function` str  
Function called.

`arguments` dict\[str, JsonValue\]  
Arguments to function.

`internal` JsonValue \| None  
Model provider specific payload - typically used to aid transformation
back to model types.

`view` ToolCallContent \| None  
Custom view of tool call input.

`result` [ToolResult](inspect_ai.tool.qmd#toolresult)  
Function return value.

`truncated` tuple\[int, int\] \| None  
Bytes truncated (from,to) if truncation occurred

`error` [ToolCallError](inspect_ai.tool.qmd#toolcallerror) \| None  
Error that occurred during tool call.

`completed` datetime \| None  
Time that tool call completed (see `timestamp` for started)

`working_time` float \| None  
Working time for tool call (i.e. time not spent waiting on semaphores).

`agent` str \| None  
Name of agent if the tool call was an agent handoff.

`failed` bool \| None  
Did the tool call fail with a hard error?.

`message_id` str \| None  
Id of ChatMessageTool associated with this event.

`cancelled` bool  
Was the task cancelled?

### SandboxEvent

Sandbox execution or I/O

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L302)

``` python
class SandboxEvent(BaseEvent)
```

#### Attributes

`event` Literal\['sandbox'\]  
Event type

`action` Literal\['exec', 'read_file', 'write_file'\]  
Sandbox action

`cmd` str \| None  
Command (for exec)

`options` dict\[str, JsonValue\] \| None  
Options (for exec)

`file` str \| None  
File (for read_file and write_file)

`input` str \| None  
Input (for cmd and write_file). Truncated to 100 lines.

`result` int \| None  
Result (for exec)

`output` str \| None  
Output (for exec and read_file). Truncated to 100 lines.

`completed` datetime \| None  
Time that sandbox action completed (see `timestamp` for started)

### ApprovalEvent

Tool approval.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L339)

``` python
class ApprovalEvent(BaseEvent)
```

#### Attributes

`event` Literal\['approval'\]  
Event type

`message` str  
Message generated by model along with tool call.

`call` ToolCall  
Tool call being approved.

`view` ToolCallView \| None  
View presented for approval.

`approver` str  
Aprover name.

`decision` Literal\['approve', 'modify', 'reject', 'escalate', 'terminate'\]  
Decision of approver.

`modified` ToolCall \| None  
Modified tool call for decision ‘modify’.

`explanation` str \| None  
Explanation for decision.

### InputEvent

Input screen interaction.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L367)

``` python
class InputEvent(BaseEvent)
```

#### Attributes

`event` Literal\['input'\]  
Event type.

`input` str  
Input interaction (plain text).

`input_ansi` str  
Input interaction (ANSI).

### ErrorEvent

Event with sample error.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L403)

``` python
class ErrorEvent(BaseEvent)
```

#### Attributes

`event` Literal\['error'\]  
Event type.

`error` [EvalError](inspect_ai.log.qmd#evalerror)  
Sample error

### LoggerEvent

Log message recorded with Python logger.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L380)

``` python
class LoggerEvent(BaseEvent)
```

#### Attributes

`event` Literal\['logger'\]  
Event type.

`message` [LoggingMessage](inspect_ai.log.qmd#loggingmessage)  
Logging message

### LoggingLevel

Logging level.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_message.py#L7)

``` python
LoggingLevel = Literal[
    "debug", "trace", "http", "sandbox", "info", "warning", "error", "critical"
]
```

### LoggingMessage

Message written to Python log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_message.py#L13)

``` python
class LoggingMessage(BaseModel)
```

#### Attributes

`name` str \| None  
Logger name (e.g. ‘httpx’)

`level` [LoggingLevel](inspect_ai.log.qmd#logginglevel)  
Logging level.

`message` str  
Log message.

`created` float  
Message created time.

`filename` str  
Logged from filename.

`module` str  
Logged from module.

`lineno` int  
Logged from line number.

### InfoEvent

Event with custom info/data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L390)

``` python
class InfoEvent(BaseEvent)
```

#### Attributes

`event` Literal\['info'\]  
Event type.

`source` str \| None  
Optional source for info event.

`data` JsonValue  
Data provided with event.

### SpanBeginEvent

Mark the beginning of a transcript span.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L433)

``` python
class SpanBeginEvent(BaseEvent)
```

#### Attributes

`event` Literal\['span_begin'\]  
Event type.

`id` str  
Unique identifier for span.

`parent_id` str \| None  
Identifier for parent span.

`type` str \| None  
Optional ‘type’ field for span.

`name` str  
Span name.

### SpanEndEvent

Mark the end of a transcript span.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L452)

``` python
class SpanEndEvent(BaseEvent)
```

#### Attributes

`event` Literal\['span_end'\]  
Event type.

`id` str  
Unique identifier for span.

### SubtaskEvent

Subtask spawned.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/log/_transcript.py#L478)

``` python
class SubtaskEvent(BaseEvent)
```

#### Attributes

`event` Literal\['subtask'\]  
Event type.

`name` str  
Name of subtask function.

`type` str \| None  
Type of subtask

`input` dict\[str, Any\]  
Subtask function inputs.

`result` Any  
Subtask function result.

`completed` datetime \| None  
Time that subtask completed (see `timestamp` for started)

`working_time` float \| None  
Working time for subtask (i.e. time not spent waiting on semaphores or
model retries).
