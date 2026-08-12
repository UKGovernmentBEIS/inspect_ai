# inspect_ai.hooks – Inspect

## Registration

### Hooks

Base class for hooks.

Note that whenever hooks are called, they are wrapped in a try/except block to catch any exceptions that may occur. This is to ensure that a hook failure does not affect the overall execution of the eval. If a hook fails, a warning will be logged.

#### Hook lifecycle

The `@hooks` decorator instantiates your class once, at import time, and registers that single instance. Inspect never creates a second instance and never destroys it: the registry holds it for the lifetime of the process, and there is no teardown event. Do per-run cleanup in `on_run_end` or `on_eval_set_end`.

Because there is exactly one instance, `self` is shared by every eval set, run, task, sample and epoch in the process:

- State stored on `self` by one sample is visible to all the others. Key per-sample state by `data.sample_id` and remove it in `on_sample_end`, otherwise it accumulates for the life of the process.
- Samples run concurrently on a single event loop, so a call for one sample can begin at any `await` in an in-flight call for another. Don’t assume one call completes before the next begins. (Within a single sample, `on_sample_event` calls are serialized.)

#### Ownership of hook event data

Event objects passed via `on_sample_event` and the [EvalSample](../reference/inspect_ai.log.html.md#evalsample) passed via `on_sample_end` are owned by the framework. Hook implementations may read these objects and may retain references for inspection, but **must not mutate them in place**. The framework retains references to these objects and may serialize, copy, or further transform them after the hook returns; in-place mutation is undefined behavior. If a hook needs a mutable working copy, call `data.event.model_copy(deep=True)` (or the equivalent on the sample) inside the hook and operate on that copy.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L361)

``` python
class Hooks
```

#### Methods

enabled  
Check if the hook should be enabled.

Default implementation returns True.

Hooks may wish to override this to e.g. check the presence of an environment variable or a configuration setting.

Will be called frequently, so consider caching the result if the computation is expensive.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L399)

``` python
def enabled(self) -> bool
```

on_eval_set_start  
On eval set start.

A “eval set” is an invocation of [eval_set()](../reference/inspect_ai.html.md#eval_set) for a log directory. Note that the `eval_set_id` will be stable across multiple invocations of [eval_set()](../reference/inspect_ai.html.md#eval_set) for the same log directory.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L412)

``` python
async def on_eval_set_start(self, data: EvalSetStart) -> None
```

`data` [EvalSetStart](../reference/inspect_ai.hooks.html.md#evalsetstart)  
Eval set start data.

on_eval_set_end  
On eval set end.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L424)

``` python
async def on_eval_set_end(self, data: EvalSetEnd) -> None
```

`data` [EvalSetEnd](../reference/inspect_ai.hooks.html.md#evalsetend)  
Eval set end data.

on_run_start  
On run start.

A “run” is a single invocation of [eval()](../reference/inspect_ai.html.md#eval) or [eval_retry()](../reference/inspect_ai.html.md#eval_retry) which may contain many Tasks, each with many Samples and many epochs. Note that [eval_retry()](../reference/inspect_ai.html.md#eval_retry) can be invoked multiple times within an [eval_set()](../reference/inspect_ai.html.md#eval_set).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L432)

``` python
async def on_run_start(self, data: RunStart) -> None
```

`data` [RunStart](../reference/inspect_ai.hooks.html.md#runstart)  
Run start data.

on_run_end  
On run end.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L444)

``` python
async def on_run_end(self, data: RunEnd) -> None
```

`data` [RunEnd](../reference/inspect_ai.hooks.html.md#runend)  
Run end data.

on_task_start  
On task start.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L452)

``` python
async def on_task_start(self, data: TaskStart) -> None
```

`data` [TaskStart](../reference/inspect_ai.hooks.html.md#taskstart)  
Task start data.

on_task_end  
On task end.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L460)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L468)

``` python
async def on_sample_init(self, data: SampleInit) -> None
```

`data` [SampleInit](../reference/inspect_ai.hooks.html.md#sampleinit)  
Sample init data.

on_sample_start  
On sample start.

Called when a sample is about to be start. If the sample errors and retries, this will not be called again.

If a sample is run for multiple epochs, this will be called once per epoch.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L484)

``` python
async def on_sample_start(self, data: SampleStart) -> None
```

`data` [SampleStart](../reference/inspect_ai.hooks.html.md#samplestart)  
Sample start data.

on_sample_event  
On sample event.

Called when a sample event is emmitted. Pending events are not logged here (i.e. ToolEvent and ModelEvent are not logged until they are complete).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L497)

``` python
async def on_sample_event(self, data: SampleEvent) -> None
```

`data` [SampleEvent](../reference/inspect_ai.hooks.html.md#sampleevent)  
Sample event.

on_sample_end  
On sample end.

Called when a sample has either completed successfully, or when a sample has errored and has no retries remaining.

If a sample is run for multiple epochs, this will be called once per epoch.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L509)

``` python
async def on_sample_end(self, data: SampleEnd) -> None
```

`data` [SampleEnd](../reference/inspect_ai.hooks.html.md#sampleend)  
Sample end data.

on_before_model_generate  
Called before a model’s generate() method is invoked.

This is called before cache lookup and before model API access verification, so hook mutations to inputs/tools/config are reflected in cache keys and in the actual API call.

Note that this fires inside the retry wrapper, so it will be called on each retry attempt, not just the first.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L522)

``` python
async def on_before_model_generate(self, data: BeforeModelGenerate) -> None
```

`data` BeforeModelGenerate  
Pre-generation data including input messages, tools, and config.

on_model_retry  
Called before a model call is retried after a transient failure.

Fires once per retry (i.e. not for the initial attempt), before the backoff sleep. Useful for surfacing how much time is spent in rate limiting and other retries (see `data.wait_time` for the upcoming backoff duration).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L537)

``` python
async def on_model_retry(self, data: ModelRetry) -> None
```

`data` [ModelRetry](../reference/inspect_ai.hooks.html.md#modelretry)  
Model retry data.

on_sample_attempt_start  
On sample attempt start.

Fired at the beginning of every attempt (including the first). Unlike on_sample_start which fires once per sample, this fires on retries too.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L550)

``` python
async def on_sample_attempt_start(self, data: SampleAttemptStart) -> None
```

`data` [SampleAttemptStart](../reference/inspect_ai.hooks.html.md#sampleattemptstart)  
Sample attempt start data.

on_sample_attempt_end  
On sample attempt end.

Fired at the end of every attempt (including the last). Unlike on_sample_end which fires once per sample, this fires on retries too.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L561)

``` python
async def on_sample_attempt_end(self, data: SampleAttemptEnd) -> None
```

`data` [SampleAttemptEnd](../reference/inspect_ai.hooks.html.md#sampleattemptend)  
Sample attempt end data.

on_model_usage  
Called when a call to a model’s generate() method completes successfully without hitting Inspect’s local cache.

Note that this is not called when Inspect’s local cache is used and is a cache hit (i.e. if no external API call was made). Provider-side caching will result in this being called.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L572)

``` python
async def on_model_usage(self, data: ModelUsageData) -> None
```

`data` [ModelUsageData](../reference/inspect_ai.hooks.html.md#modelusagedata)  
Model usage data.

on_model_cache_usage  
Called when a call to a model’s generate() method completes successfully by hitting Inspect’s local cache.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L584)

``` python
async def on_model_cache_usage(self, data: ModelCacheUsageData) -> None
```

`data` ModelCacheUsageData  
Cached model usage data.

on_sample_scoring  
Called before the sample is scored.

Can be used by hooks to demarcate the end of solver execution and the start of scoring.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L592)

``` python
async def on_sample_scoring(self, data: SampleScoring) -> None
```

`data` SampleScoring  
Sample scoring data.

override_api_key  
Optionally override an API key.

When overridden, this method may return a new API key value which will be used in place of the original one during the eval.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L602)

``` python
def override_api_key(self, data: ApiKeyOverride) -> str | None
```

`data` [ApiKeyOverride](../reference/inspect_ai.hooks.html.md#apikeyoverride)  
Api key override data.

### hooks

Decorator for registering a hook subscriber.

Either decorate a subclass of [Hooks](../reference/inspect_ai.hooks.html.md#hooks), or a function which returns the type of a subclass of [Hooks](../reference/inspect_ai.hooks.html.md#hooks). This decorator will instantiate the hook class and store it in the registry.

Instantiation happens eagerly, when the decorator runs (i.e. when the defining module is imported), and the resulting instance is reused for every event for the lifetime of the process. See [Hooks](../reference/inspect_ai.hooks.html.md#hooks) for what that implies for instance state.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L620)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L351)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L245)

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

### ModelRetry

Model retry hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L310)

``` python
@dataclass(frozen=True)
class ModelRetry
```

#### Attributes

`model_name` str  
The name of the model whose call is being retried.

`attempt` int  
The number of the attempt that just failed (1 for the first failure).

`wait_time` float  
The time in seconds that will be waited (backoff) before the next attempt. This is the time attributable to rate limiting and other transient retries.

`eval_set_id` str \| None  
The globally unique identifier for the eval set (if any).

`run_id` str \| None  
The globally unique identifier for the run (if any).

`eval_id` str \| None  
The globally unique identifier for the task execution (if any).

`sample_id` str \| None  
The globally unique identifier for the sample execution (if any).

`task_name` str \| None  
The name of the task whose model call is being retried (if any).

`exception_type` str \| None  
The type name of the exception that triggered the retry (e.g. “RateLimitError”), if known.

`status_code` int \| None  
The HTTP status code of the failure that triggered the retry (e.g. 429 or 503), if any.

### EvalSetStart

Eval set start hook event data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L39)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L51)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L75)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L63)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L181)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L133)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L149)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L197)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L219)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L165)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L118)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/e72c73f8a514c53ddf55da180e4bedaf8f0362b4/src/inspect_ai/hooks/_hooks.py#L91)

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

Do not mutate: this is the object the recorder holds until the final log write, so changing it here corrupts the written log header.

`plan` [EvalPlan](../reference/inspect_ai.log.html.md#evalplan)  
All solvers that will be run, in order.

Note that a `finish` solver is reported both in `finish` and as the last entry of `steps`, so read one or the other, not both.

Do not mutate: this is the object the recorder holds until the final log write, so changing it here corrupts the written log header.
