# inspect_ai.log


## Eval Logs

### list_eval_logs

List all eval logs in a directory.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_file.py#L87)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_file.py#L135)

``` python
def write_eval_log(
    log: EvalLog,
    location: str | Path | FileInfo | None = None,
    format: Literal["eval", "json", "auto"] = "auto",
    if_match_etag: str | None = None,
) -> None
```

`log` [EvalLog](inspect_ai.log.qmd#evallog)  
Evaluation log to write.

`location` str \| Path \| FileInfo \| None  
Location to write log to.

`format` Literal\['eval', 'json', 'auto'\]  
Write to format (defaults to ‘auto’ based on `log_file` extension)

`if_match_etag` str \| None  
ETag for conditional write. If provided and writing to S3, will only
write if the current ETag matches.

### write_eval_log_async

Write an evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_file.py#L166)

``` python
async def write_eval_log_async(
    log: EvalLog,
    location: str | Path | FileInfo | None = None,
    format: Literal["eval", "json", "auto"] = "auto",
    if_match_etag: str | None = None,
) -> None
```

`log` [EvalLog](inspect_ai.log.qmd#evallog)  
Evaluation log to write.

`location` str \| Path \| FileInfo \| None  
Location to write log to.

`format` Literal\['eval', 'json', 'auto'\]  
Write to format (defaults to ‘auto’ based on `log_file` extension)

`if_match_etag` str \| None  
ETag for conditional write. If provided and writing to S3, will only
write if the current ETag matches.

### read_eval_log

Read an evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_file.py#L251)

``` python
def read_eval_log(
    log_file: str | Path | EvalLogInfo | IO[bytes],
    header_only: bool = False,
    resolve_attachments: bool | Literal["full", "core"] = False,
    format: Literal["eval", "json", "auto"] = "auto",
) -> EvalLog
```

`log_file` str \| Path \| [EvalLogInfo](inspect_ai.log.qmd#evalloginfo) \| IO\[bytes\]  
Log file to read. When providing IO\[bytes\], the returned EvalLog will
have an empty location (which can be set manually if needed).

`header_only` bool  
Read only the header (i.e. exclude the “samples” and “logging” fields).
Defaults to False.

`resolve_attachments` bool \| Literal\['full', 'core'\]  
Resolve attachments (duplicated content blocks) to their full content.

`format` Literal\['eval', 'json', 'auto'\]  
Read from format (defaults to ‘auto’ based on `log_file` extension).

### read_eval_log_async

Read an evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_file.py#L291)

``` python
async def read_eval_log_async(
    log_file: str | Path | EvalLogInfo | IO[bytes],
    header_only: bool = False,
    resolve_attachments: bool | Literal["full", "core"] = False,
    format: Literal["eval", "json", "auto"] = "auto",
) -> EvalLog
```

`log_file` str \| Path \| [EvalLogInfo](inspect_ai.log.qmd#evalloginfo) \| IO\[bytes\]  
Log file to read. When providing IO\[bytes\], the returned EvalLog will
have an empty location (which can be set manually if needed).

`header_only` bool  
Read only the header (i.e. exclude the “samples” and “logging” fields).
Defaults to False.

`resolve_attachments` bool \| Literal\['full', 'core'\]  
Resolve attachments (duplicated content blocks) to their full content.

`format` Literal\['eval', 'json', 'auto'\]  
Read from format (defaults to ‘auto’ based on `log_file` extension).

### read_eval_log_sample

Read a sample from an evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_file.py#L399)

``` python
def read_eval_log_sample(
    log_file: str | Path | EvalLogInfo,
    id: int | str | None = None,
    epoch: int = 1,
    uuid: str | None = None,
    resolve_attachments: bool | Literal["full", "core"] = False,
    format: Literal["eval", "json", "auto"] = "auto",
    exclude_fields: set[str] | None = None,
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

`resolve_attachments` bool \| Literal\['full', 'core'\]  
Resolve attachments (duplicated content blocks) to their full content.

`format` Literal\['eval', 'json', 'auto'\]  
Read from format (defaults to ‘auto’ based on `log_file` extension)

`exclude_fields` set\[str\] \| None  
Set of field names to exclude when reading the sample. Useful when
reading large samples with fields like ‘store’ or ‘attachments’ that
aren’t needed.

### read_eval_log_samples

Read all samples from an evaluation log incrementally.

Generator for samples in a log file. Only one sample at a time will be
read into memory and yielded to the caller.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_file.py#L590)

``` python
def read_eval_log_samples(
    log_file: str | Path | EvalLogInfo,
    all_samples_required: bool = True,
    resolve_attachments: bool | Literal["full", "core"] = False,
    format: Literal["eval", "json", "auto"] = "auto",
    exclude_fields: set[str] | None = None,
) -> Generator[EvalSample, None, None]
```

`log_file` str \| Path \| [EvalLogInfo](inspect_ai.log.qmd#evalloginfo)  
Log file to read.

`all_samples_required` bool  
All samples must be included in the file or an IndexError is thrown.

`resolve_attachments` bool \| Literal\['full', 'core'\]  
Resolve attachments (duplicated content blocks) to their full content.

`format` Literal\['eval', 'json', 'auto'\]  
Read from format (defaults to ‘auto’ based on `log_file` extension)

`exclude_fields` set\[str\] \| None  
Set of field names to exclude when reading the sample. Useful when
reading large samples with fields like ‘store’ or ‘attachments’ that
aren’t needed.

### read_eval_log_sample_summaries

Read sample summaries from an eval log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_file.py#L535)

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

### recompute_metrics

Recompute aggregate metrics after score edits.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_metric.py#L9)

``` python
def recompute_metrics(log: EvalLog) -> None
```

`log` [EvalLog](inspect_ai.log.qmd#evallog)  
The evaluation log to recompute metrics for

### convert_eval_logs

Convert between log file formats.

Convert log file(s) to a target format. If a file is already in the
target format it will just be copied to the output dir.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_convert.py#L22)

``` python
def convert_eval_logs(
    path: str,
    to: Literal["eval", "json"],
    output_dir: str,
    overwrite: bool = False,
    resolve_attachments: bool | Literal["full", "core"] = False,
    stream: int | bool = False,
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

`resolve_attachments` bool \| Literal\['full', 'core'\]  
Resolve attachments (duplicated content blocks) to their full content.

`stream` int \| bool  
Stream samples through the conversion process instead of reading the
entire log into memory. Useful for large logs.

### bundle_log_dir

Bundle a log_dir into a statically deployable viewer

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_bundle.py#L67)

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
used. If the path starts with ‘hf/’, it will be uploaded to HuggingFace
Hub.

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_file.py#L210)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_retry.py#L10)

``` python
def retryable_eval_logs(logs: list[EvalLogInfo]) -> list[EvalLogInfo]
```

`logs` list\[[EvalLogInfo](inspect_ai.log.qmd#evalloginfo)\]  
List of logs to examine.

### EvalLogInfo

File info and task identifiers for eval log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_file.py#L39)

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

## Log Editing

### edit_eval_log

Apply edits to a log.

Creates a LogUpdate from the edits and provenance, appends it to
log.log_updates, and recomputes cached tags/metadata. Returns modified
log (not persisted). Use write_eval_log() to save.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_edit.py#L70)

``` python
def edit_eval_log(
    log: EvalLog,
    edits: Sequence[LogEdit],
    provenance: ProvenanceData,
) -> EvalLog
```

`log` [EvalLog](inspect_ai.log.qmd#evallog)  
Eval log to edit.

`edits` Sequence\[[LogEdit](inspect_ai.log.qmd#logedit)\]  
List of edits to apply.

`provenance` [ProvenanceData](inspect_ai.log.qmd#provenancedata)  
Provenance data for the edits.

### edit_score

Edit or add a score in-place.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_score.py#L11)

``` python
def edit_score(
    log: EvalLog,
    sample_id: int | str,
    score_name: str,
    edit: ScoreEdit,
    recompute_metrics: bool = True,
    epoch: int | None = None,
) -> None
```

`log` [EvalLog](inspect_ai.log.qmd#evallog)  
The evaluation log containing the samples and scores

`sample_id` int \| str  
ID of the sample containing the score to edit or add to

`score_name` str  
Name of the score to edit. If the score does not exist, a new score will
be created with this name.

`edit` ScoreEdit  
The edit to apply to the score. When creating a new score, the ‘value’
field must be provided (cannot be UNCHANGED).

`recompute_metrics` bool  
Whether to recompute aggregate metrics after editing

`epoch` int \| None  
Epoch number of the sample to edit (required when there are multiple
epochs)

### invalidate_samples

Invalidate samples in the log.

Additionally, sets `EvalLog.invalidated = True`. Logs with invalidated
samples will be automatically retried when executing eval sets.

The log with invalidated samples is returned but not persisted to
storage. Use `write_eval_log()` to save the new log with invalidated
samples.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_edit.py#L197)

``` python
def invalidate_samples(
    log: EvalLog,
    sample_uuids: Sequence[str] | Literal["all"],
    provenance: ProvenanceData,
) -> EvalLog
```

`log` [EvalLog](inspect_ai.log.qmd#evallog)  
Eval log

`sample_uuids` Sequence\[str\] \| Literal\['all'\]  
List of sample uuids to invalidate (or “all” to invaliate all samples).

`provenance` [ProvenanceData](inspect_ai.log.qmd#provenancedata)  
Timestamp and optional author, reason, and metadata for the
invalidation.

### uninvalidate_samples

Uninvalidate samples in the log.

Additionally, sets `EvalLog.invalidated = False` if there are no more
invalidated samples.

The log with uninvalidated samples is returned but not persisted to
storage. Use `write_eval_log()` to save the new log with uninvalidated
samples.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_edit.py#L224)

``` python
def uninvalidate_samples(
    log: EvalLog, sample_uuids: Sequence[str] | Literal["all"]
) -> EvalLog
```

`log` [EvalLog](inspect_ai.log.qmd#evallog)  
Eval log

`sample_uuids` Sequence\[str\] \| Literal\['all'\]  
List of sample uuids to uninvalidate (or “all” to uninvalidate all
samples).

### LogUpdate

A group of edits that share provenance.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_edit.py#L60)

``` python
class LogUpdate(BaseModel)
```

#### Attributes

`edits` list\[LogEditType\]  
List of edits in this update.

`provenance` [ProvenanceData](inspect_ai.log.qmd#provenancedata)  
Provenance for this update.

### LogEdit

A single edit action on log tags and/or metadata.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_edit.py#L29)

``` python
class LogEdit(BaseModel)
```

### MetadataEdit

Edit action for metadata.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_edit.py#L45)

``` python
class MetadataEdit(LogEdit)
```

#### Attributes

`metadata_set` dict\[str, Any\]  
Metadata keys to set.

`metadata_remove` list\[str\]  
Metadata keys to remove.

### TagsEdit

Edit action for tags.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_edit.py#L33)

``` python
class TagsEdit(LogEdit)
```

#### Attributes

`tags_add` list\[str\]  
Tags to add.

`tags_remove` list\[str\]  
Tags to remove.

### ProvenanceData

Metadata about who made an edit and why.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_edit.py#L13)

``` python
class ProvenanceData(BaseModel)
```

#### Attributes

`timestamp` UtcDatetime  
Timestamp when the edit was made.

`author` str  
Author who made the edit.

`reason` str \| None  
Reason for the edit.

`metadata` dict\[str, Any\]  
Additional metadata about the edit.

## Eval Log API

### EvalStatus

Status of an evaluation run.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L55)

``` python
EvalStatus = Literal["started", "success", "cancelled", "error"]
```

### EvalLog

Evaluation log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L981)

``` python
class EvalLog(BaseModel)
```

#### Attributes

`version` int  
Eval log file format version.

`status` [EvalStatus](inspect_ai.log.qmd#evalstatus)  
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

`invalidated` bool  
Whether any samples were invalidated.

`log_updates` list\[[LogUpdate](inspect_ai.log.qmd#logupdate)\] \| None  
Post-eval edits to tags and metadata.

`tags` list\[str\]  
Current tags (eval-time + edits). Do not set directly; use
edit_eval_log().

`metadata` dict\[str, Any\]  
Current metadata (eval-time + edits). Do not set directly; use
edit_eval_log().

`samples` list\[[EvalSample](inspect_ai.log.qmd#evalsample)\] \| None  
Samples processed by eval.

`reductions` list\[[EvalSampleReductions](inspect_ai.log.qmd#evalsamplereductions)\] \| None  
Reduced sample values

`location` str  
Location that the log file was read from.

`etag` str \| None  
ETag from S3 for conditional writes.

#### Methods

recompute_tags_and_metadata  
Recompute tags and metadata from eval-time values + log_updates.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L1038)

``` python
def recompute_tags_and_metadata(self) -> None
```

### EvalSpec

Eval target and configuration.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L808)

``` python
class EvalSpec(BaseModel)
```

#### Attributes

`eval_set_id` str \| None  
Globally unique id for eval set (if any).

`eval_id` str  
Globally unique id for eval.

`run_id` str  
Unique run id

`created` UtcDatetimeStr  
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

`solver_args_passed` dict\[str, Any\] \| None  
Arguments explicitly passed by caller for invoking the solver.

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

`model_roles` dict\[str, [ModelConfig](inspect_ai.model.qmd#modelconfig)\] \| None  
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

`metrics` list\[EvalMetricDefinition \| dict\[str, list\[EvalMetricDefinition\]\]\] \| dict\[str, list\[EvalMetricDefinition\]\] \| None  
metrics and args for this eval

### EvalDataset

Dataset used for evaluation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L749)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L89)

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

`continue_on_fail` bool \| None  
Continue eval even if the `fail_on_error` condition is met.

`True` to continue running and only fail at the end if the
`fail_on_error` condition is met. `False` to fail eval immediately when
the `fail_on_error` condition is met (default).

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

`cost_limit` float \| None  
Maximum cost (in dollars) per sample.

`max_samples` int \| None  
Maximum number of samples to run in parallel.

`max_dataset_memory` int \| None  
Maximum MB of dataset sample data to hold in memory per task. When
exceeded, samples are paged to a temporary file on disk.

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

`log_model_api` bool \| None  
Log raw model api requests and responses.

`log_buffer` int \| None  
Number of samples to buffer before writing log file.

`log_shared` int \| None  
Interval (in seconds) for syncing sample events to log directory.

`score_display` bool \| None  
Display scoring metrics realtime.

### EvalRevision

Git revision for evaluation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L792)

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

`dirty` bool \| None  
Working tree has uncommitted changes or untracked files.

### EvalPlan

Plan (solvers) used in evaluation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L581)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L558)

``` python
class EvalPlanStep(BaseModel)
```

#### Attributes

`solver` str  
Name of solver.

`params` dict\[str, Any\]  
Parameters used to instantiate solver.

`params_passed` dict\[str, Any\]  
Parameters explicitly passed to the eval plan.

### EvalResults

Scoring results from evaluation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L661)

``` python
class EvalResults(BaseModel)
```

#### Attributes

`total_samples` int  
Total samples in eval (dataset samples \* epochs)

`completed_samples` int  
Samples completed without error.

Will be equal to total_samples except when –fail-on-error is enabled or
when there is early stopping.

`early_stopping` [EarlyStoppingSummary](inspect_ai.util.qmd#earlystoppingsummary) \| None  
Early stopping summary (if an early stopping manager was present).

`scores` list\[[EvalScore](inspect_ai.log.qmd#evalscore)\]  
Scorers used to compute results

`metadata` dict\[str, Any\] \| None  
Additional results metadata.

`sample_reductions` list\[[EvalSampleReductions](inspect_ai.log.qmd#evalsamplereductions)\] \| None  
List of per sample scores reduced across epochs

### EvalScore

Score for evaluation task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L613)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L597)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L648)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L962)

``` python
class EvalStats(BaseModel)
```

#### Attributes

`started_at` UtcDatetimeStr \| Literal\[''\]  
Evaluation start time. Empty string if eval interrupted before start
time set.

`completed_at` UtcDatetimeStr \| Literal\[''\]  
Evaluation completion time. Empty string if eval interrupted before
completion.

`model_usage` dict\[str, [ModelUsage](inspect_ai.model.qmd#modelusage)\]  
Model token usage for evaluation.

`role_usage` dict\[str, [ModelUsage](inspect_ai.model.qmd#modelusage)\]  
Model token usage by role for evaluation.

### EvalError

Eval error details.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/_util/error.py#L11)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L311)

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

`events` list\[Event\]  
Events that occurred during sample execution.

`timelines` list\[[Timeline](inspect_ai.event.qmd#timeline)\] \| None  
Custom timelines for this sample.

`model_usage` dict\[str, [ModelUsage](inspect_ai.model.qmd#modelusage)\]  
Model token usage for sample.

`role_usage` dict\[str, [ModelUsage](inspect_ai.model.qmd#modelusage)\]  
Model token usage by role for sample.

`started_at` UtcDatetimeStr \| None  
Time sample started.

`completed_at` UtcDatetimeStr \| None  
Time sample completed.

`total_time` float \| None  
Total time that the sample was running.

`working_time` float \| None  
Time spent working (model generation, sandbox calls, etc.)

`uuid` str \| None  
Globally unique identifier for sample run (exists for samples created in
Inspect \>= 0.3.70)

`invalidation` [ProvenanceData](inspect_ai.log.qmd#provenancedata) \| None  
Provenance data for invalidation.

`error` [EvalError](inspect_ai.log.qmd#evalerror) \| None  
Error that halted sample.

`error_retries` list\[[EvalError](inspect_ai.log.qmd#evalerror)\] \| None  
Errors that were retried for this sample.

`attachments` dict\[str, str\]  
Attachments referenced from messages and events.

Resolve attachments for a sample (replacing <attachment://>\* references
with attachment content) by passing `resolve_attachments=True` to log
reading functions.

`events_data` [EventsData](inspect_ai.log.qmd#eventsdata) \| None  
Pooled dedup data for condensed events (messages and calls).

`limit` [EvalSampleLimit](inspect_ai.log.qmd#evalsamplelimit) \| None  
The limit that halted the sample

#### Methods

metadata_as  
Pydantic model interface to metadata.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L350)

``` python
def metadata_as(self, metadata_cls: Type[MT]) -> MT
```

`metadata_cls` Type\[MT\]  
Pydantic model type

store_as  
Pydantic model interface to the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L364)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L439)

``` python
def summary(self) -> EvalSampleSummary
```

### EvalSampleSummary

Summary information (including scoring) for a sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L217)

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

`choices` list\[str\] \| None  
Sample choices.

`target` str \| list\[str\]  
Sample target value(s)

`metadata` dict\[str, Any\]  
Sample metadata (only fields \< 1k; strings truncated to 1k).

`scores` dict\[str, [Score](inspect_ai.scorer.qmd#score)\] \| None  
Scores for sample (only metadata fields \< 1k; strings truncated to 1k).

`model_usage` dict\[str, [ModelUsage](inspect_ai.model.qmd#modelusage)\]  
Model token usage for sample.

`role_usage` dict\[str, [ModelUsage](inspect_ai.model.qmd#modelusage)\]  
Model token usage by role for sample.

`started_at` UtcDatetimeStr \| None  
Time sample started.

`completed_at` UtcDatetimeStr \| None  
Time sample completed.

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

`message_count` int \| None  
Number of messages in the sample conversation.

### EvalSampleLimit

Limit encountered by sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L205)

``` python
class EvalSampleLimit(BaseModel)
```

#### Attributes

`type` Literal\['context', 'time', 'working', 'message', 'token', 'cost', 'operator', 'custom'\]  
The type of limit

`limit` float  
The limit value

### EvalSampleReductions

Score reductions.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L648)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L641)

``` python
class EvalSampleScore(Score)
```

#### Attributes

`value` [Value](inspect_ai.scorer.qmd#value)  
Score value.

`answer` str \| None  
Answer extracted from model output (optional)

`explanation` str \| None  
Explanation of score (optional).

`metadata` dict\[str, Any\] \| None  
Additional metadata related to the score

`history` list\[ScoreEdit\]  
Edit history - users can access intermediate states.

`text` str  
Read the score as text.

`sample_id` str \| int \| None  
Sample ID.

#### Methods

as_str  
Read the score as a string.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/scorer/_metric.py#L104)

``` python
def as_str(self) -> str
```

as_int  
Read the score as an integer.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/scorer/_metric.py#L108)

``` python
def as_int(self) -> int
```

as_float  
Read the score as a float.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/scorer/_metric.py#L112)

``` python
def as_float(self) -> float
```

as_bool  
Read the score as a boolean.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/scorer/_metric.py#L116)

``` python
def as_bool(self) -> bool
```

as_list  
Read the score as a list.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/scorer/_metric.py#L120)

``` python
def as_list(self) -> list[str | int | float | bool]
```

as_dict  
Read the score as a dictionary.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/scorer/_metric.py#L127)

``` python
def as_dict(self) -> dict[str, str | int | float | bool | None]
```

### WriteConflictError

Exception raised when a conditional write fails due to concurrent
modification.

This error occurs when attempting to write to a log file that has been
modified by another process since it was last read, indicating a race
condition between concurrent evaluation runs.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/_util/error.py#L62)

``` python
class WriteConflictError(Exception)
```

## Condense API

### condense_sample

Reduce the storage size of the eval sample.

Reduce size by: 1. De-duplicating larger content fields (especially
important for images but also for message repeated over and over in the
event stream) 2. Removing base64 encoded images if log_images is True

The de-duplication of content fields can be reversed by calling
`resolve_attachments()`. Removal of base64 encoded images is a one-way
operation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_condense.py#L114)

``` python
def condense_sample(sample: EvalSample, log_images: bool = True) -> EvalSample
```

`sample` [EvalSample](inspect_ai.log.qmd#evalsample)  
Eval sample to condense.

`log_images` bool  
Should base64 images be logged for this sample.

### condense_events

De-duplicate repeated content in a sequence of events.

Extracts repeated ModelEvent inputs and calls into shared pools,
replacing inline content with pool index references.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_condense.py#L65)

``` python
def condense_events(
    events: Sequence[Event],
) -> tuple[list[Event], EventsData]
```

`events` Sequence\[Event\]  
Events to condense.

### expand_events

Reverse :func:`condense_events` — restore pooled content into events.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_condense.py#L84)

``` python
def expand_events(
    events: Sequence[Event] | str,
    data: EventsData | str,
) -> list[Event]
```

`events` Sequence\[Event\] \| str  
Condensed events (with pool index references), or a JSON-serialized
`list[Event]`.

`data` [EventsData](inspect_ai.log.qmd#eventsdata) \| str  
Events data returned by :func:`condense_events`, or a JSON-serialized
`EventsData`.

### EventsData

Pooled data extracted by condense_events / condense_sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_log.py#L48)

``` python
class EventsData(TypedDict)
```

## Transcript API

### transcript

Get the current `Transcript`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_transcript.py#L147)

``` python
def transcript() -> Transcript
```

### Transcript

Transcript of events.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_transcript.py#L36)

``` python
class Transcript
```

#### Methods

info  
Add an `InfoEvent` to the transcript.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_transcript.py#L58)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_transcript.py#L67)

``` python
@contextlib.contextmanager
def step(self, name: str, type: str | None = None) -> Iterator[None]
```

`name` str  
Step name.

`type` str \| None  
Optional step type.

add_timeline  
Add a named timeline to the transcript.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b979937677100d7e122936c1f3af7fae94f2052d/src/inspect_ai/log/_transcript.py#L98)

``` python
def add_timeline(self, timeline: Timeline) -> None
```

`timeline` [Timeline](inspect_ai.event.qmd#timeline)  
Timeline to add.
