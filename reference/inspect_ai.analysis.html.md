# inspect_ai.analysis


## Evals

### evals_df

Read a dataframe containing evals.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/evals/table.py#L54)

``` python
def evals_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = EvalColumns,
    strict: bool = True,
    quiet: bool | None = None,
) -> "pd.DataFrame" | tuple["pd.DataFrame", Sequence[ColumnError]]
```

`logs` LogPaths  
One or more paths to log files or log directories. Defaults to the
contents of the currently active log directory (e.g. ./logs or
INSPECT_LOG_DIR).

`columns` Sequence\[[Column](inspect_ai.analysis.qmd#column)\]  
Specification for what columns to read from log files.

`strict` bool  
Raise import errors immediately. Defaults to `True`. If `False` then a
tuple of `DataFrame` and errors is returned.

`quiet` bool \| None  
If `True`, do not show any output or progress. Defaults to `False` for
terminal environments, and `True` for notebooks.

### EvalColumn

Column which maps to `EvalLog`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/evals/columns.py#L21)

``` python
class EvalColumn(Column)
```

### EvalColumns

Default columns to import for `evals_df()`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/evals/columns.py#L136)

``` python
EvalColumns: list[Column] = (
    EvalInfo
    + EvalTask
    + EvalModel
    + EvalDataset
    + EvalConfiguration
    + EvalResults
    + EvalScores
)
```

### EvalInfo

Eval basic information columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/evals/columns.py#L61)

``` python
EvalInfo: list[Column] = [
    EvalColumn("eval_set_id", path="eval.eval_set_id"),
    EvalColumn("run_id", path="eval.run_id", required=True),
    EvalColumn("task_id", path="eval.task_id", required=True),
    *EvalLogPath,
    EvalColumn("created", path="eval.created", type=datetime, required=True),
    EvalColumn("tags", path="eval.tags", default="", value=list_as_str),
    EvalColumn("git_origin", path="eval.revision.origin"),
    EvalColumn("git_commit", path="eval.revision.commit"),
    EvalColumn("packages", path="eval.packages"),
    EvalColumn("metadata", path="eval.metadata"),
]
```

### EvalTask

Eval task configuration columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/evals/columns.py#L75)

``` python
EvalTask: list[Column] = [
    EvalColumn("task_name", path="eval.task", required=True, value=remove_namespace),
    EvalColumn("task_display_name", path=eval_log_task_display_name),
    EvalColumn("task_version", path="eval.task_version", required=True),
    EvalColumn("task_file", path="eval.task_file"),
    EvalColumn("task_attribs", path="eval.task_attribs"),
    EvalColumn("task_arg_*", path="eval.task_args"),
    EvalColumn("solver", path="eval.solver"),
    EvalColumn("solver_args", path="eval.solver_args"),
    EvalColumn("sandbox_type", path="eval.sandbox.type"),
    EvalColumn("sandbox_config", path="eval.sandbox.config"),
]
```

### EvalModel

Eval model columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/evals/columns.py#L89)

``` python
EvalModel: list[Column] = [
    EvalColumn("model", path="eval.model", required=True),
    EvalColumn("model_base_url", path="eval.model_base_url"),
    EvalColumn("model_args", path="eval.model_base_url"),
    EvalColumn("model_generate_config", path="eval.model_generate_config"),
    EvalColumn("model_roles", path="eval.model_roles"),
]
```

### EvalConfiguration

Eval configuration columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/evals/columns.py#L107)

``` python
EvalConfiguration: list[Column] = [
    EvalColumn("epochs", path="eval.config.epochs"),
    EvalColumn("epochs_reducer", path="eval.config.epochs_reducer"),
    EvalColumn("approval", path="eval.config.approval"),
    EvalColumn("message_limit", path="eval.config.message_limit"),
    EvalColumn("token_limit", path="eval.config.token_limit"),
    EvalColumn("time_limit", path="eval.config.time_limit"),
    EvalColumn("working_limit", path="eval.config.working_limit"),
]
```

### EvalResults

Eval results columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/evals/columns.py#L118)

``` python
EvalResults: list[Column] = [
    EvalColumn("status", path="status", required=True),
    EvalColumn("error_message", path="error.message"),
    EvalColumn("error_traceback", path="error.traceback"),
    EvalColumn("total_samples", path="results.total_samples"),
    EvalColumn("completed_samples", path="results.completed_samples"),
    EvalColumn("score_headline_name", path="results.scores[0].scorer"),
    EvalColumn("score_headline_metric", path="results.scores[0].metrics.*.name"),
    EvalColumn("score_headline_value", path="results.scores[0].metrics.*.value"),
    EvalColumn("score_headline_stderr", path=eval_log_headline_stderr),
]
```

### EvalScores

Eval scores (one score/metric per-columns).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/evals/columns.py#L131)

``` python
EvalScores: list[Column] = [
    EvalColumn("score_*_*", path=eval_log_scores_dict),
]
```

## Samples

### samples_df

Read a dataframe containing samples from a set of evals.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/samples/table.py#L80)

``` python
def samples_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = SampleSummary,
    full: bool = False,
    strict: bool = True,
    parallel: bool | int = False,
    quiet: bool | None = None,
) -> "pd.DataFrame" | tuple["pd.DataFrame", list[ColumnError]]
```

`logs` LogPaths  
One or more paths to log files or log directories. Defaults to the
contents of the currently active log directory (e.g. ./logs or
INSPECT_LOG_DIR).

`columns` Sequence\[[Column](inspect_ai.analysis.qmd#column)\]  
Specification for what columns to read from log files.

`full` bool  
Read full sample `metadata`. This will be much slower, but will include
the unfiltered values of sample `metadata` rather than the abbrevivated
metadata from sample summaries (which includes only scalar values and
limits string values to 1k).

`strict` bool  
Raise import errors immediately. Defaults to `True`. If `False` then a
tuple of `DataFrame` and errors is returned.

`parallel` bool \| int  
If `True`, use `ProcessPoolExecutor` to read logs in parallel (with
workers based on `mp.cpu_count()`, capped at 8). If `int`, read in
parallel with the specified number of workers. If `False` (the default)
do not read in parallel.

`quiet` bool \| None  
If `True`, do not show any output or progress. Defaults to `False` for
terminal environments, and `True` for notebooks.

### SampleColumn

Column which maps to `EvalSample` or `EvalSampleSummary`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/samples/columns.py#L19)

``` python
class SampleColumn(Column)
```

### SampleSummary

Sample summary columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/samples/columns.py#L58)

``` python
SampleSummary: list[Column] = [
    SampleColumn("id", path="id", required=True, type=str),
    SampleColumn("epoch", path="epoch", required=True),
    SampleColumn("input", path=sample_input_as_str, required=True),
    SampleColumn("target", path="target", required=True, value=list_as_str),
    SampleColumn("metadata_*", path="metadata"),
    SampleColumn("score_*", path="scores", value=score_values),
    SampleColumn("model_usage", path="model_usage"),
    SampleColumn("total_time", path="total_time"),
    SampleColumn("working_time", path="total_time"),
    SampleColumn("error", path="error", default=""),
    SampleColumn("limit", path="limit"),
    SampleColumn("retries", path="retries"),
]
```

### SampleMessages

Sample messages as a string.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/samples/columns.py#L74)

``` python
SampleMessages: list[Column] = [
    SampleColumn("messages", path=sample_messages_as_str, required=True, full=True)
]
```

## Messages

### messages_df

Read a dataframe containing messages from a set of evals.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/messages/table.py#L45)

``` python
def messages_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = MessageColumns,
    filter: MessageFilter | None = None,
    strict: bool = True,
    parallel: bool | int = False,
    quiet: bool | None = None,
) -> "pd.DataFrame" | tuple["pd.DataFrame", list[ColumnError]]
```

`logs` LogPaths  
One or more paths to log files or log directories. Defaults to the
contents of the currently active log directory (e.g. ./logs or
INSPECT_LOG_DIR).

`columns` Sequence\[[Column](inspect_ai.analysis.qmd#column)\]  
Specification for what columns to read from log files.

`filter` [MessageFilter](inspect_ai.analysis.qmd#messagefilter) \| None  
Callable that filters messages

`strict` bool  
Raise import errors immediately. Defaults to `True`. If `False` then a
tuple of `DataFrame` and errors is returned.

`parallel` bool \| int  
If `True`, use `ProcessPoolExecutor` to read logs in parallel (with
workers based on `mp.cpu_count()`, capped at 8). If `int`, read in
parallel with the specified number of workers. If `False` (the default)
do not read in parallel.

`quiet` bool \| None  
If `True`, do not show any output or progress. Defaults to `False` for
terminal environments, and `True` for notebooks.

### MessageFilter

Filter for `messages_df()` rows.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/messages/table.py#L19)

``` python
MessageFilter: TypeAlias = Callable[[ChatMessage], bool]
```

### MessageColumn

Column which maps to `ChatMessage`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/messages/columns.py#L16)

``` python
class MessageColumn(Column)
```

### MessageContent

Message content columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/messages/columns.py#L44)

``` python
MessageContent: list[Column] = [
    MessageColumn("message_id", path="id"),
    MessageColumn("role", path="role", required=True),
    MessageColumn("source", path="source"),
    MessageColumn("content", path=message_text),
]
```

### MessageToolCalls

Message tool call columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/messages/columns.py#L52)

``` python
MessageToolCalls: list[Column] = [
    MessageColumn("tool_calls", path=message_tool_calls),
    MessageColumn("tool_call_id", path="tool_call_id"),
    MessageColumn("tool_call_function", path="function"),
    MessageColumn("tool_call_error", path="error.message"),
]
```

### MessageColumns

Chat message columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/messages/columns.py#L60)

``` python
MessageColumns: list[Column] = MessageContent + MessageToolCalls
```

## Events

### events_df

Read a dataframe containing events from a set of evals.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/events/table.py#L45)

``` python
def events_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = EventInfo,
    filter: EventFilter | None = None,
    strict: bool = True,
    parallel: bool | int = False,
    quiet: bool | None = None,
) -> "pd.DataFrame" | tuple["pd.DataFrame", list[ColumnError]]
```

`logs` LogPaths  
One or more paths to log files or log directories. Defaults to the
contents of the currently active log directory (e.g. ./logs or
INSPECT_LOG_DIR).

`columns` Sequence\[[Column](inspect_ai.analysis.qmd#column)\]  
Specification for what columns to read from log files.

`filter` EventFilter \| None  
Callable that filters event types.

`strict` bool  
Raise import errors immediately. Defaults to `True`. If `False` then a
tuple of `DataFrame` and errors is returned.

`parallel` bool \| int  
If `True`, use `ProcessPoolExecutor` to read logs in parallel (with
workers based on `mp.cpu_count()`, capped at 8). If `int`, read in
parallel with the specified number of workers. If `False` (the default)
do not read in parallel.

`quiet` bool \| None  
If `True`, do not show any output or progress. Defaults to `False` for
terminal environments, and `True` for notebooks.

### EventColumn

Column which maps to `Event`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/events/columns.py#L19)

``` python
class EventColumn(Column)
```

### EventInfo

Event basic information columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/events/columns.py#L47)

``` python
EventInfo: list[Column] = [
    EventColumn("event_id", path="uuid"),
    EventColumn("event", path="event"),
    EventColumn("span_id", path="span_id"),
]
```

### EventTiming

Event timing columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/events/columns.py#L54)

``` python
EventTiming: list[Column] = [
    EventColumn("timestamp", path="timestamp", type=datetime),
    EventColumn("completed", path="completed", type=datetime),
    EventColumn("working_start", path="working_start"),
    EventColumn("working_time", path="working_time"),
]
```

### ModelEventColumns

Model event columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/events/columns.py#L62)

``` python
ModelEventColumns: list[Column] = [
    EventColumn("model_event_model", path="model"),
    EventColumn("model_event_role", path="role"),
    EventColumn("model_event_input", path=model_event_input_as_str),
    EventColumn("model_event_tools", path="tools"),
    EventColumn("model_event_tool_choice", path=tool_choice_as_str),
    EventColumn("model_event_config", path="config"),
    EventColumn("model_event_usage", path="output.usage"),
    EventColumn("model_event_time", path="output.time"),
    EventColumn("model_event_completion", path=completion_as_str),
    EventColumn("model_event_retries", path="retries"),
    EventColumn("model_event_error", path="error"),
    EventColumn("model_event_cache", path="cache"),
    EventColumn("model_event_call", path="call"),
]
```

### ToolEventColumns

Tool event columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/events/columns.py#L79)

``` python
ToolEventColumns: list[Column] = [
    EventColumn("tool_event_function", path="function"),
    EventColumn("tool_event_arguments", path="arguments"),
    EventColumn("tool_event_view", path=tool_view_as_str),
    EventColumn("tool_event_result", path="result"),
    EventColumn("tool_event_truncated", path="truncated"),
    EventColumn("tool_event_error_type", path="error.type"),
    EventColumn("tool_event_error_message", path="error.message"),
]
```

## Prepare

### prepare

Prepare a data frame for analysis using one or more transform
operations.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_prepare/prepare.py#L10)

``` python
def prepare(
    df: "pd.DataFrame", operation: Operation | Sequence[Operation]
) -> "pd.DataFrame"
```

`df` pd.DataFrame  
Input data frame.

`operation` [Operation](inspect_ai.analysis.qmd#operation) \| Sequence\[[Operation](inspect_ai.analysis.qmd#operation)\]  
`Operation` or sequence of operations to apply.

### log_viewer

Add a log viewer column to an eval data frame.

Tranform operation to add a log_viewer column to a data frame based on
one more more `url_mappings`.

URL mappings define the relationship between log file paths (either
fileystem or S3) and URLs where logs are published. The URL target
should be the location where the output of the
[`inspect view bundle`](../log-viewer.qmd#sec-publishing) command was
published.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_prepare/log_viewer.py#L8)

``` python
def log_viewer(
    target: Literal["eval", "sample", "event", "message"],
    url_mappings: dict[str, str],
    log_column: str = "log",
    log_viewer_column: str = "log_viewer",
) -> Operation
```

`target` Literal\['eval', 'sample', 'event', 'message'\]  
Target for log viewer (“eval”, “sample”, “event”, or “message”).

`url_mappings` dict\[str, str\]  
Map log file paths (either filesystem or S3) to URLs where logs are
published.

`log_column` str  
Column in the data frame containing log file path (defaults to “log”).

`log_viewer_column` str  
Column to create with log viewer URL (defaults to “log_viewer”)

### model_info

Amend data frame with model metadata.

Fields added (when available) include:

`model_organization_name`  
Displayable model organization (e.g. OpenAI, Anthropic, etc.)

`model_display_name`  
Displayable model name (e.g. Gemini Flash 2.5)

`model_snapshot`  
A snapshot (version) string, if available (e.g. “latest” or “20240229”)

`model_release_date`  
The model’s release date

`model_knowledge_cutoff_date`  
The model’s knowledge cutoff date

Inspect includes built in support for many models (based upon the
`model` string in the dataframe). If you are using models for which
Inspect does not include model metadata, you may include your own model
metadata via the `model_info` argument.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_prepare/model_info.py#L10)

``` python
def model_info(
    model_info: Dict[str, ModelInfo] | None = None,
) -> Operation
```

`model_info` Dict\[str, [ModelInfo](inspect_ai.analysis.qmd#modelinfo)\] \| None  
Additional model info for models not supported directly by Inspect’s
internal database.

### task_info

Amend data frame with task display name.

Maps task names to task display names for plotting (e.g. “gpqa_diamond”
-\> “GPQA Diamond”)

If no mapping is provided for a task then name will come from the
`display_name` attribute of the `Task` (or failing that from the
registered name of the `Task`).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_prepare/task_info.py#L6)

``` python
def task_info(
    display_names: dict[str, str],
    task_name_column: str = "task_name",
    task_display_name_column: str = "task_display_name",
) -> Operation
```

`display_names` dict\[str, str\]  
Mapping of task log names (e.g. “gpqa_diamond”) to task display names
(e.g. “GPQA Diamond”).

`task_name_column` str  
Column to draw the task name from (defaults to “task_name”).

`task_display_name_column` str  
Column to populate with the task display name (defaults to
“task_display_name”)

### frontier

Add a frontier column to an eval data frame.

Tranform operation to add a frontier column to a data frame based using
a task, release date, and score.

The frontier column will be True if the model was the top-scoring model
on the task among all models available at the moment the model was
released; otherwise it will be False.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_prepare/frontier.py#L4)

``` python
def frontier(
    task_column: str = "task_name",
    date_column: str = "model_release_date",
    score_column: str = "score_headline_value",
    frontier_column: str = "frontier",
) -> Operation
```

`task_column` str  
The column in the data frame containing the task name (defaults to
“task_name”).

`date_column` str  
The column in the data frame containing the model release date (defaults
to “model_release_date”).

`score_column` str  
The column in the data frame containing the score (defaults to
“score_headline_value”).

`frontier_column` str  
The column to create with the frontier value (defaults to “frontier”).

### score_to_float

Converts score columns to float values.

For each column specified, this operation will convert the values to
floats using the provided `value_to_float` function. The column value
will be replaced with the float value.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_prepare/score_to_float.py#L7)

``` python
def score_to_float(
    columns: str | Sequence[str], *, value_to_float: ValueToFloat = value_to_float()
) -> Operation
```

`columns` str \| Sequence\[str\]  
The name of the score column(s) to convert to float. This can be a
single column name or a sequence of column names.

`value_to_float` ValueToFloat  
Function to convert values to float. Defaults to the built-in
`value_to_float` function.

### Operation

Operation to transform a data frame for analysis.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_prepare/operation.py#L8)

``` python
class Operation(Protocol):
    def __call__(self, df: "pd.DataFrame") -> "pd.DataFrame"
```

`df` pd.DataFrame  
Input data frame.

### ModelInfo

Model information and metadata

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_prepare/model_data/model_data.py#L73)

``` python
class ModelInfo(BaseModel)
```

#### Attributes

`organization` str \| None  
Model organization (e.g. Anthropic, OpenAI).

`model` str \| None  
Model name (e.g. Gemini 2.5 Flash).

`snapshot` str \| None  
A snapshot (version) string, if available (e.g. “latest” or
“20240229”)..

`release_date` date \| None  
The mode’s release date.

## Columns

### Column

Specification for importing a column into a dataframe.

Extract columns from an `EvalLog` path either using
[JSONPath](https://github.com/h2non/jsonpath-ng) expressions or a
function that takes `EvalLog` and returns a value.

By default, columns are not required, pass `required=True` to make them
required. Non-required columns are extracted as `None`, provide a
`default` to yield an alternate value.

The `type` option serves as both a validation check and a directive to
attempt to coerce the data into the specified `type`. Coercion from
`str` to other types is done after interpreting the string using YAML
(e.g. `"true"` -\> `True`).

The `value` function provides an additional hook for transformation of
the value read from the log before it is realized as a column (e.g. list
to a comma-separated string).

The `root` option indicates which root eval log context the columns
select from.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/columns.py#L21)

``` python
class Column(abc.ABC)
```

#### Attributes

`name` str  
Column name.

`path` JSONPath \| None  
Path to column in `EvalLog`

`required` bool  
Is the column required? (error is raised if required columns aren’t
found).

`default` JsonValue \| None  
Default value for column when it is read from the log as `None`.

`type` Type\[[ColumnType](inspect_ai.analysis.qmd#columntype)\] \| None  
Column type (import will attempt to coerce to the specified type).

#### Methods

value  
Convert extracted value into a column value (defaults to identity
function).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/columns.py#L86)

``` python
def value(self, x: JsonValue) -> JsonValue
```

`x` JsonValue  
Value to convert.

### ColumnType

Valid types for columns.

Values of `list` and `dict` are converted into column values as JSON
`str`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/columns.py#L14)

``` python
ColumnType: TypeAlias = int | float | bool | str | date | time | datetime | None
```

### ColumnError

Error which occurred parsing a column.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0ac98764442c6dd3f249b906fc027a0999a43094/src/inspect_ai/analysis/_dataframe/columns.py#L115)

``` python
@dataclass
class ColumnError
```

#### Attributes

`column` str  
Target column name.

`path` str \| None  
Path to select column value.

`error` Exception  
Underlying error.

`log` [EvalLog](inspect_ai.log.qmd#evallog)  
Eval log where the error occurred.

Use log.location to determine the path where the log was read from.
