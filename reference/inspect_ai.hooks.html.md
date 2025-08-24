# inspect_ai.hooks


## Registration

### Hooks

Base class for hooks.

Note that whenever hooks are called, they are wrapped in a try/except
block to catch any exceptions that may occur. This is to ensure that a
hook failure does not affect the overall execution of the eval. If a
hook fails, a warning will be logged.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L122)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L130)

``` python
def enabled(self) -> bool
```

on_run_start  
On run start.

A “run” is a single invocation of `eval()` or `eval_retry()` which may
contain many Tasks, each with many Samples and many epochs. Note that
`eval_retry()` can be invoked multiple times within an `eval_set()`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L143)

``` python
async def on_run_start(self, data: RunStart) -> None
```

`data` [RunStart](inspect_ai.hooks.qmd#runstart)  
Run start data.

on_run_end  
On run end.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L155)

``` python
async def on_run_end(self, data: RunEnd) -> None
```

`data` [RunEnd](inspect_ai.hooks.qmd#runend)  
Run end data.

on_task_start  
On task start.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L163)

``` python
async def on_task_start(self, data: TaskStart) -> None
```

`data` [TaskStart](inspect_ai.hooks.qmd#taskstart)  
Task start data.

on_task_end  
On task end.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L171)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L179)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L192)

``` python
async def on_sample_end(self, data: SampleEnd) -> None
```

`data` [SampleEnd](inspect_ai.hooks.qmd#sampleend)  
Sample end data.

on_model_usage  
Called when a call to a model’s generate() method completes
successfully.

Note that this is not called when Inspect’s local cache is used and is a
cache hit (i.e. if no external API call was made). Provider-side caching
will result in this being called.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L205)

``` python
async def on_model_usage(self, data: ModelUsageData) -> None
```

`data` [ModelUsageData](inspect_ai.hooks.qmd#modelusagedata)  
Model usage data.

override_api_key  
Optionally override an API key.

When overridden, this method may return a new API key value which will
be used in place of the original one during the eval.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L217)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L235)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L112)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L98)

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

### RunEnd

Run end hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L31)

``` python
@dataclass(frozen=True)
class RunEnd
```

#### Attributes

`run_id` str  
The globally unique identifier for the run.

`exception` Exception \| None  
The exception that occurred during the run, if any. If None, the run
completed successfully.

`logs` EvalLogs  
All eval logs generated during the run. Can be headers only if the run
was an `eval_set()`.

### RunStart

Run start hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L21)

``` python
@dataclass(frozen=True)
class RunStart
```

#### Attributes

`run_id` str  
The globally unique identifier for the run.

`task_names` list\[str\]  
The names of the tasks which will be used in the run.

### SampleEnd

Sample end hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L84)

``` python
@dataclass(frozen=True)
class SampleEnd
```

#### Attributes

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L70)

``` python
@dataclass(frozen=True)
class SampleStart
```

#### Attributes

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L57)

``` python
@dataclass(frozen=True)
class TaskEnd
```

#### Attributes

`run_id` str  
The globally unique identifier for the run.

`eval_id` str  
The globally unique identifier for the task execution.

`log` [EvalLog](inspect_ai.log.qmd#evallog)  
The log generated for the task. Can be header only if the run was an
`eval_set()`

### TaskStart

Task start hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/9b052140425599961a44134a70e49d2b334af98b/src/inspect_ai/hooks/_hooks.py#L45)

``` python
@dataclass(frozen=True)
class TaskStart
```

#### Attributes

`run_id` str  
The globally unique identifier for the run.

`eval_id` str  
The globally unique identifier for this task execution.

`spec` [EvalSpec](inspect_ai.log.qmd#evalspec)  
Specification of the task.
