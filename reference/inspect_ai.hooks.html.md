# inspect_ai.hooks

Hook into Inspect lifecycle events.

## Registration

### Hooks

Base class for hooks.

Note that whenever hooks are called, they are wrapped in a try/except block to catch any exceptions that may occur. This is to ensure that a hook failure does not affect the overall execution of the eval. If a hook fails, a warning will be logged.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L315)

``` python
class Hooks
```

#### Methods

enabled  
Check if the hook should be enabled.

Default implementation returns True.

Hooks may wish to override this to e.g. check the presence of an environment variable or a configuration setting.

Will be called frequently, so consider caching the result if the computation is expensive.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L323)

``` python
def enabled(self) -> bool
```

on_eval_set_start  
On eval set start.

A “eval set” is an invocation of [eval_set()](../reference/inspect_ai.html.md#eval_set) for a log directory. Note that the `eval_set_id` will be stable across multiple invocations of [eval_set()](../reference/inspect_ai.html.md#eval_set) for the same log directory.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L336)

``` python
async def on_eval_set_start(self, data: EvalSetStart) -> None
```

`data` [EvalSetStart](../reference/inspect_ai.hooks.html.md#evalsetstart)  
Eval set start data.

on_eval_set_end  
On eval set end.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L348)

``` python
async def on_eval_set_end(self, data: EvalSetEnd) -> None
```

`data` [EvalSetEnd](../reference/inspect_ai.hooks.html.md#evalsetend)  
Eval set end data.

on_run_start  
On run start.

A “run” is a single invocation of [eval()](../reference/inspect_ai.html.md#eval) or [eval_retry()](../reference/inspect_ai.html.md#eval_retry) which may contain many Tasks, each with many Samples and many epochs. Note that [eval_retry()](../reference/inspect_ai.html.md#eval_retry) can be invoked multiple times within an [eval_set()](../reference/inspect_ai.html.md#eval_set).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L356)

``` python
async def on_run_start(self, data: RunStart) -> None
```

`data` [RunStart](../reference/inspect_ai.hooks.html.md#runstart)  
Run start data.

on_run_end  
On run end.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L368)

``` python
async def on_run_end(self, data: RunEnd) -> None
```

`data` [RunEnd](../reference/inspect_ai.hooks.html.md#runend)  
Run end data.

on_task_start  
On task start.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L376)

``` python
async def on_task_start(self, data: TaskStart) -> None
```

`data` [TaskStart](../reference/inspect_ai.hooks.html.md#taskstart)  
Task start data.

on_task_end  
On task end.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L384)

``` python
async def on_task_end(self, data: TaskEnd) -> None
```

`data` [TaskEnd](../reference/inspect_ai.hooks.html.md#taskend)  
Task end data.

on_sample_init  
On sample init.

Called when a sample has been scheduled and is about to begin initialization, before sandbox environments are created. This hook can be used to gate sandbox resource provisioning.

If the sample errors and retries, this will not be called again.

If a sample is run for multiple epochs, this will be called once per epoch.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L392)

``` python
async def on_sample_init(self, data: SampleInit) -> None
```

`data` [SampleInit](../reference/inspect_ai.hooks.html.md#sampleinit)  
Sample init data.

on_sample_start  
On sample start.

Called when a sample is about to be start. If the sample errors and retries, this will not be called again.

If a sample is run for multiple epochs, this will be called once per epoch.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L408)

``` python
async def on_sample_start(self, data: SampleStart) -> None
```

`data` [SampleStart](../reference/inspect_ai.hooks.html.md#samplestart)  
Sample start data.

on_sample_event  
On sample event.

Called when a sample event is emmitted. Pending events are not logged here (i.e. ToolEvent and ModelEvent are not logged until they are complete).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L421)

``` python
async def on_sample_event(self, data: SampleEvent) -> None
```

`data` [SampleEvent](../reference/inspect_ai.hooks.html.md#sampleevent)  
Sample event.

on_sample_end  
On sample end.

Called when a sample has either completed successfully, or when a sample has errored and has no retries remaining.

If a sample is run for multiple epochs, this will be called once per epoch.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L433)

``` python
async def on_sample_end(self, data: SampleEnd) -> None
```

`data` [SampleEnd](../reference/inspect_ai.hooks.html.md#sampleend)  
Sample end data.

on_before_model_generate  
Called before a model’s generate() method is invoked.

This is called after cache lookup (only fires on cache miss) and after model API access verification, right before the actual API call.

Note that this fires inside the retry wrapper, so it will be called on each retry attempt, not just the first.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L446)

``` python
async def on_before_model_generate(self, data: BeforeModelGenerate) -> None
```

`data` BeforeModelGenerate  
Pre-generation data including input messages, tools, and config.

on_sample_attempt_start  
On sample attempt start.

Fired at the beginning of every attempt (including the first). Unlike on_sample_start which fires once per sample, this fires on retries too.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L460)

``` python
async def on_sample_attempt_start(self, data: SampleAttemptStart) -> None
```

`data` [SampleAttemptStart](../reference/inspect_ai.hooks.html.md#sampleattemptstart)  
Sample attempt start data.

on_sample_attempt_end  
On sample attempt end.

Fired at the end of every attempt (including the last). Unlike on_sample_end which fires once per sample, this fires on retries too.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L471)

``` python
async def on_sample_attempt_end(self, data: SampleAttemptEnd) -> None
```

`data` [SampleAttemptEnd](../reference/inspect_ai.hooks.html.md#sampleattemptend)  
Sample attempt end data.

on_model_usage  
Called when a call to a model’s generate() method completes successfully without hitting Inspect’s local cache.

Note that this is not called when Inspect’s local cache is used and is a cache hit (i.e. if no external API call was made). Provider-side caching will result in this being called.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L482)

``` python
async def on_model_usage(self, data: ModelUsageData) -> None
```

`data` [ModelUsageData](../reference/inspect_ai.hooks.html.md#modelusagedata)  
Model usage data.

on_model_cache_usage  
Called when a call to a model’s generate() method completes successfully by hitting Inspect’s local cache.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L494)

``` python
async def on_model_cache_usage(self, data: ModelCacheUsageData) -> None
```

`data` ModelCacheUsageData  
Cached model usage data.

on_sample_scoring  
Called before the sample is scored.

Can be used by hooks to demarcate the end of solver execution and the start of scoring.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L502)

``` python
async def on_sample_scoring(self, data: SampleScoring) -> None
```

`data` SampleScoring  
Sample scoring data.

override_api_key  
Optionally override an API key.

When overridden, this method may return a new API key value which will be used in place of the original one during the eval.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L512)

``` python
def override_api_key(self, data: ApiKeyOverride) -> str | None
```

`data` [ApiKeyOverride](../reference/inspect_ai.hooks.html.md#apikeyoverride)  
Api key override data.

### hooks

Decorator for registering a hook subscriber.

Either decorate a subclass of [Hooks](../reference/inspect_ai.hooks.html.md#hooks), or a function which returns the type of a subclass of [Hooks](../reference/inspect_ai.hooks.html.md#hooks). This decorator will instantiate the hook class and store it in the registry.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L530)

``` python
def hooks(name: str, description: str) -> Callable[..., Type[T]]
```

`name` str  
Name of the subscriber (e.g. “audit logging”).

`description` str  
Short description of the hook (e.g. “Copies eval files to S3 bucket for auditing.”).

## Hook Data

### ApiKeyOverride

Api key override hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L305)

``` python
@dataclass(frozen=True)
class ApiKeyOverride
```

#### Attributes

`env_var_name` str  
The name of the environment var containing the API key (e.g. OPENAI_API_KEY).

`value` str  
The original value of the environment variable.

### ModelUsageData

Model usage hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L226)

``` python
@dataclass(frozen=True)
class ModelUsageData
```

#### Attributes

`model_name` str  
The name of the model that was used.

`usage` [ModelUsage](../reference/inspect_ai.model.html.md#modelusage)  
The model usage metrics.

`call_duration` float  
The duration of the model call in seconds. If HTTP retries were made, this is the time taken for the successful call. This excludes retry waiting (e.g. exponential backoff) time.

`eval_set_id` str \| None  
The globally unique identifier for the eval set (if any).

`run_id` str \| None  
The globally unique identifier for the run (if any).

`eval_id` str \| None  
The globally unique identifier for the task execution (if any).

`task_name` str \| None  
The name of the task that generated this usage (if any).

`retries` int  
The number of HTTP retries made before the successful call.

### EvalSetStart

Eval set start hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L33)

``` python
@dataclass(frozen=True)
class EvalSetStart
```

#### Attributes

`eval_set_id` str  
The globally unique identifier for the eval set. Note that the `eval_set_id` will be stable across multiple invocations of [eval_set()](../reference/inspect_ai.html.md#eval_set) for the same log directory

`log_dir` str  
The log directory for the eval set.

### EvalSetEnd

Eval set end event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L45)

``` python
@dataclass(frozen=True)
class EvalSetEnd
```

#### Attributes

`eval_set_id` str  
The globally unique identifier for the eval set. Note that the `eval_set_id` will be stable across multiple invocations of [eval_set()](../reference/inspect_ai.html.md#eval_set) for the same log directory

`log_dir` str  
The log directory for the eval set.

### RunEnd

Run end hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L69)

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
The exception that occurred during the run, if any. If None, the run completed successfully.

`logs` EvalLogs  
All eval logs generated during the run. Can be headers only if the run was an [eval_set()](../reference/inspect_ai.html.md#eval_set).

### RunStart

Run start hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L57)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L162)

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

`sample` [EvalSample](../reference/inspect_ai.log.html.md#evalsample)  
The sample that has run.

### SampleInit

Sample init hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L114)

``` python
@dataclass(frozen=True)
class SampleInit
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

`summary` [EvalSampleSummary](../reference/inspect_ai.log.html.md#evalsamplesummary)  
Summary of the sample to be initialized.

### SampleStart

Sample start hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L130)

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

`summary` [EvalSampleSummary](../reference/inspect_ai.log.html.md#evalsamplesummary)  
Summary of the sample to be run.

### SampleAttemptStart

Sample attempt start hook event data.

Fired at the beginning of every attempt (including the first). Unlike on_sample_start which fires once per sample, this fires on retries too.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L178)

``` python
@dataclass(frozen=True)
class SampleAttemptStart
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

`summary` [EvalSampleSummary](../reference/inspect_ai.log.html.md#evalsamplesummary)  
Summary of the sample to be run.

`attempt` int  
1-based attempt number.

### SampleAttemptEnd

Sample attempt end hook event data.

Fired at the end of every attempt (including the last). Unlike on_sample_end which fires once per sample, this fires on retries too.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L200)

``` python
@dataclass(frozen=True)
class SampleAttemptEnd
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

`summary` [EvalSampleSummary](../reference/inspect_ai.log.html.md#evalsamplesummary)  
Summary of the sample.

`attempt` int  
1-based attempt number.

`error` [EvalError](../reference/inspect_ai.log.html.md#evalerror) \| None  
The error from this attempt, if any.

`will_retry` bool  
Whether the sample will be retried after this attempt.

### SampleEvent

Sample event hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L146)

``` python
@dataclass(frozen=True)
class SampleEvent
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

`event` Event  
Sample events.

### TaskEnd

Task end hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L99)

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

`log` [EvalLog](../reference/inspect_ai.log.html.md#evallog)  
The log generated for the task. Can be header only if the run was an [eval_set()](../reference/inspect_ai.html.md#eval_set)

### TaskStart

Task start hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/bed324a769a18102a5b56b3c87627e6727d33dab/src/inspect_ai/hooks/_hooks.py#L85)

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

`spec` [EvalSpec](../reference/inspect_ai.log.html.md#evalspec)  
Specification of the task.
