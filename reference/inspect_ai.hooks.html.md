# inspect_ai.hooks


## Registration

### Hooks

Base class for hooks.

Note that whenever hooks are called, they are wrapped in a try/except
block to catch any exceptions that may occur. This is to ensure that a
hook failure does not affect the overall execution of the eval. If a
hook fails, a warning will be logged.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L186)

``` python
class Hooks
```

#### Methods

enabled  
Check if the hook should be enabled.

Default implementation returns True.

Hooks may wish to override this to e.g. check the presence of an
environment variable or a configuration setting.

Will be called frequently, so consider caching the result if the
computation is expensive.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L194)

``` python
def enabled(self) -> bool
```

on_eval_set_start  
On eval set start.

A “eval set” is an invocation of `eval_set()` for a log directory. Note
that the `eval_set_id` will be stable across multiple invocations of
`eval_set()` for the same log directory.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L207)

``` python
async def on_eval_set_start(self, data: EvalSetStart) -> None
```

`data` [EvalSetStart](inspect_ai.hooks.qmd#evalsetstart)  
Eval set start data.

on_eval_set_end  
On eval set end.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L219)

``` python
async def on_eval_set_end(self, data: EvalSetEnd) -> None
```

`data` [EvalSetEnd](inspect_ai.hooks.qmd#evalsetend)  
Eval set end data.

on_run_start  
On run start.

A “run” is a single invocation of `eval()` or `eval_retry()` which may
contain many Tasks, each with many Samples and many epochs. Note that
`eval_retry()` can be invoked multiple times within an `eval_set()`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L227)

``` python
async def on_run_start(self, data: RunStart) -> None
```

`data` [RunStart](inspect_ai.hooks.qmd#runstart)  
Run start data.

on_run_end  
On run end.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L239)

``` python
async def on_run_end(self, data: RunEnd) -> None
```

`data` [RunEnd](inspect_ai.hooks.qmd#runend)  
Run end data.

on_task_start  
On task start.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L247)

``` python
async def on_task_start(self, data: TaskStart) -> None
```

`data` [TaskStart](inspect_ai.hooks.qmd#taskstart)  
Task start data.

on_task_end  
On task end.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L255)

``` python
async def on_task_end(self, data: TaskEnd) -> None
```

`data` [TaskEnd](inspect_ai.hooks.qmd#taskend)  
Task end data.

on_sample_start  
On sample start.

Called when a sample is about to be start. If the sample errors and
retries, this will not be called again.

If a sample is run for multiple epochs, this will be called once per
epoch.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L263)

``` python
async def on_sample_start(self, data: SampleStart) -> None
```

`data` [SampleStart](inspect_ai.hooks.qmd#samplestart)  
Sample start data.

on_sample_end  
On sample end.

Called when a sample has either completed successfully, or when a sample
has errored and has no retries remaining.

If a sample is run for multiple epochs, this will be called once per
epoch.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L276)

``` python
async def on_sample_end(self, data: SampleEnd) -> None
```

`data` [SampleEnd](inspect_ai.hooks.qmd#sampleend)  
Sample end data.

on_model_usage  
Called when a call to a model’s generate() method completes successfully
without hitting Inspect’s local cache.

Note that this is not called when Inspect’s local cache is used and is a
cache hit (i.e. if no external API call was made). Provider-side caching
will result in this being called.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L289)

``` python
async def on_model_usage(self, data: ModelUsageData) -> None
```

`data` [ModelUsageData](inspect_ai.hooks.qmd#modelusagedata)  
Model usage data.

on_model_cache_usage  
Called when a call to a model’s generate() method completes successfully
by hitting Inspect’s local cache.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L301)

``` python
async def on_model_cache_usage(self, data: ModelCacheUsageData) -> None
```

`data` ModelCacheUsageData  
Cached model usage data.

on_sample_scoring  
Called before the sample is scored.

Can be used by hooks to demarcate the end of solver execution and the
start of scoring.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L309)

``` python
async def on_sample_scoring(self, data: SampleScoring) -> None
```

`data` SampleScoring  
Sample scoring data.

override_api_key  
Optionally override an API key.

When overridden, this method may return a new API key value which will
be used in place of the original one during the eval.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L319)

``` python
def override_api_key(self, data: ApiKeyOverride) -> str | None
```

`data` [ApiKeyOverride](inspect_ai.hooks.qmd#apikeyoverride)  
Api key override data.

### hooks

Decorator for registering a hook subscriber.

Either decorate a subclass of `Hooks`, or a function which returns the
type of a subclass of `Hooks`. This decorator will instantiate the hook
class and store it in the registry.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L337)

``` python
def hooks(name: str, description: str) -> Callable[..., Type[T]]
```

`name` str  
Name of the subscriber (e.g. “audit logging”).

`description` str  
Short description of the hook (e.g. “Copies eval files to S3 bucket for
auditing.”).

## Hook Data

### ApiKeyOverride

Api key override hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L176)

``` python
@dataclass(frozen=True)
class ApiKeyOverride
```

#### Attributes

`env_var_name` str  
The name of the environment var containing the API key
(e.g. OPENAI_API_KEY).

`value` str  
The original value of the environment variable.

### ModelUsageData

Model usage hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L135)

``` python
@dataclass(frozen=True)
class ModelUsageData
```

#### Attributes

`model_name` str  
The name of the model that was used.

`usage` [ModelUsage](inspect_ai.model.qmd#modelusage)  
The model usage metrics.

`call_duration` float  
The duration of the model call in seconds. If HTTP retries were made,
this is the time taken for the successful call. This excludes retry
waiting (e.g. exponential backoff) time.

### EvalSetStart

Eval set start hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L22)

``` python
@dataclass(frozen=True)
class EvalSetStart
```

#### Attributes

`eval_set_id` str  
The globally unique identifier for the eval set. Note that the
`eval_set_id` will be stable across multiple invocations of `eval_set()`
for the same log directory

`log_dir` str  
The log directory for the eval set.

### EvalSetEnd

Eval set end event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L34)

``` python
@dataclass(frozen=True)
class EvalSetEnd
```

#### Attributes

`eval_set_id` str  
The globally unique identifier for the eval set. Note that the
`eval_set_id` will be stable across multiple invocations of `eval_set()`
for the same log directory

`log_dir` str  
The log directory for the eval set.

### RunEnd

Run end hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L58)

``` python
@dataclass(frozen=True)
class RunEnd
```

#### Attributes

`eval_set_id` str \| None  
The globally unique identifier for the eval set (if any).

`run_id` str  
The globally unique identifier for the run.

`exception` BaseException \| None  
The exception that occurred during the run, if any. If None, the run
completed successfully.

`logs` EvalLogs  
All eval logs generated during the run. Can be headers only if the run
was an `eval_set()`.

### RunStart

Run start hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L46)

``` python
@dataclass(frozen=True)
class RunStart
```

#### Attributes

`eval_set_id` str \| None  
The globally unique identifier for the eval set (if any).

`run_id` str  
The globally unique identifier for the run.

`task_names` list\[str\]  
The names of the tasks which will be used in the run.

### SampleEnd

Sample end hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L119)

``` python
@dataclass(frozen=True)
class SampleEnd
```

#### Attributes

`eval_set_id` str \| None  
The globally unique identifier for the eval set (if any).

`run_id` str  
The globally unique identifier for the run.

`eval_id` str  
The globally unique identifier for the task execution.

`sample_id` str  
The globally unique identifier for the sample execution.

`sample` [EvalSample](inspect_ai.log.qmd#evalsample)  
The sample that has run.

### SampleStart

Sample start hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L103)

``` python
@dataclass(frozen=True)
class SampleStart
```

#### Attributes

`eval_set_id` str \| None  
The globally unique identifier for the eval set (if any).

`run_id` str  
The globally unique identifier for the run.

`eval_id` str  
The globally unique identifier for the task execution.

`sample_id` str  
The globally unique identifier for the sample execution.

`summary` [EvalSampleSummary](inspect_ai.log.qmd#evalsamplesummary)  
Summary of the sample to be run.

### TaskEnd

Task end hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L88)

``` python
@dataclass(frozen=True)
class TaskEnd
```

#### Attributes

`eval_set_id` str \| None  
The globally unique identifier for the eval set (if any).

`run_id` str  
The globally unique identifier for the run.

`eval_id` str  
The globally unique identifier for the task execution.

`log` [EvalLog](inspect_ai.log.qmd#evallog)  
The log generated for the task. Can be header only if the run was an
`eval_set()`

### TaskStart

Task start hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/81d8689032370a3b30a10fe8e8ac0be5efae8788/src/inspect_ai/hooks/_hooks.py#L74)

``` python
@dataclass(frozen=True)
class TaskStart
```

#### Attributes

`eval_set_id` str \| None  
The globally unique identifier for the eval set (if any).

`run_id` str  
The globally unique identifier for the run.

`eval_id` str  
The globally unique identifier for this task execution.

`spec` [EvalSpec](inspect_ai.log.qmd#evalspec)  
Specification of the task.
