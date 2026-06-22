# inspect_ai.util – Inspect

## Store

### Store

The [Store](../reference/inspect_ai.util.html.md#store) is used to record state and state changes.

The [TaskState](../reference/inspect_ai.solver.html.md#taskstate) for each sample has a [Store](../reference/inspect_ai.util.html.md#store) which can be used when solvers and/or tools need to coordinate changes to shared state. The [Store](../reference/inspect_ai.util.html.md#store) can be accessed directly from the [TaskState](../reference/inspect_ai.solver.html.md#taskstate) via `state.store` or can be accessed using the [store()](../reference/inspect_ai.util.html.md#store) global function.

Note that changes to the store that occur are automatically recorded to transcript as a [StoreEvent](../reference/inspect_ai.event.html.md#storeevent). In order to be serialised to the transcript, values and objects must be JSON serialisable (you can make objects with several fields serialisable using the `@dataclass` decorator or by inheriting from Pydantic `BaseModel`)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_store.py#L27)

``` python
class Store
```

#### Methods

get  
Get a value from the store.

Provide a `default` to automatically initialise a named store value with the default when it does not yet exist.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_store.py#L53)

``` python
def get(self, key: str, default: VT | None = None) -> VT | Any
```

`key` str  
Name of value to get

`default` VT \| None  
Default value (defaults to `None`)

set  
Set a value into the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_store.py#L71)

``` python
def set(self, key: str, value: Any) -> None
```

`key` str  
Name of value to set

`value` Any  
Value to set

delete  
Remove a value from the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_store.py#L80)

``` python
def delete(self, key: str) -> None
```

`key` str  
Name of value to remove

keys  
View of keys within the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_store.py#L88)

``` python
def keys(self) -> KeysView[str]
```

values  
View of values within the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_store.py#L92)

``` python
def values(self) -> ValuesView[Any]
```

items  
View of items within the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_store.py#L96)

``` python
def items(self) -> ItemsView[str, Any]
```

### store

Get the currently active [Store](../reference/inspect_ai.util.html.md#store).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_store.py#L110)

``` python
def store() -> Store
```

### store_as

Get a Pydantic model interface to the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_store_model.py#L177)

``` python
def store_as(model_cls: Type[SMT], instance: str | None = None) -> SMT
```

`model_cls` Type\[SMT\]  
Pydantic model type (must derive from StoreModel)

`instance` str \| None  
Optional instance name for store (enables multiple instances of a given StoreModel type within a single sample)

### StoreModel

Store backed Pydandic BaseModel.

The model is initialised from a Store, so that Store should either already satisfy the validation constraints of the model OR you should provide Field(default=) annotations for all of your model fields (the latter approach is recommended).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_store_model.py#L8)

``` python
class StoreModel(BaseModel)
```

### store_from_events

Reconstruct a Store by replaying StoreEvent changes.

Uses event_tree() to ensure proper ordering of parallel events. Only processes StoreEvents from root-level spans (which encompass all nested changes) to avoid redundant replay.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_store.py#L143)

``` python
def store_from_events(events: list["Event"]) -> Store
```

`events` list\[Event\]  
List of Event objects (typically from EvalSample.events).

### store_from_events_as

Reconstruct a StoreModel from events.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_store.py#L176)

``` python
def store_from_events_as(
    events: list["Event"],
    model_cls: Type["SMT"],
    instance: str | None = None,
) -> "SMT"
```

`events` list\[Event\]  
List of Event objects.

`model_cls` Type\[SMT\]  
Pydantic model type (must derive from StoreModel).

`instance` str \| None  
Optional instance name for namespaced store keys.

## Limits

### message_limit

Limits the number of messages in a conversation.

The total number of messages in the conversation are compared to the limit (not just “new” messages).

These limits can be stacked.

This relies on “cooperative” checking - consumers must call check_message_limit() themselves whenever the message count is updated.

When a limit is exceeded, a [LimitExceededError](../reference/inspect_ai.util.html.md#limitexceedederror) is raised.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_limit.py#L372)

``` python
def message_limit(limit: int | None) -> _MessageLimit
```

`limit` int \| None  
The maximum conversation length (number of messages) allowed while the context manager is open. A value of None means unlimited messages.

### token_limit

Limits the total number of tokens which can be used.

The counter starts when the context manager is opened and ends when it is closed.

These limits can be stacked.

This relies on “cooperative” checking - consumers must call `check_token_limit()` themselves whenever tokens are consumed.

When a limit is exceeded, a [LimitExceededError](../reference/inspect_ai.util.html.md#limitexceedederror) is raised.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_limit.py#L249)

``` python
def token_limit(limit: int | None) -> _TokenLimit
```

`limit` int \| None  
The maximum number of tokens that can be used while the context manager is open. Tokens used before the context manager was opened are not counted. A value of None means unlimited tokens.

### cost_limit

Limits the total cost (in dollars) which can be used.

The counter starts when the context manager is opened and ends when it is closed.

These limits can be stacked.

This relies on “cooperative” checking - consumers must call `check_cost_limit()` themselves whenever cost is recorded.

When a limit is exceeded, a [LimitExceededError](../reference/inspect_ai.util.html.md#limitexceedederror) is raised.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_limit.py#L329)

``` python
def cost_limit(limit: float | None) -> _CostLimit
```

`limit` float \| None  
The maximum cost (in dollars) that can be used while the context manager is open. A value of None means unlimited cost.

### time_limit

Limits the wall clock time which can elapse.

The timer starts when the context manager is opened and stops when it is closed.

These limits can be stacked.

When a limit is exceeded, the code block is cancelled and a [LimitExceededError](../reference/inspect_ai.util.html.md#limitexceedederror) is raised.

Uses anyio’s cancellation scopes meaning that the operations within the context manager block are cancelled if the limit is exceeded. The [LimitExceededError](../reference/inspect_ai.util.html.md#limitexceedederror) is therefore raised at the level that the [time_limit()](../reference/inspect_ai.util.html.md#time_limit) context manager was opened, not at the level of the operation which caused the limit to be exceeded (e.g. a call to [generate()](../reference/inspect_ai.solver.html.md#generate)). Ensure you handle [LimitExceededError](../reference/inspect_ai.util.html.md#limitexceedederror) at the level of opening the context manager.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_limit.py#L499)

``` python
def time_limit(limit: float | None) -> _TimeLimit
```

`limit` float \| None  
The maximum number of seconds that can pass while the context manager is open. A value of None means unlimited time.

### working_limit

Limits the working time which can elapse.

Working time is the wall clock time minus any waiting time e.g. waiting before retrying in response to rate limits or waiting on a semaphore.

The timer starts when the context manager is opened and stops when it is closed.

These limits can be stacked.

When a limit is exceeded, a [LimitExceededError](../reference/inspect_ai.util.html.md#limitexceedederror) is raised.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_limit.py#L522)

``` python
def working_limit(limit: float | None) -> _WorkingLimit
```

`limit` float \| None  
The maximum number of seconds of working that can pass while the context manager is open. A value of None means unlimited time.

### apply_limits

Apply a list of limits within a context manager.

Optionally catches any [LimitExceededError](../reference/inspect_ai.util.html.md#limitexceedederror) raised by the applied limits, while allowing other limit errors from any other scope (e.g. the Sample level) to propagate.

Yields a `LimitScope` object which can be used once the context manager is closed to determine which, if any, limits were exceeded.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_limit.py#L128)

``` python
@contextmanager
def apply_limits(
    limits: list[Limit], catch_errors: bool = False
) -> Iterator[LimitScope]
```

`limits` list\[[Limit](../reference/inspect_ai.util.html.md#limit)\]  
List of limits to apply while the context manager is open. Should a limit be exceeded, a [LimitExceededError](../reference/inspect_ai.util.html.md#limitexceedederror) is raised.

`catch_errors` bool  
If True, catch any [LimitExceededError](../reference/inspect_ai.util.html.md#limitexceedederror) raised by the applied limits. Callers can determine whether any limits were exceeded by checking the limit_error property of the `LimitScope` object yielded by this function. If False, all [LimitExceededError](../reference/inspect_ai.util.html.md#limitexceedederror) exceptions will be allowed to propagate.

### sample_limits

Get the top-level limits applied to the current [Sample](../reference/inspect_ai.dataset.html.md#sample).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_limit.py#L203)

``` python
def sample_limits() -> SampleLimits
```

### SampleLimits

Data class to hold the limits applied to a Sample.

This is used to return the limits from [sample_limits()](../reference/inspect_ai.util.html.md#sample_limits).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_limit.py#L177)

``` python
@dataclass
class SampleLimits
```

#### Attributes

`token` [Limit](../reference/inspect_ai.util.html.md#limit)  
Token limit.

`cost` [Limit](../reference/inspect_ai.util.html.md#limit)  
Cost limit.

`message` [Limit](../reference/inspect_ai.util.html.md#limit)  
Message limit.

`turn` [Limit](../reference/inspect_ai.util.html.md#limit)  
Turn limit.

`working` [Limit](../reference/inspect_ai.util.html.md#limit)  
Working limit.

`time` [Limit](../reference/inspect_ai.util.html.md#limit)  
Time limit.

### Limit

Base class for all limit context managers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_limit.py#L75)

``` python
class Limit(abc.ABC)
```

#### Attributes

`limit` float \| None  
The value of the limit being applied.

Can be None which represents no limit.

`usage` float  
The current usage of the resource being limited.

`remaining` float \| None  
The remaining “unused” amount of the resource being limited.

Returns None if the limit is None.

### LimitExceededError

Exception raised when a limit is exceeded.

In some scenarios this error may be raised when `value >= limit` to prevent another operation which is guaranteed to exceed the limit from being wastefully performed.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_limit.py#L26)

``` python
class LimitExceededError(Exception)
```

### suspend_token_limit

Suspend token limit metering within a block of code.

While this context manager is open:

- Token usage is not recorded against any active [token_limit()](../reference/inspect_ai.util.html.md#token_limit) scope (including sample-level, agent-scoped, and arbitrary block limits).
- Calls to `check_token_limit()` are no-ops.
- This applies to any [token_limit()](../reference/inspect_ai.util.html.md#token_limit) contexts opened inside the block as well — suspension wins over nested limits.

Useful for running code whose token usage should not count against an agent’s budget, e.g. one-shot summarization, routing, or auxiliary planning calls.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_limit.py#L301)

``` python
def suspend_token_limit() -> AbstractContextManager[None]
```

## Concurrency

### concurrency

Concurrency context manager.

A concurrency context can be used to limit the number of coroutines executing a block of code (e.g calling an API). For example, here we limit concurrent calls to an api (‘api-name’) to 10:

``` python
async with concurrency("api-name", 10):
    # call the api
```

Note that concurrency for model API access is handled internally via the `max_connections` generation config option. Concurrency for launching subprocesses is handled via the `subprocess` function.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_concurrency.py#L239)

``` python
@contextlib.asynccontextmanager
async def concurrency(
    name: str,
    concurrency: int,
    key: str | None = None,
    visible: bool = True,
    adaptive: AdaptiveConcurrency | None = None,
) -> AsyncIterator[ConcurrencySemaphore]
```

`name` str  
Name for concurrency context. This serves as the display name for the context, and also the unique context key (if the `key` parameter is omitted)

`concurrency` int  
Maximum number of coroutines that can enter the context (ignored if `adaptive` is set).

`key` str \| None  
Unique context key for this context. Optional. Used if the unique key isn’t human readable – e.g. includes api tokens or account ids so that the more readable `name` can be presented to users e.g in console UI\>

`visible` bool  
Should context utilization be visible in the status bar.

`adaptive` [AdaptiveConcurrency](../reference/inspect_ai.util.html.md#adaptiveconcurrency) \| None  
When set, creates an adaptive controller managing a CapacityLimiter that scales between `adaptive.min` and `adaptive.max` based on retry feedback.

### subprocess

Execute and wait for a subprocess.

Convenience method for solvers, scorers, and tools to launch subprocesses. Automatically enforces a limit on concurrent subprocesses (defaulting to os.cpu_count() but controllable via the `max_subprocesses` eval config option).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_subprocess.py#L74)

``` python
async def subprocess(
    args: str | list[str],
    text: bool = True,
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    output_limit: int | None = None,
    timeout: int | None = None,
    concurrency: bool = True,
) -> Union[ExecResult[str], ExecResult[bytes]]
```

`args` str \| list\[str\]  
Command and arguments to execute.

`text` bool  
Return stdout and stderr as text (defaults to True)

`input` str \| bytes \| memoryview \| None  
Optional stdin for subprocess.

`cwd` str \| Path \| None  
Switch to directory for execution.

`env` dict\[str, str\] \| None  
Additional environment variables.

`capture_output` bool  
Capture stderr and stdout into ExecResult (if False, then output is redirected to parent stderr/stdout or to logging if INSPECT_SUBPROCESS_REDIRECT_TO_LOGGER is set)

`output_limit` int \| None  
Maximum bytes to retain from stdout/stderr. If output exceeds this limit, only the most recent bytes are kept (older output is discarded). The process continues to completion.

`timeout` int \| None  
Timeout. If the timeout expires then a `TimeoutError` will be raised.

`concurrency` bool  
Request that the [concurrency()](../reference/inspect_ai.util.html.md#concurrency) function is used to throttle concurrent subprocesses.

### ExecResult

Execution result from call to [subprocess()](../reference/inspect_ai.util.html.md#subprocess).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_subprocess.py#L28)

``` python
@dataclass
class ExecResult(Generic[T])
```

#### Attributes

`success` bool  
Did the process exit with success.

`returncode` int  
Return code from process exit.

`stdout` T  
Contents of stdout.

`stderr` T  
Contents of stderr.

### AdaptiveConcurrency

Bounds and tuning for an adaptive concurrency controller.

Basic fields (`min`, `start`, `max`) bound the range the controller will scale within. Advanced fields (`cooldown_seconds`, `decrease_factor`, `scale_up_percent`) tune the response curve and have sensible defaults for typical evaluation workloads — see the parallelism docs for guidance. Accepts a string shorthand (“min-max” or “min-start-max”) for use in CLI flags and config files; advanced fields are Python-only.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_concurrency.py#L22)

``` python
class AdaptiveConcurrency(BaseModel)
```

#### Attributes

`min` int  
Minimum concurrency (must be \>= 1).

`max` int  
Maximum concurrency.

`start` int  
Starting concurrency (must be within \[min, max\]).

`cooldown_seconds` float  
Minimum seconds between scale-down cuts. The server’s `Retry-After` header (or the `x-ratelimit-reset-*` family as a fallback) extends this when larger.

`decrease_factor` float  
Multiplicative cut applied on each rate-limit episode (must be in (0, 1)).

`scale_up_percent` float  
Steady-state additive growth per clean round, as a fraction of current limit (must be in (0, 1\]).

## Display

### display_counter

Display a counter in the UI.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_display.py#L74)

``` python
def display_counter(caption: str, value: str) -> None
```

`caption` str  
The counter’s caption e.g. “HTTP rate limits”.

`value` str  
The counter’s value e.g. “42”.

### display_type

Get the current console display type.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_display.py#L47)

``` python
def display_type() -> DisplayType
```

### DisplayType

Console display type.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_display.py#L11)

``` python
DisplayType = Literal["full", "conversation", "rich", "plain", "log", "none"]
```

## Utilities

### span

Context manager for establishing a transcript span.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_span.py#L55)

``` python
@contextlib.asynccontextmanager
async def span(
    name: str, *, type: str | None = None, id: str | None = None
) -> AsyncIterator[None]
```

`name` str  
Step name.

`type` str \| None  
Optional span type.

`id` str \| None  
Optional span ID. Generated if not provided. If a span-ID provider is active (`set_span_id_provider`), it is consulted with `(name, parent_id, requested_id)` instead of generating a UUID.

### current_span_id

Return the current span id (if any).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_span.py#L116)

``` python
def current_span_id() -> str | None
```

### span_id_provider

Set the span-ID provider for the duration of the context.

When set, every [span()](../reference/inspect_ai.util.html.md#span) call consults `await provider(name, parent_id, requested_id)` to determine the span id (any explicit `id` argument is passed through as `requested_id`).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_span.py#L122)

``` python
@contextlib.contextmanager
def span_id_provider(provider: SpanIdProvider | None) -> Iterator[None]
```

`provider` SpanIdProvider \| None  

### collect

Run and collect the results of one or more async coroutines.

Similar to [`asyncio.gather()`](https://docs.python.org/3/library/asyncio-task.html#asyncio.gather), but also works when [Trio](https://trio.readthedocs.io/en/stable/) is the async backend.

Automatically includes each task in a [span()](../reference/inspect_ai.util.html.md#span), which ensures that its events are grouped together in the transcript.

Using [collect()](../reference/inspect_ai.util.html.md#collect) in preference to `asyncio.gather()` is highly recommended for both Trio compatibility and more legible transcript output.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_collect.py#L13)

``` python
async def collect(*tasks: Awaitable[T]) -> list[T]
```

`*tasks` Awaitable\[T\]  
Tasks to run

### throttle

Throttle a function with trailing-edge semantics.

When calls arrive faster than the throttle window: - The first call fires immediately (no previous window to trail from). - Subsequent calls within the window are saved, not fired. - When the window expires, the most recently saved call fires. - The call that triggers the window expiry does NOT fire immediately; instead it becomes the new pending call for the next window while the previously pending call fires.

After an idle period (no calls for \>= window), the next call fires immediately since there is no pending call to trail.

The return value is always the result of the most recent actual invocation. When a call is throttled (not fired), the previous invocation’s result is returned.

Behavior depends on whether an async context is active:

With async context: a background task fires the trailing event after the window expires, so pending events are never lost.

Without async context: pending args are saved but only fire on the next call that arrives after the window expires. If no further call is made, the final trailing event is lost.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_throttle.py#L19)

``` python
def throttle(seconds: float) -> Callable[[Callable[P, R]], Callable[P, R]]
```

`seconds` float  
Throttle window in seconds.

### background

Run an async function in the background of the current sample.

Background functions must be run from an executing sample. The function will run as long as the current sample is running.

When the sample terminates, an anyio cancelled error will be raised in the background function. To catch this error and cleanup:

``` python
import anyio

async def run():
    try:
        # background code
    except anyio.get_cancelled_exc_class():
        ...
```

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_background.py#L19)

``` python
def background(
    func: Callable[[Unpack[PosArgsT]], Awaitable[Any]],
    args: Unpack[PosArgsT] = ...,
) -> None
```

`func` Callable\[\[Unpack\[PosArgsT\]\], Awaitable\[Any\]\]  
Async function to run

`*args` Unpack\[PosArgsT\]  
Optional function arguments.

### trace_action

Trace a long running or poentially unreliable action.

Trace actions for which you want to collect data on the resolution (e.g. succeeded, cancelled, failed, timed out, etc.) and duration of.

Traces are written to the `TRACE` log level (which is just below `HTTP` and `INFO`). List and read trace logs with `inspect trace list` and related commands (see `inspect trace --help` for details).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/_util/trace.py#L42)

``` python
@contextmanager
def trace_action(
    logger: Logger, action: str, message: str, *args: Any, **kwargs: Any
) -> Generator[None, None, None]
```

`logger` Logger  
Logger to use for tracing (e.g. from `getLogger(__name__)`)

`action` str  
Name of action to trace (e.g. ‘Model’, ‘Subprocess’, etc.)

`message` str  
Message describing action (can be a format string w/ args or kwargs)

`*args` Any  
Positional arguments for `message` format string.

`**kwargs` Any  
Named args for `message` format string.

### trace_message

Log a message using the TRACE log level.

The `TRACE` log level is just below `HTTP` and `INFO`). List and read trace logs with `inspect trace list` and related commands (see `inspect trace --help` for details).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/_util/trace.py#L140)

``` python
def trace_message(
    logger: Logger, category: str, message: str, *args: Any, **kwargs: Any
) -> None
```

`logger` Logger  
Logger to use for tracing (e.g. from `getLogger(__name__)`)

`category` str  
Category of trace message.

`message` str  
Trace message (can be a format string w/ args or kwargs)

`*args` Any  
Positional arguments for `message` format string.

`**kwargs` Any  
Named args for `message` format string.

### media_resolver

Context manager for registering a media URI resolver.

Registers a resolver scoped to the current context for resolving custom URI schemes in media content (images, audio, video). Stack-safe for nested use with the same scheme.

Note: The resolver is called at most once per URI. The returned value is not re-resolved, so returning another custom scheme URI will not trigger additional resolver lookups.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/_util/images.py#L37)

``` python
@contextmanager
def media_resolver(
    scheme: str,
    resolver: MediaResolverFunc,
) -> Iterator[None]
```

`scheme` str  
URI scheme (e.g., “s3”, “gs”).

`resolver` MediaResolverFunc  
Async function taking a URI and returning a resolved path, URL, or data URI.

### resource

Read and resolve a resource to a string.

Resources are often used for templates, configuration, etc. They are sometimes hard-coded strings, and sometimes paths to external resources (e.g. in the local filesystem or remote stores e.g. s3:// or <https://>).

The [resource()](../reference/inspect_ai.util.html.md#resource) function will resolve its argument to a resource string. If a protocol-prefixed file name (e.g. s3://) or the path to a local file that exists is passed then it will be read and its contents returned. Otherwise, it will return the passed `str` directly This function is mostly intended as a helper for other functions that take either a string or a resource path as an argument, and want to easily resolve them to the underlying content.

If you want to ensure that only local or remote files are consumed, specify `type="file"`. For example: `resource("templates/prompt.txt", type="file")`

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_resource.py#L8)

``` python
def resource(
    resource: str,
    type: Literal["auto", "file"] = "auto",
    fs_options: dict[str, Any] = {},
) -> str
```

`resource` str  
Path to local or remote (e.g. s3://) resource, or for `type="auto"` (the default), a string containing the literal resource value.

`type` Literal\['auto', 'file'\]  
For “auto” (the default), interpret the resource as a literal string if its not a valid path. For “file”, always interpret it as a file path.

`fs_options` dict\[str, Any\]  
Optional. Additional arguments to pass through to the `fsspec` filesystem provider (e.g. `S3FileSystem`). Use `{"anon": True }` if you are accessing a public S3 bucket with no credentials.

### download

Download a file and verify its SHA256 checksum.

If `dest` already exists and its checksum matches, the download is skipped. Retries on transient HTTP errors (408, 429, 5xx) with exponential backoff; gives up immediately on other 4xx responses.

The download is streamed to a sibling tempfile and atomically renamed to `dest` only after the checksum has been verified, so a failed or corrupted download never leaves a partial file at `dest`. Two processes targeting the same `dest` are safe under last-write-wins semantics; no locking is performed.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/_util/download.py#L36)

``` python
def download(
    url: str,
    sha256: str,
    dest: Path,
    *,
    headers: dict[str, str] | None = None,
) -> Path
```

`url` str  
URL to download from.

`sha256` str  
Expected SHA256 hex digest of the file contents.

`dest` Path  
Destination path. Parent directory is created if missing.

`headers` dict\[str, str\] \| None  
Optional HTTP headers to include with the request.

### gdrive_download

Download a Google Drive file via `gdown` and verify SHA256.

Useful for fetching public-link Google Drive assets (datasets, zipped corpora) without OAuth. Requires the optional `gdown` dependency:

    pip install gdown

Skip-if-checksum-matches and atomic-write semantics are identical to [download()](../reference/inspect_ai.util.html.md#download).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/_util/download.py#L107)

``` python
def gdrive_download(file_id: str, sha256: str, dest: Path) -> Path
```

`file_id` str  
Google Drive file id.

`sha256` str  
Expected SHA256 hex digest of the file contents.

`dest` Path  
Destination path. Parent directory is created if missing.

## Sandbox

### sandbox

Get the SandboxEnvironment for the current sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/context.py#L41)

``` python
def sandbox(name: str | None = None) -> SandboxEnvironment
```

`name` str \| None  
Optional sandbox environment name.

### sandbox_with

Get the SandboxEnvironment for the current sample that has the specified file.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/context.py#L71)

``` python
async def sandbox_with(
    file: str, on_path: bool = False, *, name: str | None = None
) -> SandboxEnvironment | None
```

`file` str  
Path to file to check for if on_path is False. If on_path is True, file should be a filename that exists on the system path.

`on_path` bool  
If True, file is a filename to be verified using “which”. If False, file is a path to be checked within the sandbox environments.

`name` str \| None  
Optional sandbox environment name.

### sandbox_default

Set the default sandbox environment for the current context.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/context.py#L381)

``` python
@contextmanager
def sandbox_default(name: str) -> Iterator[None]
```

`name` str  
Sandbox to set as the default.

### SandboxEnvironment

Environment for executing arbitrary code from tools.

Sandbox environments provide both an execution environment as well as a per-sample filesystem context to copy samples files into and resolve relative paths to.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L92)

``` python
class SandboxEnvironment(abc.ABC)
```

#### Methods

exec  
Execute a command within a sandbox environment.

The current working directory for execution will be the per-sample filesystem context.

By default, each output stream (stdout and stderr) is limited to 10 MiB. You can override this by setting the `INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE` environment variable (specified in bytes). If exceeded, an `OutputLimitExceededError` will be raised.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L104)

``` python
@abc.abstractmethod
async def exec(
    self,
    cmd: list[str],
    input: str | bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    user: str | None = None,
    timeout: int | None = None,
    timeout_retry: bool = True,
    concurrency: bool = True,
) -> ExecResult[str]
```

`cmd` list\[str\]  
Command or command and arguments to execute.

`input` str \| bytes \| None  
Standard input (optional).

`cwd` str \| None  
Current working dir (optional). If relative, will be relative to the per-sample filesystem context.

`env` dict\[str, str\] \| None  
Environment variables for execution.

`user` str \| None  
Optional username or UID to run the command as.

`timeout` int \| None  
Optional execution timeout (seconds).

`timeout_retry` bool  
Retry the command in the case that it times out. Commands will be retried up to twice, with a timeout of no greater than 60 seconds for the first retry and 30 for the second.

`concurrency` bool  
For sandboxes that run locally, request that the [concurrency()](../reference/inspect_ai.util.html.md#concurrency) function be used to throttle concurrent subprocesses.

write_file  
Write a file into the sandbox environment.

If the parent directories of the file path do not exist they should be automatically created.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L151)

``` python
@abc.abstractmethod
async def write_file(self, file: str, contents: str | bytes) -> None
```

`file` str  
Path to file (relative file paths will resolve to the per-sample working directory).

`contents` str \| bytes  
Text or binary file contents.

read_file  
Read a file from the sandbox environment.

By default, file size is limited to 100 MiB. You may change this by setting the `INSPECT_SANDBOX_MAX_READ_FILE_SIZE` environment variable (specified in bytes). If exceeded, an `OutputLimitExceededError` will be raised.

When reading text files, implementations should preserve newline constructs (e.g. crlf should be preserved not converted to lf). This is equivalent to specifying `newline=""` in a call to the Python `open()` function.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L178)

``` python
@abc.abstractmethod
async def read_file(self, file: str, text: bool = True) -> Union[str | bytes]
```

`file` str  
Path to file (relative file paths will resolve to the per-sample working directory).

`text` bool  
Read as a utf-8 encoded text file.

connection  
Information required to connect to sandbox environment.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L210)

``` python
async def connection(self, *, user: str | None = None) -> SandboxConnection
```

`user` str \| None  
User to login as.

exec_remote  
Start a command and return a process handle or result.

In streaming mode (stream=True), the function returns only after the process has been successfully launched in the sandbox. The returned ExecRemoteProcess handle can then be iterated for output events or killed later.

Both modes support automatic cleanup on cancellation: if the calling task is cancelled (e.g., via task group cancellation), the subprocess is automatically killed before the cancellation exception propagates.

Usage patterns:

1.  Streaming (stream=True, default): iterate over events

    ``` python
    proc = await sandbox.exec_remote(["pytest", "-v"])
    async for event in proc:
        match event:
            case ExecStdout(data=data): print(data, end="")
            case ExecStderr(data=data): print(data, end="", file=sys.stderr)
            case ExecCompleted(exit_code=code): print(f"Done: {code}")
    ```

2.  Fire-and-forget with explicit kill:

    ``` python
    proxy = await sandbox.exec_remote(["./model-proxy"])
    # ... do other work ...
    await proxy.kill()  # terminate when done
    ```

3.  Simple await (stream=False): get result without streaming

    ``` python
    result = await sandbox.exec_remote(["pytest", "-v"], stream=False)
    if result.success:
        print(result.stdout)
    ```

4.  Long-running process with automatic cleanup via task cancellation:

    ``` python
    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)  # uses exec_remote(..., stream=False)
        yield  # do work while server runs
        tg.cancel_scope.cancel()  # server killed automatically
    ```

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L243)

``` python
async def exec_remote(
    self,
    cmd: list[str],
    options: ExecRemoteStreamingOptions | ExecRemoteAwaitableOptions | None = None,
    *,
    stream: bool = True,
) -> ExecRemoteProcess | ExecResult[str]
```

`cmd` list\[str\]  
Command and arguments to execute.

`options` [ExecRemoteStreamingOptions](../reference/inspect_ai.util.html.md#execremotestreamingoptions) \| [ExecRemoteAwaitableOptions](../reference/inspect_ai.util.html.md#execremoteawaitableoptions) \| None  
Execution options (see ExecRemoteOptions).

`stream` bool  
If True (default), returns ExecRemoteProcess for streaming. If False, returns ExecResult\[str\] directly.

as_type  
Verify and return a reference to a subclass of SandboxEnvironment.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L322)

``` python
def as_type(self, sandbox_cls: Type[ST]) -> ST
```

`sandbox_cls` Type\[ST\]  
Class of sandbox (subclass of SandboxEnvironment)

default_polling_interval  
Polling interval for sandbox service requests.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L341)

``` python
def default_polling_interval(self) -> float
```

default_concurrency  
Default max_sandboxes for this provider (`None` means no maximum)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L345)

``` python
@classmethod
def default_concurrency(cls) -> int | None
```

task_init  
Called at task startup initialize resources.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L350)

``` python
@classmethod
async def task_init(
    cls, task_name: str, config: SandboxEnvironmentConfigType | None
) -> None
```

`task_name` str  
Name of task using the sandbox environment.

`config` SandboxEnvironmentConfigType \| None  
Implementation defined configuration (optional).

task_init_environment  
Called at task startup to identify environment variables required by task_init for a sample.

Return 1 or more environment variables to request a dedicated call to task_init for samples that have exactly these environment variables (by default there is only one call to task_init for all of the samples in a task if they share a sandbox configuration).

This is useful for situations where config files are dynamic (e.g. through sample metadata variable interpolation) and end up yielding different images that need their own init (e.g. ‘docker pull’).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L362)

``` python
@classmethod
async def task_init_environment(
    cls, config: SandboxEnvironmentConfigType | None, metadata: dict[str, str]
) -> dict[str, str]
```

`config` SandboxEnvironmentConfigType \| None  
Implementation defined configuration (optional).

`metadata` dict\[str, str\]  
metadata: Sample `metadata` field

sample_init  
Initialize sandbox environments for a sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L386)

``` python
@classmethod
async def sample_init(
    cls,
    task_name: str,
    config: SandboxEnvironmentConfigType | None,
    metadata: dict[str, str],
) -> dict[str, "SandboxEnvironment"]
```

`task_name` str  
Name of task using the sandbox environment.

`config` SandboxEnvironmentConfigType \| None  
Implementation defined configuration (optional).

`metadata` dict\[str, str\]  
Sample `metadata` field

sample_cleanup  
Cleanup sandbox environments.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L407)

``` python
@classmethod
@abc.abstractmethod
async def sample_cleanup(
    cls,
    task_name: str,
    config: SandboxEnvironmentConfigType | None,
    environments: dict[str, "SandboxEnvironment"],
    interrupted: bool,
) -> None
```

`task_name` str  
Name of task using the sandbox environment.

`config` SandboxEnvironmentConfigType \| None  
Implementation defined configuration (optional).

`environments` dict\[str, 'SandboxEnvironment'\]  
Sandbox environments created for this sample.

`interrupted` bool  
Was the task interrupted by an error or cancellation

task_cleanup  
Called at task exit as a last chance to cleanup resources.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L426)

``` python
@classmethod
async def task_cleanup(
    cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
) -> None
```

`task_name` str  
Name of task using the sandbox environment.

`config` SandboxEnvironmentConfigType \| None  
Implementation defined configuration (optional).

`cleanup` bool  
Whether to actually cleanup environment resources (False if `--no-sandbox-cleanup` was specified)

cli_cleanup  
Handle a cleanup invoked from the CLI (e.g. inspect sandbox cleanup).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L440)

``` python
@classmethod
async def cli_cleanup(cls, id: str | None) -> None
```

`id` str \| None  
Optional ID to limit scope of cleanup.

config_files  
Standard config files for this provider (used for automatic discovery)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L449)

``` python
@classmethod
def config_files(cls) -> list[str]
```

is_docker_compatible  
Is the provider docker compatible (accepts Dockerfile and compose.yaml)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L454)

``` python
@classmethod
def is_docker_compatible(cls) -> bool
```

config_deserialize  
Deserialize a sandbox-specific configuration model from a dict.

Override this method if you support a custom configuration model.

A basic implementation would be: `return MySandboxEnvironmentConfig(**config)`

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L459)

``` python
@classmethod
def config_deserialize(cls, config: dict[str, Any]) -> BaseModel
```

`config` dict\[str, Any\]  
Configuration dictionary produced by serializing the configuration model.

### SandboxConnection

Information required to connect to sandbox.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/environment.py#L73)

``` python
class SandboxConnection(BaseModel)
```

#### Attributes

`type` str  
Sandbox type name (e.g. ‘docker’, ‘local’, etc.)

`command` str  
Shell command to connect to sandbox.

`vscode_command` list\[Any\] \| None  
Optional vscode command (+args) to connect to sandbox.

`ports` list\[PortMapping\] \| None  
Optional list of port mappings into container

`container` str \| None  
Optional container name (does not apply to all sandboxes).

### sandboxenv

Decorator for registering sandbox environments.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/registry.py#L24)

``` python
def sandboxenv(name: str) -> Callable[..., Type[T]]
```

`name` str  
Name of SandboxEnvironment type

### sandbox_service

Run a service that is callable from within a sandbox.

The service makes available a set of methods to a sandbox for calling back into the main Inspect process.

To use the service from within a sandbox, either add it to the sys path or use importlib. For example, if the service is named ‘foo’:

``` python
import sys
sys.path.append("/var/tmp/sandbox-services/foo")
import foo
```

Or:

``` python
import importlib.util
spec = importlib.util.spec_from_file_location(
    "foo", "/var/tmp/sandbox-services/foo/foo.py"
)
foo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(foo)
```

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/service.py#L85)

``` python
async def sandbox_service(
    name: str,
    methods: list[SandboxServiceMethod] | dict[str, SandboxServiceMethod],
    until: Callable[[], bool],
    sandbox: SandboxEnvironment,
    user: str | None = None,
    instance: str | None = None,
    polling_interval: float | None = None,
    started: anyio.Event | None = None,
    requires_python: bool = True,
    handle_requests: bool = True,
) -> None | Callable[[], Awaitable[None]]
```

`name` str  
Service name

`methods` list\[SandboxServiceMethod\] \| dict\[str, SandboxServiceMethod\]  
Service methods.

`until` Callable\[\[\], bool\]  
Function used to check whether the service should stop.

`sandbox` [SandboxEnvironment](../reference/inspect_ai.util.html.md#sandboxenvironment)  
Sandbox to publish service to.

`user` str \| None  
User to login as. Defaults to the sandbox environment’s default user.

`instance` str \| None  
If you want multiple instances of a service in a single sandbox then use the `instance` param.

`polling_interval` float \| None  
Polling interval for request checking. If not specified uses sandbox specific default (2 seconds if not specified, 0.2 seconds for Docker).

`started` anyio.Event \| None  
Event to set when service has been started

`requires_python` bool  
Does the sandbox service require Python? Note that ALL sandbox services require Python unless they’ve injected an alternate implementation of the sandbox service client code.

`handle_requests` bool  
If `True` (the default), handle requests immediately – will run so long as until() returns `True`. If `False`, returns an async function which can be called to handle requests.

### ExecRemoteProcess

Handle to a running exec_remote process.

This class is an async iterator that yields events as they arrive. It can only be iterated once (single-use iterator pattern).

Usage patterns:

1.  Streaming: iterate over the process directly

    ``` python
    proc = await sandbox.exec_remote(["cmd"])
    async for event in proc:
        match event:
            case ExecStdout(data=data): print(data)
            case ExecCompleted(exit_code=code): print(f"Done: {code}")
    ```

2.  Fire-and-forget with explicit kill:

    ``` python
    proxy = await sandbox.exec_remote(["./proxy"])
    # ... do other work ...
    await proxy.kill()  # terminate when done
    ```

3.  Interactive stdin (requires stdin_open=True):

    ``` python
    opts = ExecRemoteStreamingOptions(stdin_open=True)
    proc = await sandbox.exec_remote(["cat"], opts)
    await proc.write_stdin("hello\n")
    await proc.write_stdin("world\n")
    await proc.close_stdin()  # signal EOF
    async for event in proc:
        ...
    ```

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/exec_remote.py#L199)

``` python
class ExecRemoteProcess
```

#### Attributes

`pid` int  
Return the process ID.

#### Methods

\_\_init\_\_  
Initialize an ExecRemoteProcess.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/exec_remote.py#L235)

``` python
def __init__(
    self,
    sandbox: SandboxEnvironment,
    cmd: list[str],
    options: ExecRemoteStreamingOptions | ExecRemoteCommonOptions,
    sandbox_default_poll_interval: float,
) -> None
```

`sandbox` [SandboxEnvironment](../reference/inspect_ai.util.html.md#sandboxenvironment)  
The sandbox environment where the process will run.

`cmd` list\[str\]  
Command and arguments to execute.

`options` [ExecRemoteStreamingOptions](../reference/inspect_ai.util.html.md#execremotestreamingoptions) \| ExecRemoteCommonOptions  
Execution options.

`sandbox_default_poll_interval` float  
Default poll interval in seconds, provided by the sandbox (e.g. from \_default_poll_interval()).

write_stdin  
Write data to the process’s stdin.

Requires that the process was started with stdin_open=True in ExecRemoteStreamingOptions.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/exec_remote.py#L438)

``` python
async def write_stdin(self, data: str | bytes) -> None
```

`data` str \| bytes  
Data to write. Bytes are decoded to UTF-8.

close_stdin  
Close the process’s stdin to signal EOF.

Requires that the process was started with stdin_open=True in ExecRemoteStreamingOptions. Idempotent: calling after stdin is already closed is a no-op.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/exec_remote.py#L474)

``` python
async def close_stdin(self) -> None
```

kill  
Terminate the process.

Any output buffered since the last poll is enqueued as pending events so the async iterator can yield them before StopAsyncIteration.

If the process has already completed or been killed, this is a no-op.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/exec_remote.py#L505)

``` python
async def kill(self) -> None
```

### ExecRemoteStreamingOptions

Options for exec_remote() in streaming mode (stream=True).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/exec_remote.py#L123)

``` python
@dataclass
class ExecRemoteStreamingOptions(ExecRemoteCommonOptions)
```

#### Attributes

`input` str \| bytes \| None  
Standard input to send to the command

`cwd` str \| None  
Working directory for command execution

`env` dict\[str, str\] \| None  
Additional environment variables

`user` str \| None  
User to run the command as

`poll_interval` float \| None  
Interval between poll requests in seconds

`poll_timeout` float \| None  
Timeout for individual RPC poll requests in seconds. Defaults to 120 seconds.

`poll_timeout_retry` bool \| None  
Retry individual RPC poll requests when they time out. Requests will be retried up to twice, with a timeout of no greater than 60 seconds for the first retry and 30 for the second.

`concurrency` bool  
For sandboxes that run locally, request that the [concurrency()](../reference/inspect_ai.util.html.md#concurrency) function be used to throttle concurrent subprocesses.

`stdin_open` bool  
If True, keep stdin open after writing initial input, enabling write_stdin() and close_stdin() on the returned ExecRemoteProcess. If False (default), stdin is closed immediately after writing initial input (or not opened at all)

### ExecRemoteAwaitableOptions

Options for exec_remote() in awaitable mode (stream=False).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/exec_remote.py#L133)

``` python
@dataclass
class ExecRemoteAwaitableOptions(ExecRemoteCommonOptions)
```

#### Attributes

`input` str \| bytes \| None  
Standard input to send to the command

`cwd` str \| None  
Working directory for command execution

`env` dict\[str, str\] \| None  
Additional environment variables

`user` str \| None  
User to run the command as

`poll_interval` float \| None  
Interval between poll requests in seconds

`poll_timeout` float \| None  
Timeout for individual RPC poll requests in seconds. Defaults to 120 seconds.

`poll_timeout_retry` bool \| None  
Retry individual RPC poll requests when they time out. Requests will be retried up to twice, with a timeout of no greater than 60 seconds for the first retry and 30 for the second.

`concurrency` bool  
For sandboxes that run locally, request that the [concurrency()](../reference/inspect_ai.util.html.md#concurrency) function be used to throttle concurrent subprocesses.

`timeout` float \| None  
Maximum execution time in seconds. On timeout, the process is killed and TimeoutError is raised

### ExecOutput

Union type for all events that can be yielded by ExecRemoteProcess.events.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/exec_remote.py#L77)

``` python
ExecOutput = Union[ExecStdout, ExecStderr, ExecCompleted]
```

### ExecStdout

A chunk of stdout data from the running process.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/exec_remote.py#L39)

``` python
@dataclass
class ExecStdout
```

#### Attributes

`type` str  
Event type discriminator.

`data` str  
The stdout data.

### ExecStderr

A chunk of stderr data from the running process.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/exec_remote.py#L50)

``` python
@dataclass
class ExecStderr
```

#### Attributes

`type` str  
Event type discriminator.

`data` str  
The stderr data.

### ExecCompleted

Process completed (successfully or with error).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/exec_remote.py#L61)

``` python
@dataclass
class ExecCompleted
```

#### Attributes

`type` str  
Event type discriminator.

`exit_code` int  
The process exit code (0 = success)

`success` bool  
True if the process exited successfully (exit code 0).

## Intervention

### notify

Send a notification via the active Apprise instance (best-effort).

No-op when no Apprise instance is installed for the current eval scope. When `title` is omitted, the title and body are composed from the active sample context: title becomes `Inspect Agent: <task>` and the body starts with a `sample: <sample_id>/<epoch>` line followed by the message. Outside an active sample, the title is just `Inspect Agent` and the body is the unmodified message.

Best-effort by contract: a misbehaving Apprise backend (slow HTTP, network blackhole, plugin exception) must not delay or break the actual operator prompt that follows this call. Dispatch is bounded by `NOTIFY_TIMEOUT_SECONDS`; any exception is logged at warning and swallowed.

Apprise’s sync API is dispatched on a worker thread so this works under both asyncio and trio backends.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_notify.py#L139)

``` python
async def notify(message: str, title: str | None = None) -> None
```

`message` str  
The notification body.

`title` str \| None  
Optional title. Pass `None` to use the default `Inspect Agent` framing with sample context prepended to the body.

### request_input

Ask the user a structured question and wait for an answer.

Dispatches to the built-in handler selection (ACP, Textual panel, or console) based on runtime context. Also fires a notification via the active Apprise instance (a no-op when no notifications are configured) so an operator who has stepped away from the terminal can be pinged.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_input/request.py#L22)

``` python
async def request_input(
    *,
    message: str,
    schema: ElicitationSchema,
) -> InputResult
```

`message` str  
Prompt shown to the user.

`schema` ElicitationSchema  
ACP `ElicitationSchema` describing the answer fields.

### InputRequest

A structured question posted to the user via `request_input`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_input/_types.py#L16)

``` python
@dataclass
class InputRequest
```

#### Attributes

`message` str  
The prompt shown to the user.

`schema` ElicitationSchema  
Schema describing the answer fields.

### InputResult

Result returned from an `ask_user` interaction.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_input/_types.py#L27)

``` python
@dataclass
class InputResult
```

#### Attributes

`outcome` InputOutcome  
How the interaction concluded.

`content` dict\[str, Any\] \| None  
The user’s answer (keyed by `ElicitationSchema` property name) when `outcome == "accepted"`; otherwise `None`.

### InputResult

Result returned from an `ask_user` interaction.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_input/_types.py#L27)

``` python
@dataclass
class InputResult
```

#### Attributes

`outcome` InputOutcome  
How the interaction concluded.

`content` dict\[str, Any\] \| None  
The user’s answer (keyed by `ElicitationSchema` property name) when `outcome == "accepted"`; otherwise `None`.

## Checkpointing

### checkpointer

Enter the checkpointer bound to the active sample.

Delegates to the per-sample setup object stashed on the active sample by the harness. The setup builds and caches a real :class:[Checkpointer](../reference/inspect_ai.util.html.md#checkpointer) on first entry; subsequent opens within the same sample reuse the cached instance.

Must be called inside an active sample — :func:`sample_active` returning `None` raises `RuntimeError`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_checkpoint/checkpointer.py#L164)

``` python
@contextlib.asynccontextmanager
async def checkpointer() -> AsyncIterator[Checkpointer]
```

### Checkpointer

The session yielded by `async with checkpointer() as cp:`.

Agent-facing — no lifecycle methods. The async-ctx-mgr concerns live on the setup object that the harness keeps on the active sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_checkpoint/checkpointer.py#L44)

``` python
class Checkpointer(Protocol)
```

#### Attributes

`attempt` Literal\['initial', 'resume', 'resume_for_scoring'\]  
Why this session is running.

Stable across the lifetime of the session. Agents typically branch as follows:

- `"initial"` — fresh start; perform one-time setup.
- `"resume"` — prior agent loop crashed; framework state has been rehydrated, agent continues from where it left off.
- `"resume_for_scoring"` — prior agent loop finished cleanly but scoring crashed; agent should restore tracked state and return immediately so scoring can re-run.

#### Methods

tick  
Invoke at each turn boundary; may fire a checkpoint.

Triggered by the agent at points where a checkpoint is permissible. State persisted at the fire is whatever the agent has registered via :meth:`track`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_checkpoint/checkpointer.py#L68)

``` python
async def tick(self) -> None
```

checkpoint  
Force a fire regardless of policy (used by manual triggers).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_checkpoint/checkpointer.py#L77)

``` python
async def checkpoint(self) -> None
```

span_session  
Bracket the agent’s checkpointed scope with per-checkpoint transcript spans.

Spans are peers — siblings under whatever span was active when the agent opened `async with checkpointer()`. Each span’s name matches the checkpoint id it will fire under (1-indexed, same numbering as `ckpt-NNNNN.json`): `checkpoint 1` is the work that the first fire commits, `checkpoint 2` is the work that the second fire commits, and so on.

On fire, the current span closes *before* `write_host_context` (so the [SpanEndEvent](../reference/inspect_ai.event.html.md#spanendevent) lands in this checkpoint’s `events.json`), then the next span opens after the checkpoint file is committed.

A sample that finishes without ever firing leaves an unclosed `checkpoint 1` span — expected and informative: it records the work that would have been the first checkpoint had any fire happened. Same shape on resume: an attempt with `M` prior commits that finishes without firing leaves an unclosed `checkpoint M+1`.

For the no-op session this returns an empty ctx mgr.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_checkpoint/checkpointer.py#L81)

``` python
def span_session(self) -> contextlib.AbstractAsyncContextManager[None]
```

track  
Track `key` as part of the agent’s checkpointed state.

`callback` is invoked at every checkpoint fire to capture the value of the tracked state. On a retry of this sample, the captured value is returned; on a fresh run, `initial_value` is returned.

Generic over `T`. The runtime contract on the captured value is “any value that `pydantic_core.to_jsonable_python` can serialize” — JSON primitives, lists, dicts, Pydantic models, dataclasses, and arbitrary nesting of these.

`value_type` is required for any `T` whose JSON form differs from its in-memory form — collections of Pydantic models, discriminated unions, models nested in generic containers, etc. Two cases are auto-handled and do **not** need a `value_type`:

- A single Pydantic model instance — the instance’s runtime class is unambiguous.
- A JSON-primitive value (`int`, `float`, `str`, `bool`, `None`) — round-trips identically through `json`.

Any other `initial_value` without a `value_type` raises `TypeError` at register time. The check fires deterministically on every run (fresh or resume) so the missing-`value_type` bug surfaces during development rather than mid-agent-loop after a real failure-and-retry.

A key may be tracked only once per session; a duplicate call raises `ValueError`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_checkpoint/checkpointer.py#L107)

``` python
def track(
    self,
    key: str,
    callback: Callable[[], T],
    initial_value: T,
    *,
    value_type: type[T] | None = None,
) -> T
```

`key` str  

`callback` Callable\[\[\], T\]  

`initial_value` T  

`value_type` type\[T\] \| None  

### CheckpointConfig

User-facing checkpoint configuration for the task and eval layers.

Specify on `Task(checkpoint=...)` or `eval(checkpoint=...)`. All fields default to `None` so that each level can supply a partial config; the layers are combined per-field at sample-run time (precedence: eval \> sample \> task).

Adds the eval-wide fields (`checkpoints_location`, `retention`) to the sample-permitted base class. Sample-layer configs use the base :class:[CheckpointSampleConfig](../reference/inspect_ai.util.html.md#checkpointsampleconfig) directly — these fields cannot be set per-sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_checkpoint/config.py#L63)

``` python
@dataclass
class CheckpointConfig(CheckpointSampleConfig)
```

#### Attributes

`trigger` [CheckpointTrigger](../reference/inspect_ai.util.html.md#checkpointtrigger) \| None  
Checkpoint trigger strategy — any implementer of :class:[CheckpointTrigger](../reference/inspect_ai.util.html.md#checkpointtrigger) (see :mod:`.triggers`). `None` means “inherit from a lower-priority layer”; when no layer sets a trigger, resolution falls back to :<data:%60DEFAULT_CHECKPOINT_TRIGGER>\`.

`sandbox_paths` dict\[str, list\[str\]\] \| None  
Per-sandbox-name list of absolute paths to capture inside the sandbox. `None` = inherit; `{}` (after merge) = host-only checkpointing (no sandbox repos).

`max_consecutive_failures` int \| None  
If set, the sample fails after N consecutive failed checkpoint attempts. `None` = inherit / unlimited tolerance. `0` = any failure is fatal.

`checkpoints_location` str \| None  
Override the parent directory under which the eval checkpoints dir lands. `None` = sibling of the eval log file. When set, inspect places `<log-base>.checkpoints/` under this root. Supports any fsspec-resolvable path (`s3://`, `gs://`, plain local). Eval-wide — settable only at the task or eval layer.

`retention` Literal\['delete', 'retain'\] \| None  
Controls when checkpoint data is deleted after eval completion. `"delete"` removes the checkpoint directory after successful eval completion; `"retain"` keeps it for later inspection or replay. `None` = inherit / use the default (`"delete"`). Eval-wide — settable only at the task or eval layer.

### CheckpointSampleConfig

Checkpoint configuration fields that may be set at the sample layer.

These fields can be specified on `Sample(checkpoint=...)` and are also accepted at the task and eval layers (where they participate in the per-field merge — precedence: eval \> sample \> task).

The fields excluded from this base class — `checkpoints_location` and `retention` — are eval-wide concerns that the sample layer must not influence. They live only on the derived :class:[CheckpointConfig](../reference/inspect_ai.util.html.md#checkpointconfig), which is the type used at the task and eval layers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_checkpoint/config.py#L31)

``` python
@dataclass
class CheckpointSampleConfig
```

#### Attributes

`trigger` [CheckpointTrigger](../reference/inspect_ai.util.html.md#checkpointtrigger) \| None  
Checkpoint trigger strategy — any implementer of :class:[CheckpointTrigger](../reference/inspect_ai.util.html.md#checkpointtrigger) (see :mod:`.triggers`). `None` means “inherit from a lower-priority layer”; when no layer sets a trigger, resolution falls back to :<data:%60DEFAULT_CHECKPOINT_TRIGGER>\`.

`sandbox_paths` dict\[str, list\[str\]\] \| None  
Per-sandbox-name list of absolute paths to capture inside the sandbox. `None` = inherit; `{}` (after merge) = host-only checkpointing (no sandbox repos).

`max_consecutive_failures` int \| None  
If set, the sample fails after N consecutive failed checkpoint attempts. `None` = inherit / unlimited tolerance. `0` = any failure is fatal.

### CheckpointTrigger

User-facing checkpoint trigger spec — a union of frozen dataclass config types. See :mod:`._engine` for the runtime dispatch.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_checkpoint/_triggers/types.py#L110)

``` python
CheckpointTrigger = (
    Manual | TurnInterval | TimeInterval | TokenInterval | CostInterval | BudgetPercent
)
```

### TimeInterval

Fire after a wall-clock interval.

The engine fires when at least `every` has elapsed since the last fire (or since the session opened, for the first fire).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_checkpoint/_triggers/types.py#L44)

``` python
@dataclass(frozen=True)
class TimeInterval
```

### TokenInterval

Fire every `every` tokens of sample-level usage.

Sample total tokens are read from :func:`inspect_ai.model.sample_total_tokens`; the trigger fires each time the running total crosses another `every`-token boundary since the last fire.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_checkpoint/_triggers/types.py#L55)

``` python
@dataclass(frozen=True)
class TokenInterval
```

### TurnInterval

Fire after every `every` agent turns of work.

The very first `tick()` call marks the boundary *before* turn 1 has run — agents place `cp.tick()` at the top of their loop, so the opening tick stands between “no turn yet” and “turn 1.” That boundary is informational and doesn’t count toward the threshold; otherwise `every=1` would fire an empty checkpoint on the opening tick.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_checkpoint/_triggers/types.py#L29)

``` python
@dataclass(frozen=True)
class TurnInterval
```

### Manual

No-op trigger spec.

The engine’s `tick()` always returns `None` for this spec — fires happen only through explicit `cp.checkpoint()` calls.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_checkpoint/_triggers/types.py#L20)

``` python
@dataclass(frozen=True)
class Manual
```

## Registry

### registry_info

Lookup RegistryInfo for an object.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/_util/registry.py#L393)

``` python
def registry_info(o: object) -> RegistryInfo
```

`o` object  
Object to lookup info for

### registry_create

Create a registry object.

Creates objects registered via decorator (e.g. `@task`, `@solver`). Note that this can also create registered objects within Python packages, in which case the name of the package should be used a prefix, e.g.

``` python
registry_create("scorer", "mypackage/myscorer", ...)
```

Object within the Inspect package do not require a prefix, nor do objects from imported modules that aren’t in a package.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/_util/registry.py#L320)

``` python
def registry_create(type: RegistryType, name: str, **kwargs: Any) -> object:  # type: ignore[return]
```

`type` [RegistryType](../reference/inspect_ai.util.html.md#registrytype)  
Type of registry object to create

`name` str  
Name of registry object to create

`**kwargs` Any  
Optional creation arguments

### RegistryInfo

Registry information for registered object (e.g. solver, scorer, etc.).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/_util/registry.py#L65)

``` python
class RegistryInfo(BaseModel)
```

#### Attributes

`type` [RegistryType](../reference/inspect_ai.util.html.md#registrytype)  
Type of registry object.

`name` str  
Registered name.

`metadata` dict\[str, Any\]  
Additional registry metadata.

### RegistryType

Enumeration of registry object types.

These are the types of objects in this system that can be registered using a decorator (e.g. `@task`, `@solver`). Registered objects can in turn be created dynamically using the [registry_create()](../reference/inspect_ai.util.html.md#registry_create) function.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/_util/registry.py#L38)

``` python
RegistryType = Literal[
    "agent",
    "approver",
    "hooks",
    "metric",
    "modelapi",
    "plan",
    "sandboxenv",
    "score_reducer",
    "scorer",
    "solver",
    "task",
    "task_source",
    "tool",
    "loader",
    "scanner",
    "scanjob",
]
```

## JSON

### StrEnum

Enum where members are also (and must be) strings.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/_util/strenum.py#L22)

``` python
    class StrEnum(str, Enum)
```

### JSONType

Valid types within JSON schema.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_json.py#L26)

``` python
JSONType = Literal["string", "integer", "number", "boolean", "array", "object", "null"]
```

### JSONSchema

JSON Schema for type.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_json.py#L30)

``` python
class JSONSchema(BaseModel)
```

#### Attributes

`type` [JSONType](../reference/inspect_ai.util.html.md#jsontype) \| list\[[JSONType](../reference/inspect_ai.util.html.md#jsontype)\] \| None  
JSON type of tool parameter.

`format` str \| None  
Format of the parameter (e.g. date-time).

`description` str \| None  
Parameter description.

`default` Any  
Default value for parameter.

`enum` list\[Any\] \| None  
Valid values for enum parameters.

`items` [JSONSchema](../reference/inspect_ai.util.html.md#jsonschema) \| None  
Valid type for array parameters.

`properties` dict\[str, [JSONSchema](../reference/inspect_ai.util.html.md#jsonschema)\] \| None  
Valid fields for object parametrs.

`additionalProperties` Optional\[[JSONSchema](../reference/inspect_ai.util.html.md#jsonschema)\] \| bool \| None  
Are additional properties allowed?

`anyOf` list\[[JSONSchema](../reference/inspect_ai.util.html.md#jsonschema)\] \| None  
Valid types for union parameters.

`required` list\[str\] \| None  
Required fields for object parameters.

`pattern` str \| None  
Regex pattern for string parameters.

`minLength` int \| None  
Minimum length for string parameters.

`maxLength` int \| None  
Maximum length for string parameters.

`minimum` int \| float \| None  
Minimum value for numeric parameters.

`maximum` int \| float \| None  
Maximum value for numeric parameters.

`examples` list\[Any\] \| None  
Example values for the parameter.

### json_schema

Provide a JSON Schema for the specified type.

Schemas can be automatically inferred for a wide variety of Python class types including Pydantic BaseModel, dataclasses, and typed dicts.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_json.py#L153)

``` python
def json_schema(t: Type[Any]) -> JSONSchema
```

`t` Type\[Any\]  
Python type

## Early Stopping

### EarlyStopping

Early stopping manager for skipping selected samples/epochs.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_early_stopping.py#L42)

``` python
class EarlyStopping(Protocol)
```

#### Methods

start_task  
Called at the beginning of an eval run to register the tasks that will be run.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_early_stopping.py#L45)

``` python
async def start_task(
    self, task: "EvalSpec", samples: list["Sample"], epochs: int
) -> str
```

`task` 'EvalSpec'  
Task metadata.

`samples` list\['Sample'\]  
List of samples that will be executed for this task.

`epochs` int  
Number of epochs to run for each sample.

schedule_sample  
Called prior to scheduling a sample to cheeck for an early stop.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_early_stopping.py#L60)

``` python
async def schedule_sample(self, id: str | int, epoch: int) -> EarlyStop | None
```

`id` str \| int  
Sample dataset id.

`epoch` int  
Sample epoch.

complete_sample  
Called when a sample is complete.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_early_stopping.py#L72)

``` python
async def complete_sample(
    self,
    id: str | int,
    epoch: int,
    scores: dict[str, "SampleScore"],
) -> None
```

`id` str \| int  
Sample dataset id.

`epoch` int  
Sample epoch.

`scores` dict\[str, 'SampleScore'\]  
Scores for this sample.

complete_task  
Called when the task is complete.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_early_stopping.py#L87)

``` python
async def complete_task(self) -> dict[str, JsonValue]
```

### EarlyStoppingSummary

Summary of early stopping applied to task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_early_stopping.py#L29)

``` python
class EarlyStoppingSummary(BaseModel)
```

#### Attributes

`manager` str  
Name of early stopping manager.

`early_stops` list\[[EarlyStop](../reference/inspect_ai.util.html.md#earlystop)\]  
Samples that were stopped early.

`metadata` dict\[str, JsonValue\]  
Metadata about early stopping

### EarlyStop

Directive to stop a sample early.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_early_stopping.py#L13)

``` python
class EarlyStop(BaseModel)
```

#### Attributes

`id` str \| int  
Sample dataset id.

`epoch` int  
Sample epoch.

`reason` str \| None  
Reason for the early stop.

`metadata` dict\[str, JsonValue\] \| None  
Metadata related to early stop.

## Compose

### parse_compose_yaml

Parse a Docker Compose file into a ComposeConfig.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/compose.py#L343)

``` python
def parse_compose_yaml(
    file: str,
    *,
    multiple_services: bool = True,
) -> ComposeConfig
```

`file` str  
Path to the compose file.

`multiple_services` bool  
Whether the provider supports multiple services. If False and the compose file has multiple services, a ValueError will be raised.

### is_compose_yaml

Check if a path is a Docker Compose file.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/compose.py#L41)

``` python
def is_compose_yaml(file: Any) -> TypeGuard[str]
```

`file` Any  
Path to check.

### is_dockerfile

Check if a path is a Dockerfile.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/compose.py#L75)

``` python
def is_dockerfile(file: Any) -> TypeGuard[str]
```

`file` Any  
Path to check.

### ComposeConfig

Parsed Docker Compose configuration.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/compose.py#L320)

``` python
class ComposeConfig(ComposeModel)
```

#### Attributes

`extensions` dict\[str, Any\]  
Get x- extension fields.

`services` dict\[str, [ComposeService](../reference/inspect_ai.util.html.md#composeservice)\]  
Service definitions, keyed by service name.

`volumes` dict\[str, Any\] \| None  
Volume definitions.

`networks` dict\[str, Any\] \| None  
Network definitions.

### ComposeService

A service definition from a compose file.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/compose.py#L214)

``` python
class ComposeService(ComposeModel)
```

#### Attributes

`extensions` dict\[str, Any\]  
Get x- extension fields.

`image` str \| None  
Docker image to use (e.g., ‘python:3.11’).

`build` [ComposeBuild](../reference/inspect_ai.util.html.md#composebuild) \| str \| None  
Build configuration or path to build context.

`command` list\[str\] \| str \| None  
Command to run in the container.

`entrypoint` list\[str\] \| str \| None  
Entrypoint for the container.

`working_dir` str \| None  
Working directory inside the container.

`environment` list\[str\] \| dict\[str, str \| None\] \| None  
Environment variables.

`env_file` list\[str\] \| str \| None  
Path(s) to file(s) containing environment variables.

`user` str \| None  
User to run the container as.

`healthcheck` [ComposeHealthcheck](../reference/inspect_ai.util.html.md#composehealthcheck) \| None  
Health check configuration.

`ports` list\[str \| int\] \| None  
Port mappings (host:container).

`expose` list\[str \| int\] \| None  
Ports to expose without publishing to the host.

`volumes` list\[str\] \| None  
Volume mounts.

`networks` list\[str\] \| dict\[str, Any\] \| None  
Networks to connect to.

`network_mode` str \| None  
Network mode (e.g., ‘host’, ‘none’, ‘bridge’).

`hostname` str \| None  
Container hostname.

`runtime` str \| None  
Runtime to use (e.g., ‘nvidia’).

`init` bool \| None  
Run an init process inside the container.

`privileged` bool \| None  
Run the container in privileged mode.

`shm_size` str \| int \| None  
Size of `/dev/shm` (e.g. `1g`, `256m`, or bytes as int).

`ulimits` dict\[str, int \| dict\[str, int\]\] \| None  
Per-container ulimits (e.g. `nofile: {soft: 20000, hard: 40000}`).

`depends_on` list\[str\] \| dict\[str, Any\] \| None  
Service startup dependencies. Short (list) or long (dict) form per Compose spec.

`pull_policy` str \| None  
Image pull policy (e.g. `always`, `never`, `missing`, `build`).

`platform` str \| None  
Target platform for the container (e.g. `linux/amd64`).

`extra_hosts` list\[str\] \| dict\[str, str\] \| None  
Extra `/etc/hosts` entries. List (`"host:ip"`) or mapping form per Compose spec.

`cap_add` list\[str\] \| None  
Linux capabilities to add (e.g. `["SYS_PTRACE"]`).

`cap_drop` list\[str\] \| None  
Linux capabilities to drop (e.g. `["ALL"]`).

`security_opt` list\[str\] \| None  
Container security options (e.g. `["seccomp=unconfined"]`).

`tmpfs` str \| list\[str\] \| None  
Paths mounted as a tmpfs. Single path or list of paths.

`deploy` ComposeDeploy \| None  
Deployment configuration including resources.

`mem_limit` str \| None  
Memory limit (shortcut for deploy.resources.limits.memory).

`mem_reservation` str \| None  
Memory reservation (shortcut for deploy.resources.reservations.memory).

`memswap_limit` str \| int \| None  
Total memory + swap limit (e.g. `20g`, `256m`, or bytes as int).

`cpus` float \| None  
CPU limit (shortcut for deploy.resources.limits.cpus).

`x_default` bool \| None  
Mark this service as the default for sandbox providers.

### ComposeBuild

Build configuration for a compose service.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/compose.py#L145)

``` python
class ComposeBuild(ComposeModel)
```

#### Attributes

`extensions` dict\[str, Any\]  
Get x- extension fields.

`context` str \| None  
Path to the build context directory.

`dockerfile` str \| None  
Path to the Dockerfile, relative to context.

### ComposeHealthcheck

Healthcheck configuration for a compose service.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/3e05d56606c8b5da730a1e331620b0d71f63a95e/src/inspect_ai/util/_sandbox/compose.py#L123)

``` python
class ComposeHealthcheck(ComposeModel)
```

#### Attributes

`extensions` dict\[str, Any\]  
Get x- extension fields.

`test` list\[str\] \| str \| None  
Command to run to check health.

`interval` str \| None  
Time between health checks (e.g., ‘30s’, ‘1m’).

`timeout` str \| None  
Maximum time to wait for a check to complete.

`start_period` str \| None  
Time to wait before starting health checks.

`start_interval` str \| None  
Time between checks during the start period.

`retries` int \| None  
Number of consecutive failures needed to consider unhealthy.
