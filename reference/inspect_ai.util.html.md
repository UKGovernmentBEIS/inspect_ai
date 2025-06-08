# inspect_ai.util


## Store

### Store

The `Store` is used to record state and state changes.

The `TaskState` for each sample has a `Store` which can be used when
solvers and/or tools need to coordinate changes to shared state. The
`Store` can be accessed directly from the `TaskState` via `state.store`
or can be accessed using the `store()` global function.

Note that changes to the store that occur are automatically recorded to
transcript as a `StoreEvent`. In order to be serialised to the
transcript, values and objects must be JSON serialisable (you can make
objects with several fields serialisable using the `@dataclass`
decorator or by inheriting from Pydantic `BaseModel`)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_store.py#L20)

``` python
class Store
```

#### Methods

get  
Get a value from the store.

Provide a `default` to automatically initialise a named store value with
the default when it does not yet exist.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_store.py#L46)

``` python
def get(self, key: str, default: VT | None = None) -> VT | Any
```

`key` str  
Name of value to get

`default` VT \| None  
Default value (defaults to `None`)

set  
Set a value into the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_store.py#L64)

``` python
def set(self, key: str, value: Any) -> None
```

`key` str  
Name of value to set

`value` Any  
Value to set

delete  
Remove a value from the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_store.py#L73)

``` python
def delete(self, key: str) -> None
```

`key` str  
Name of value to remove

keys  
View of keys within the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_store.py#L81)

``` python
def keys(self) -> KeysView[str]
```

values  
View of values within the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_store.py#L85)

``` python
def values(self) -> ValuesView[Any]
```

items  
View of items within the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_store.py#L89)

``` python
def items(self) -> ItemsView[str, Any]
```

### store

Get the currently active `Store`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_store.py#L103)

``` python
def store() -> Store
```

### store_as

Get a Pydantic model interface to the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_store_model.py#L121)

``` python
def store_as(model_cls: Type[SMT], instance: str | None = None) -> SMT
```

`model_cls` Type\[SMT\]  
Pydantic model type (must derive from StoreModel)

`instance` str \| None  
Optional instance name for store (enables multiple instances of a given
StoreModel type within a single sample)

### StoreModel

Store backed Pydandic BaseModel.

The model is initialised from a Store, so that Store should either
already satisfy the validation constraints of the model OR you should
provide Field(default=) annotations for all of your model fields (the
latter approach is recommended).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_store_model.py#L8)

``` python
class StoreModel(BaseModel)
```

## Limits

### message_limit

Limits the number of messages in a conversation.

The total number of messages in the conversation are compared to the
limit (not just “new” messages).

These limits can be stacked.

This relies on “cooperative” checking - consumers must call
check_message_limit() themselves whenever the message count is updated.

When a limit is exceeded, a `LimitExceededError` is raised.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_limit.py#L199)

``` python
def message_limit(limit: int | None) -> _MessageLimit
```

`limit` int \| None  
The maximum conversation length (number of messages) allowed while the
context manager is open. A value of None means unlimited messages.

### token_limit

Limits the total number of tokens which can be used.

The counter starts when the context manager is opened and ends when it
is closed.

These limits can be stacked.

This relies on “cooperative” checking - consumers must call
`check_token_limit()` themselves whenever tokens are consumed.

When a limit is exceeded, a `LimitExceededError` is raised.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_limit.py#L155)

``` python
def token_limit(limit: int | None) -> _TokenLimit
```

`limit` int \| None  
The maximum number of tokens that can be used while the context manager
is open. Tokens used before the context manager was opened are not
counted. A value of None means unlimited tokens.

### time_limit

Limits the wall clock time which can elapse.

The timer starts when the context manager is opened and stops when it is
closed.

These limits can be stacked.

When a limit is exceeded, the code block is cancelled and a
`LimitExceededError` is raised.

Uses anyio’s cancellation scopes meaning that the operations within the
context manager block are cancelled if the limit is exceeded. The
`LimitExceededError` is therefore raised at the level that the
`time_limit()` context manager was opened, not at the level of the
operation which caused the limit to be exceeded (e.g. a call to
`generate()`). Ensure you handle `LimitExceededError` at the level of
opening the context manager.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_limit.py#L236)

``` python
def time_limit(limit: float | None) -> _TimeLimit
```

`limit` float \| None  
The maximum number of seconds that can pass while the context manager is
open. A value of None means unlimited time.

### working_limit

Limits the working time which can elapse.

Working time is the wall clock time minus any waiting time e.g. waiting
before retrying in response to rate limits or waiting on a semaphore.

The timer starts when the context manager is opened and stops when it is
closed.

These limits can be stacked.

When a limit is exceeded, a `LimitExceededError` is raised.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_limit.py#L259)

``` python
def working_limit(limit: float | None) -> _WorkingLimit
```

`limit` float \| None  
The maximum number of seconds of working that can pass while the context
manager is open. A value of None means unlimited time.

### apply_limits

Apply a list of limits within a context manager.

Optionally catches any `LimitExceededError` raised by the applied
limits, while allowing other limit errors from any other scope (e.g. the
Sample level) to propagate.

Yields a `LimitScope` object which can be used once the context manager
is closed to determine which, if any, limits were exceeded.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_limit.py#L106)

``` python
@contextmanager
def apply_limits(
    limits: list[Limit], catch_errors: bool = False
) -> Iterator[LimitScope]
```

`limits` list\[[Limit](inspect_ai.util.qmd#limit)\]  
List of limits to apply while the context manager is open. Should a
limit be exceeded, a `LimitExceededError` is raised.

`catch_errors` bool  
If True, catch any `LimitExceededError` raised by the applied limits.
Callers can determine whether any limits were exceeded by checking the
limit_error property of the `LimitScope` object yielded by this
function. If False, all `LimitExceededError` exceptions will be allowed
to propagate.

### Limit

Base class for all limit context managers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_limit.py#L72)

``` python
class Limit(abc.ABC)
```

#### Attributes

`usage` float  
The current usage of the resource being limited.

### LimitExceededError

Exception raised when a limit is exceeded.

In some scenarios this error may be raised when `value >= limit` to
prevent another operation which is guaranteed to exceed the limit from
being wastefully performed.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_limit.py#L25)

``` python
class LimitExceededError(Exception)
```

## Concurrency

### concurrency

Concurrency context manager.

A concurrency context can be used to limit the number of coroutines
executing a block of code (e.g calling an API). For example, here we
limit concurrent calls to an api (‘api-name’) to 10:

``` python
async with concurrency("api-name", 10):
    # call the api
```

Note that concurrency for model API access is handled internally via the
`max_connections` generation config option. Concurrency for launching
subprocesses is handled via the `subprocess` function.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_concurrency.py#L11)

``` python
@contextlib.asynccontextmanager
async def concurrency(
    name: str,
    concurrency: int,
    key: str | None = None,
) -> AsyncIterator[None]
```

`name` str  
Name for concurrency context. This serves as the display name for the
context, and also the unique context key (if the `key` parameter is
omitted)

`concurrency` int  
Maximum number of coroutines that can enter the context.

`key` str \| None  
Unique context key for this context. Optional. Used if the unique key
isn’t human readable – e.g. includes api tokens or account ids so that
the more readable `name` can be presented to users e.g in console UI\>

### subprocess

Execute and wait for a subprocess.

Convenience method for solvers, scorers, and tools to launch
subprocesses. Automatically enforces a limit on concurrent subprocesses
(defaulting to os.cpu_count() but controllable via the
`max_subprocesses` eval config option).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_subprocess.py#L71)

``` python
async def subprocess(
    args: str | list[str],
    text: bool = True,
    input: str | bytes | memoryview | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] = {},
    capture_output: bool = True,
    output_limit: int | None = None,
    timeout: int | None = None,
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

`env` dict\[str, str\]  
Additional environment variables.

`capture_output` bool  
Capture stderr and stdout into ExecResult (if False, then output is
redirected to parent stderr/stdout)

`output_limit` int \| None  
Stop reading output if it exceeds the specified limit (in bytes).

`timeout` int \| None  
Timeout. If the timeout expires then a `TimeoutError` will be raised.

### ExecResult

Execution result from call to `subprocess()`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_subprocess.py#L27)

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

## Display

### display_counter

Display a counter in the UI.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_display.py#L74)

``` python
def display_counter(caption: str, value: str) -> None
```

`caption` str  
The counter’s caption e.g. “HTTP rate limits”.

`value` str  
The counter’s value e.g. “42”.

### display_type

Get the current console display type.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_display.py#L47)

``` python
def display_type() -> DisplayType
```

### DisplayType

Console display type.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_display.py#L11)

``` python
DisplayType = Literal["full", "conversation", "rich", "plain", "log", "none"]
```

### input_screen

Input screen for receiving user input.

Context manager that clears the task display and provides a screen for
receiving console input.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_console.py#L13)

``` python
@contextmanager
def input_screen(
    header: str | None = None,
    transient: bool | None = None,
    width: int | None = None,
) -> Iterator[Console]
```

`header` str \| None  
Header line to print above console content (defaults to printing no
header)

`transient` bool \| None  
Return to task progress display after the user completes input (defaults
to `True` for normal sessions and `False` when trace mode is enabled).

`width` int \| None  
Input screen width in characters (defaults to full width)

## Utilities

### span

Context manager for establishing a transcript span.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_span.py#L7)

``` python
@contextlib.asynccontextmanager
async def span(name: str, *, type: str | None = None) -> AsyncIterator[None]
```

`name` str  
Step name.

`type` str \| None  
Optional span type.

### collect

Run and collect the results of one or more async coroutines.

Similar to
[`asyncio.gather()`](https://docs.python.org/3/library/asyncio-task.html#asyncio.gather),
but also works when [Trio](https://trio.readthedocs.io/en/stable/) is
the async backend.

Automatically includes each task in a `span()`, which ensures that its
events are grouped together in the transcript.

Using `collect()` in preference to `asyncio.gather()` is highly
recommended for both Trio compatibility and more legible transcript
output.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_collect.py#L15)

``` python
async def collect(*tasks: Awaitable[T]) -> list[T]
```

`*tasks` Awaitable\[T\]  
Tasks to run

### resource

Read and resolve a resource to a string.

Resources are often used for templates, configuration, etc. They are
sometimes hard-coded strings, and sometimes paths to external resources
(e.g. in the local filesystem or remote stores e.g. s3:// or
<https://>).

The `resource()` function will resolve its argument to a resource
string. If a protocol-prefixed file name (e.g. s3://) or the path to a
local file that exists is passed then it will be read and its contents
returned. Otherwise, it will return the passed `str` directly This
function is mostly intended as a helper for other functions that take
either a string or a resource path as an argument, and want to easily
resolve them to the underlying content.

If you want to ensure that only local or remote files are consumed,
specify `type="file"`. For example:
`resource("templates/prompt.txt", type="file")`

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_resource.py#L9)

``` python
def resource(
    resource: str,
    type: Literal["auto", "file"] = "auto",
    fs_options: dict[str, Any] = {},
) -> str
```

`resource` str  
Path to local or remote (e.g. s3://) resource, or for `type="auto"` (the
default), a string containing the literal resource value.

`type` Literal\['auto', 'file'\]  
For “auto” (the default), interpret the resource as a literal string if
its not a valid path. For “file”, always interpret it as a file path.

`fs_options` dict\[str, Any\]  
Optional. Additional arguments to pass through to the `fsspec`
filesystem provider (e.g. `S3FileSystem`). Use `{"anon": True }` if you
are accessing a public S3 bucket with no credentials.

### throttle

Throttle a function to ensure it is called no more than every n seconds.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_throttle.py#L6)

``` python
def throttle(seconds: float) -> Callable[..., Any]
```

`seconds` float  
Throttle time.

### trace_action

Trace a long running or poentially unreliable action.

Trace actions for which you want to collect data on the resolution
(e.g. succeeded, cancelled, failed, timed out, etc.) and duration of.

Traces are written to the `TRACE` log level (which is just below `HTTP`
and `INFO`). List and read trace logs with `inspect trace list` and
related commands (see `inspect trace --help` for details).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/_util/trace.py#L32)

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

The `TRACE` log level is just below `HTTP` and `INFO`). List and read
trace logs with `inspect trace list` and related commands (see
`inspect trace --help` for details).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/_util/trace.py#L133)

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

## Sandbox

### sandbox

Get the SandboxEnvironment for the current sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/context.py#L23)

``` python
def sandbox(name: str | None = None) -> SandboxEnvironment
```

`name` str \| None  
Optional sandbox environment name.

### sandbox_with

Get the SandboxEnvironment for the current sample that has the specified
file.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/context.py#L53)

``` python
async def sandbox_with(
    file: str, on_path: bool = False, *, name: str | None = None
) -> SandboxEnvironment | None
```

`file` str  
Path to file to check for if on_path is False. If on_path is True, file
should be a filename that exists on the system path.

`on_path` bool  
If True, file is a filename to be verified using “which”. If False, file
is a path to be checked within the sandbox environments.

`name` str \| None  
Optional sandbox environment name.

### sandbox_default

Set the default sandbox environment for the current context.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/context.py#L276)

``` python
@contextmanager
def sandbox_default(name: str) -> Iterator[None]
```

`name` str  
Sandbox to set as the default.

### SandboxEnvironment

Environment for executing arbitrary code from tools.

Sandbox environments provide both an execution environment as well as a
per-sample filesystem context to copy samples files into and resolve
relative paths to.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L84)

``` python
class SandboxEnvironment(abc.ABC)
```

#### Methods

exec  
Execute a command within a sandbox environment.

The current working directory for execution will be the per-sample
filesystem context.

Each output stream (stdout and stderr) is limited to 10 MiB. If
exceeded, an `OutputLimitExceededError` will be raised.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L91)

``` python
@abc.abstractmethod
async def exec(
    self,
    cmd: list[str],
    input: str | bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] = {},
    user: str | None = None,
    timeout: int | None = None,
    timeout_retry: bool = True,
) -> ExecResult[str]
```

`cmd` list\[str\]  
Command or command and arguments to execute.

`input` str \| bytes \| None  
Standard input (optional).

`cwd` str \| None  
Current working dir (optional). If relative, will be relative to the
per-sample filesystem context.

`env` dict\[str, str\]  
Environment variables for execution.

`user` str \| None  
Optional username or UID to run the command as.

`timeout` int \| None  
Optional execution timeout (seconds).

`timeout_retry` bool  
Retry the command in the case that it times out. Commands will be
retried up to twice, with a timeout of no greater than 60 seconds for
the first retry and 30 for the second.

write_file  
Write a file into the sandbox environment.

If the parent directories of the file path do not exist they should be
automatically created.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L137)

``` python
@abc.abstractmethod
async def write_file(self, file: str, contents: str | bytes) -> None
```

`file` str  
Path to file (relative file paths will resolve to the per-sample working
directory).

`contents` str \| bytes  
Text or binary file contents.

read_file  
Read a file from the sandbox environment.

File size is limited to 100 MiB.

When reading text files, implementations should preserve newline
constructs (e.g. crlf should be preserved not converted to lf). This is
equivalent to specifying `newline=""` in a call to the Python `open()`
function.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L163)

``` python
@abc.abstractmethod
async def read_file(self, file: str, text: bool = True) -> Union[str | bytes]
```

`file` str  
Path to file (relative file paths will resolve to the per-sample working
directory).

`text` bool  
Read as a utf-8 encoded text file.

connection  
Information required to connect to sandbox environment.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L194)

``` python
async def connection(self, *, user: str | None = None) -> SandboxConnection
```

`user` str \| None  
User to login as.

as_type  
Verify and return a reference to a subclass of SandboxEnvironment.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L209)

``` python
def as_type(self, sandbox_cls: Type[ST]) -> ST
```

`sandbox_cls` Type\[ST\]  
Class of sandbox (subclass of SandboxEnvironment)

default_concurrency  
Default max_sandboxes for this provider (`None` means no maximum)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L228)

``` python
@classmethod
def default_concurrency(cls) -> int | None
```

task_init  
Called at task startup initialize resources.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L233)

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
Called at task startup to identify environment variables required by
task_init for a sample.

Return 1 or more environment variables to request a dedicated call to
task_init for samples that have exactly these environment variables (by
default there is only one call to task_init for all of the samples in a
task if they share a sandbox configuration).

This is useful for situations where config files are dynamic
(e.g. through sample metadata variable interpolation) and end up
yielding different images that need their own init (e.g. ‘docker pull’).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L245)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L269)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L290)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L309)

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
Whether to actually cleanup environment resources (False if
`--no-sandbox-cleanup` was specified)

cli_cleanup  
Handle a cleanup invoked from the CLI (e.g. inspect sandbox cleanup).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L323)

``` python
@classmethod
async def cli_cleanup(cls, id: str | None) -> None
```

`id` str \| None  
Optional ID to limit scope of cleanup.

config_files  
Standard config files for this provider (used for automatic discovery)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L332)

``` python
@classmethod
def config_files(cls) -> list[str]
```

config_deserialize  
Deserialize a sandbox-specific configuration model from a dict.

Override this method if you support a custom configuration model.

A basic implementation would be:
`return MySandboxEnvironmentConfig(**config)`

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L337)

``` python
@classmethod
def config_deserialize(cls, config: dict[str, Any]) -> BaseModel
```

`config` dict\[str, Any\]  
Configuration dictionary produced by serializing the configuration
model.

### SandboxConnection

Information required to connect to sandbox.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/environment.py#L65)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_sandbox/registry.py#L16)

``` python
def sandboxenv(name: str) -> Callable[..., Type[T]]
```

`name` str  
Name of SandboxEnvironment type

## Registry

### registry_create

Create a registry object.

Creates objects registered via decorator (e.g. `@task`, `@solver`). Note
that this can also create registered objects within Python packages, in
which case the name of the package should be used a prefix, e.g.

``` python
registry_create("scorer", "mypackage/myscorer", ...)
```

Object within the Inspect package do not require a prefix, nor do
objects from imported modules that aren’t in a package.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/_util/registry.py#L283)

``` python
def registry_create(type: RegistryType, name: str, **kwargs: Any) -> object:  # type: ignore[return]
```

`type` [RegistryType](inspect_ai.util.qmd#registrytype)  
Type of registry object to create

`name` str  
Name of registry object to create

`**kwargs` Any  
Optional creation arguments

### RegistryType

Enumeration of registry object types.

These are the types of objects in this system that can be registered
using a decorator (e.g. `@task`, `@solver`). Registered objects can in
turn be created dynamically using the `registry_create()` function.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/_util/registry.py#L37)

``` python
RegistryType = Literal[
    "agent",
    "approver",
    "metric",
    "modelapi",
    "plan",
    "sandboxenv",
    "score_reducer",
    "scorer",
    "solver",
    "task",
    "tool",
]
```

## JSON

### JSONType

Valid types within JSON schema.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_json.py#L26)

``` python
JSONType = Literal["string", "integer", "number", "boolean", "array", "object", "null"]
```

### JSONSchema

JSON Schema for type.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_json.py#L30)

``` python
class JSONSchema(BaseModel)
```

#### Attributes

`type` [JSONType](inspect_ai.util.qmd#jsontype) \| None  
JSON type of tool parameter.

`format` str \| None  
Format of the parameter (e.g. date-time).

`description` str \| None  
Parameter description.

`default` Any  
Default value for parameter.

`enum` list\[Any\] \| None  
Valid values for enum parameters.

`items` Optional\[[JSONSchema](inspect_ai.util.qmd#jsonschema)\]  
Valid type for array parameters.

`properties` dict\[str, [JSONSchema](inspect_ai.util.qmd#jsonschema)\] \| None  
Valid fields for object parametrs.

`additionalProperties` Optional\[[JSONSchema](inspect_ai.util.qmd#jsonschema)\] \| bool \| None  
Are additional properties allowed?

`anyOf` list\[[JSONSchema](inspect_ai.util.qmd#jsonschema)\] \| None  
Valid types for union parameters.

`required` list\[str\] \| None  
Required fields for object parameters.

### json_schema

Provide a JSON Schema for the specified type.

Schemas can be automatically inferred for a wide variety of Python class
types including Pydantic BaseModel, dataclasses, and typed dicts.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/068717692fe4793cab9ed878842d76879b78b9b2/src/inspect_ai/util/_json.py#L64)

``` python
def json_schema(t: Type[Any]) -> JSONSchema
```

`t` Type\[Any\]  
Python type
