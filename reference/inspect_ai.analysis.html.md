# inspect_ai.analysis.beta


> [!NOTE]
>
> Analysis functions are currently in beta and are exported from the
> **inspect_ai.analysis.beta** module. The beta module will be preserved
> after final release so that code written against it now will continue
> to work after the beta.

## Evals

### evals_df

Read a dataframe containing evals.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/evals/table.py#L52)

``` python
def evals_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = EvalColumns,
    strict: bool = True,
    quiet: bool = False,
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

`quiet` bool  
If `True`, do not show any output or progress. Defaults to `False`.

### EvalColumn

Column which maps to `EvalLog`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/evals/columns.py#L16)

``` python
class EvalColumn(Column)
```

### EvalColumns

Default columns to import for `evals_df()`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/evals/columns.py#L123)

``` python
EvalColumns: list[Column] = (
    EvalInfo
    + EvalTask
    + EvalModel
    + EvalDataset
    + EvalConfig
    + EvalResults
    + EvalScores
)
```

### EvalInfo

Eval basic information columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/evals/columns.py#L51)

``` python
EvalInfo: list[Column] = [
    EvalColumn("run_id", path="eval.run_id", required=True),
    EvalColumn("task_id", path="eval.task_id", required=True),
    EvalColumn("log", path=eval_log_location),
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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/evals/columns.py#L64)

``` python
EvalTask: list[Column] = [
    EvalColumn("task_name", path="eval.task", required=True),
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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/evals/columns.py#L77)

``` python
EvalModel: list[Column] = [
    EvalColumn("model", path="eval.model", required=True),
    EvalColumn("model_base_url", path="eval.model_base_url"),
    EvalColumn("model_args", path="eval.model_base_url"),
    EvalColumn("model_generate_config", path="eval.model_generate_config"),
    EvalColumn("model_roles", path="eval.model_roles"),
]
```

### EvalConfig

Eval configuration columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/evals/columns.py#L95)

``` python
EvalConfig: list[Column] = [
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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/evals/columns.py#L106)

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
]
```

### EvalScores

Eval scores (one score/metric per-columns).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/evals/columns.py#L118)

``` python
EvalScores: list[Column] = [
    EvalColumn("score_*_*", path=eval_log_scores_dict),
]
```

## Samples

### samples_df

Read a dataframe containing samples from a set of evals.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/samples/table.py#L75)

``` python
def samples_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = SampleSummary,
    strict: bool = True,
    parallel: bool | int = False,
    quiet: bool = False,
) -> "pd.DataFrame" | tuple["pd.DataFrame", list[ColumnError]]
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

`parallel` bool \| int  
If `True`, use `ProcessPoolExecutor` to read logs in parallel (with
workers based on `mp.cpu_count()`, capped at 8). If `int`, read in
parallel with the specified number of workers. If `False` (the default)
do not read in parallel.

`quiet` bool  
If `True` do not print any output or progress (defaults to `False`).

### SampleColumn

Column which maps to `EvalSample` or `EvalSampleSummary`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/samples/columns.py#L19)

``` python
class SampleColumn(Column)
```

### SampleSummary

Sample summary columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/samples/columns.py#L58)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/samples/columns.py#L74)

``` python
SampleMessages: list[Column] = [
    SampleColumn("messages", path=sample_messages_as_str, required=True, full=True)
]
```

## Messages

### messages_df

Read a dataframe containing messages from a set of evals.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/messages/table.py#L44)

``` python
def messages_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = MessageColumns,
    filter: MessageFilter | None = None,
    strict: bool = True,
    parallel: bool | int = False,
    quiet: bool = False,
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

`quiet` bool  
If `True` do not print any output or progress (defaults to `False`).

### MessageFilter

Filter for `messages_df()` rows.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/messages/table.py#L18)

``` python
MessageFilter: TypeAlias = Callable[[ChatMessage], bool]
```

### MessageColumn

Column which maps to `ChatMessage`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/messages/columns.py#L16)

``` python
class MessageColumn(Column)
```

### MessageContent

Message content columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/messages/columns.py#L44)

``` python
MessageContent: list[Column] = [
    MessageColumn("role", path="role", required=True),
    MessageColumn("source", path="source"),
    MessageColumn("content", path=message_text),
]
```

### MessageToolCalls

Message tool call columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/messages/columns.py#L51)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/messages/columns.py#L59)

``` python
MessageColumns: list[Column] = MessageContent + MessageToolCalls
```

## Events

### events_df

Read a dataframe containing events from a set of evals.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/events/table.py#L44)

``` python
def events_df(
    logs: LogPaths = list_eval_logs(),
    columns: Sequence[Column] = EventInfo,
    filter: EventFilter | None = None,
    strict: bool = True,
    parallel: bool | int = False,
    quiet: bool = False,
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

`quiet` bool  
If `True` do not print any output or progress (defaults to `False`).

### EventColumn

Column which maps to `Event`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/events/columns.py#L19)

``` python
class EventColumn(Column)
```

### EventInfo

Event basic information columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/events/columns.py#L47)

``` python
EventInfo: list[Column] = [
    EventColumn("event", path="event"),
    EventColumn("span_id", path="span_id"),
]
```

### EventTiming

Event timing columns.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/events/columns.py#L53)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/events/columns.py#L61)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/events/columns.py#L78)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/columns.py#L21)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/columns.py#L86)

``` python
def value(self, x: JsonValue) -> JsonValue
```

`x` JsonValue  
Value to convert.

### ColumnType

Valid types for columns.

Values of `list` and `dict` are converted into column values as JSON
`str`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/columns.py#L14)

``` python
ColumnType: TypeAlias = int | float | bool | str | date | time | datetime | None
```

### ColumnError

Error which occurred parsing a column.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/41225d6dde347d7c1f2e4467b3b0edfaabdd6338/src/inspect_ai/analysis/beta/_dataframe/columns.py#L115)

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
