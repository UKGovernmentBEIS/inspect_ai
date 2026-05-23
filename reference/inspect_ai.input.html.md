# inspect_ai.input – Inspect

## Functions

### request_input

Ask the user a structured question and wait for an answer.

Runs configured notifiers in parallel with the answer-collecting handler. A custom handler (if configured) runs first with a timeout; on `None` or timeout, dispatches to the built-in handler selection (console / panel / ACP, depending on runtime context).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f76620cb8622b379c6f17ccd98d323d3c99ae00b/src/inspect_ai/input/request.py#L16)

``` python
async def request_input(
    *,
    message: str,
    schema: ElicitationSchema,
    metadata: dict[str, Any] | None = None,
) -> InputResult
```

`message` str  
Prompt shown to the user.

`schema` ElicitationSchema  
ACP `ElicitationSchema` describing the answer fields.

`metadata` dict\[str, Any\] \| None  
Free-form passthrough for handler↔︎notifier correlation.

## Types

### InputConfig

Resolved input subsystem configuration for an eval run.

Carries the handler that collects answers, the notifiers that alert the user (and any other listeners) when a question is posted, and the timeouts that bound each. Construct directly with already-resolved callables, or build from an [InputConfigSpec](../reference/inspect_ai.input.html.md#inputconfigspec) via `resolve_input_config`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f76620cb8622b379c6f17ccd98d323d3c99ae00b/src/inspect_ai/input/_config.py#L17)

``` python
@dataclass
class InputConfig
```

#### Attributes

`input_handler` [InputHandler](../reference/inspect_ai.input.html.md#inputhandler) \| None  
Handler that collects an answer; `None` falls back to the built-in handler.

`input_handler_timeout` float  
Seconds to wait for the custom handler before falling back to the built-in handler.

`input_notifiers` list\[[InputNotifier](../reference/inspect_ai.input.html.md#inputnotifier)\]  
Fire-and-forget notifiers run in parallel with the handler.

`notifier_timeout` float  
Per-notifier timeout in seconds; notifiers exceeding it are cancelled silently.

### InputRequest

A structured question posted to the user via `request_input`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f76620cb8622b379c6f17ccd98d323d3c99ae00b/src/inspect_ai/input/_types.py#L16)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f76620cb8622b379c6f17ccd98d323d3c99ae00b/src/inspect_ai/input/_types.py#L27)

``` python
@dataclass
class InputResult
```

#### Attributes

`outcome` [InputOutcome](../reference/inspect_ai.input.html.md#inputoutcome)  
How the interaction concluded.

`content` dict\[str, Any\] \| None  
The user’s answer (keyed by `ElicitationSchema` property name) when `outcome == "accepted"`; otherwise `None`.

### InputNotification

Payload delivered to input notifiers when a question is posted.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f76620cb8622b379c6f17ccd98d323d3c99ae00b/src/inspect_ai/input/_types.py#L38)

``` python
@dataclass
class InputNotification
```

#### Attributes

`action` Literal\['posted', 'answered', 'cancelled'\]  
Lifecycle action being notified.

Possible values: “posted”: The question has just been shown to the user. “answered”: The user has submitted an answer. “cancelled”: The question was withdrawn before an answer was provided.

`request` [InputRequest](../reference/inspect_ai.input.html.md#inputrequest)  
The question being notified about.

`sample_id` str  
Identifier of the active sample (empty string when called outside an eval scope).

`task_name` str  
Name of the active task (empty string when called outside an eval scope).

`metadata` dict\[str, Any\] \| None  
Caller-supplied passthrough for handler↔︎notifier correlation.

### InputHandler

Async callable that collects an answer for an `ask_user` interaction.

Receives an [InputRequest](../reference/inspect_ai.input.html.md#inputrequest) carrying the prompt and answer schema. Returns an [InputResult](../reference/inspect_ai.input.html.md#inputresult) if the handler took responsibility for the question, or `None` to defer to the built-in handler selection (console / panel / ACP).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f76620cb8622b379c6f17ccd98d323d3c99ae00b/src/inspect_ai/input/_types.py#L64)

``` python
InputHandler = Callable[[InputRequest], Awaitable[InputResult | None]]
```

### InputNotifier

Async callable invoked to alert the user that a question is waiting.

Notifiers run in parallel with the handler and are fire-and-forget: exceptions are logged and swallowed, and per-notifier timeouts apply.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f76620cb8622b379c6f17ccd98d323d3c99ae00b/src/inspect_ai/input/_types.py#L73)

``` python
InputNotifier = Callable[[InputNotification], Awaitable[None]]
```

### InputOutcome

Outcome of an `ask_user` interaction.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f76620cb8622b379c6f17ccd98d323d3c99ae00b/src/inspect_ai/input/_types.py#L6)

``` python
InputOutcome = Literal["accepted", "declined", "cancelled"]
```

## Config

### InputConfigSpec

Declarative input config (YAML/JSON-parseable, registry-name based).

Resolved into an [InputConfig](../reference/inspect_ai.input.html.md#inputconfig) via `resolve_input_config` (which instantiates each named handler/notifier from the registry) and logged back on `EvalConfig.input_config` for retries.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f76620cb8622b379c6f17ccd98d323d3c99ae00b/src/inspect_ai/input/_config.py#L87)

``` python
class InputConfigSpec(BaseModel)
```

#### Attributes

`input_handler` [InputHandlerSpec](../reference/inspect_ai.input.html.md#inputhandlerspec) \| None  
Handler to install for the run.

`input_handler_timeout` float \| None  
Override for `InputConfig.input_handler_timeout`.

`input_notifiers` list\[[InputNotifierSpec](../reference/inspect_ai.input.html.md#inputnotifierspec)\] \| None  
Notifiers to install for the run.

`notifier_timeout` float \| None  
Override for `InputConfig.notifier_timeout`.

### InputHandlerSpec

Declarative spec for a registered input handler.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f76620cb8622b379c6f17ccd98d323d3c99ae00b/src/inspect_ai/input/_config.py#L67)

``` python
class InputHandlerSpec(BaseModel)
```

#### Attributes

`name` str  
Registered handler name.

`args` dict\[str, Any\]  
Keyword arguments forwarded to the handler factory.

### InputNotifierSpec

Declarative spec for a registered input notifier.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f76620cb8622b379c6f17ccd98d323d3c99ae00b/src/inspect_ai/input/_config.py#L77)

``` python
class InputNotifierSpec(BaseModel)
```

#### Attributes

`name` str  
Registered notifier name.

`args` dict\[str, Any\]  
Keyword arguments forwarded to the notifier factory.

## Decorators

### input_handler

Decorator for registering input handlers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f76620cb8622b379c6f17ccd98d323d3c99ae00b/src/inspect_ai/input/registry.py#L29)

``` python
def input_handler(*args: Any, name: str | None = None, **attribs: Any) -> Any
```

`*args` Any  
Function returning [InputHandler](../reference/inspect_ai.input.html.md#inputhandler) targeted by plain handler decorator without attributes (e.g. `@input_handler`)

`name` str \| None  
Optional name for handler. If the decorator has no name argument then the name of the function will be used to automatically assign a name.

`**attribs` Any  
Additional handler attributes.

### input_notifier

Decorator for registering input notifiers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f76620cb8622b379c6f17ccd98d323d3c99ae00b/src/inspect_ai/input/registry.py#L94)

``` python
def input_notifier(*args: Any, name: str | None = None, **attribs: Any) -> Any
```

`*args` Any  
Function returning [InputNotifier](../reference/inspect_ai.input.html.md#inputnotifier) targeted by plain notifier decorator without attributes (e.g. `@input_notifier`)

`name` str \| None  
Optional name for notifier. If the decorator has no name argument then the name of the function will be used to automatically assign a name.

`**attribs` Any  
Additional notifier attributes.
