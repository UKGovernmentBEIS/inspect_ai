# inspect_ai.solver


## Generation

### generate

Generate output from the model and append it to task message history.

generate() is the default solver if none is specified for a given task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_solver.py#L251)

``` python
@solver
def generate(
    tool_calls: Literal["loop", "single", "none"] = "loop",
    cache: bool | CachePolicy = False,
    **kwargs: Unpack[GenerateConfigArgs],
) -> Solver
```

`tool_calls` Literal\['loop', 'single', 'none'\]  
Resolve tool calls: - `"loop"` resolves tools calls and then invokes
`generate()`, proceeding in a loop which terminates when there are no
more tool calls or `message_limit` or `token_limit` is exceeded. This is
the default behavior. - `"single"` resolves at most a single set of tool
calls and then returns. - `"none"` does not resolve tool calls at all
(in this case you will need to invoke `call_tools()` directly).

`cache` bool \| [CachePolicy](inspect_ai.model.qmd#cachepolicy)  
(bool \| CachePolicy): Caching behaviour for generate responses
(defaults to no caching).

`**kwargs` Unpack\[[GenerateConfigArgs](inspect_ai.model.qmd#generateconfigargs)\]  
Optional generation config arguments.

### use_tools

Inject tools into the task state to be used in generate().

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_use_tools.py#L8)

``` python
@solver
def use_tools(
    *tools: Tool | list[Tool],
    tool_choice: ToolChoice | None = "auto",
    append: bool = False,
) -> Solver
```

`*tools` [Tool](inspect_ai.tool.qmd#tool) \| list\[[Tool](inspect_ai.tool.qmd#tool)\]  
One or more tools or lists of tools to make available to the model. If
no tools are passed, then no change to the currently available set of
`tools` is made.

`tool_choice` [ToolChoice](inspect_ai.tool.qmd#toolchoice) \| None  
Directive indicating which tools the model should use. If `None` is
passed, then no change to `tool_choice` is made.

`append` bool  
If `True`, then the passed-in tools are appended to the existing tools;
otherwise any existing tools are replaced (the default)

## Prompting

### prompt_template

Parameterized prompt template.

Prompt template containing a `{prompt}` placeholder and any number of
additional `params`. All values contained in sample `metadata` and
`store` are also automatically included in the `params`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_prompt.py#L17)

``` python
@solver
def prompt_template(template: str, **params: Any) -> Solver
```

`template` str  
Template for prompt.

`**params` Any  
Parameters to fill into the template.

### system_message

Solver which inserts a system message into the conversation.

System message template containing any number of optional `params`. for
substitution using the `str.format()` method. All values contained in
sample `metadata` and `store` are also automatically included in the
`params`.

The new message will go after other system messages (if there are none
it will be inserted at the beginning of the conversation).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_prompt.py#L45)

``` python
@solver
def system_message(template: str, **params: Any) -> Solver
```

`template` str  
Template for system message.

`**params` Any  
Parameters to fill into the template.

### user_message

Solver which inserts a user message into the conversation.

User message template containing any number of optional `params`. for
substitution using the `str.format()` method. All values contained in
sample `metadata` and `store` are also automatically included in the
`params`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_prompt.py#L77)

``` python
@solver
def user_message(template: str, **params: Any) -> Solver
```

`template` str  
Template for user message.

`**params` Any  
Parameters to fill into the template.

### assistant_message

Solver which inserts an assistant message into the conversation.

Assistant message template containing any number of optional `params`.
for substitution using the `str.format()` method. All values contained
in sample `metadata` and `store` are also automatically included in the
`params`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_prompt.py#L104)

``` python
@solver
def assistant_message(template: str, **params: Any) -> Solver
```

`template` str  
Template for assistant message.

`**params` Any  
Parameters to fill into the template.

### chain_of_thought

Solver which modifies the user prompt to encourage chain of thought.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_prompt.py#L140)

``` python
@solver
def chain_of_thought(template: str = DEFAULT_COT_TEMPLATE) -> Solver
```

`template` str  
String or path to file containing CoT template. The template uses a
single variable: `prompt`.

### self_critique

Solver which uses a model to critique the original answer.

The `critique_template` is used to generate a critique and the
`completion_template` is used to play that critique back to the model
for an improved response. Note that you can specify an alternate `model`
for critique (you don’t need to use the model being evaluated).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_critique.py#L13)

``` python
@solver
def self_critique(
    critique_template: str | None = None,
    completion_template: str | None = None,
    model: str | Model | None = None,
) -> Solver
```

`critique_template` str \| None  
String or path to file containing critique template. The template uses
two variables: `question` and `completion`. Variables from sample
`metadata` are also available in the template.

`completion_template` str \| None  
String or path to file containing completion template. The template uses
three variables: `question`, `completion`, and `critique`

`model` str \| [Model](inspect_ai.model.qmd#model) \| None  
Alternate model to be used for critique (by default the model being
evaluated is used).

### multiple_choice

Multiple choice question solver. Formats a multiple choice question
prompt, then calls `generate()`.

Note that due to the way this solver works, it has some constraints:

1.  The `Sample` must have the `choices` attribute set.
2.  The only built-in compatible scorer is the `choice` scorer.
3.  It calls `generate()` internally, so you don’t need to call it again

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_multiple_choice.py#L214)

``` python
@solver
def multiple_choice(
    *,
    template: str | None = None,
    cot: bool = False,
    multiple_correct: bool = False,
    **kwargs: Unpack[DeprecatedArgs],
) -> Solver
```

`template` str \| None  
Template to use for the multiple choice question. The defaults vary
based on the options and are taken from the `MultipleChoiceTemplate`
enum. The template will have questions and possible answers substituted
into it before being sent to the model. Consequently it requires three
specific template variables:

- `{question}`: The question to be asked.
- `{choices}`: The choices available, which will be formatted as a list
  of A) … B) … etc. before sending to the model.
- `{letters}`: (optional) A string of letters representing the choices,
  e.g. “A,B,C”. Used to be explicit to the model about the possible
  answers.

`cot` bool  
Default `False`. Whether the solver should perform chain-of-thought
reasoning before answering. NOTE: this has no effect if you provide a
custom template.

`multiple_correct` bool  
Default `False`. Whether to allow multiple answers to the multiple
choice question. For example, “What numbers are squares? A) 3, B) 4, C)
9” has multiple correct answers, B and C. Leave as `False` if there’s
exactly one correct answer from the choices available. NOTE: this has no
effect if you provide a custom template.

`**kwargs` Unpack\[DeprecatedArgs\]  
Deprecated arguments for backward compatibility.

## Agents

### basic_agent

Basic ReAct agent.

Agent that runs a tool use loop until the model submits an answer using
the `submit()` tool. Tailor the model’s instructions by passing a
`system_message()` and/or other steps to `init` (if no `init` is
specified then a default system message will be used). Use
`max_attempts` to support additional submissions if the initial
submission(s) are incorrect.

Submissions are evaluated using the task’s main scorer, with value of
1.0 indicating a correct answer. Scorer values are converted to float
(e.g. “C” becomes 1.0) using the standard value_to_float() function.
Provide an alternate conversion scheme as required via `score_value`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_basic_agent.py#L50)

``` python
@solver
def basic_agent(
    *,
    init: Solver | list[Solver] | None = None,
    tools: list[Tool] | Solver | None = None,
    cache: bool | CachePolicy = False,
    max_attempts: int = 1,
    message_limit: int | None = None,
    token_limit: int | None = None,
    max_tool_output: int | None = None,
    score_value: ValueToFloat | None = None,
    incorrect_message: str
    | Callable[
        [TaskState, list[Score]], str | Awaitable[str]
    ] = DEFAULT_INCORRECT_MESSAGE,
    continue_message: str = DEFAULT_CONTINUE_MESSAGE,
    submit_name: str = DEFAULT_SUBMIT_NAME,
    submit_description: str = DEFAULT_SUBMIT_DESCRIPTION,
    **kwargs: Unpack[BasicAgentDeprecatedArgs],
) -> Solver
```

`init` [Solver](inspect_ai.solver.qmd#solver) \| list\[[Solver](inspect_ai.solver.qmd#solver)\] \| None  
Agent initialisation (defaults to system_message with basic ReAct
prompt)

`tools` list\[[Tool](inspect_ai.tool.qmd#tool)\] \| [Solver](inspect_ai.solver.qmd#solver) \| None  
Tools available for the agent. Either a list of tools or a Solver that
can yield dynamic tools per-sample.

`cache` bool \| [CachePolicy](inspect_ai.model.qmd#cachepolicy)  
Caching behaviour for generate responses (defaults to no caching).

`max_attempts` int  
Maximum number of submissions to accept before terminating.

`message_limit` int \| None  
Limit on messages in sample before terminating agent. If not specified,
will use limit_messages defined for the task. If there is none defined
for the task, 50 will be used as a default.

`token_limit` int \| None  
Limit on tokens used in sample before terminating agent.

`max_tool_output` int \| None  
Maximum output length (in bytes). Defaults to max_tool_output from
active GenerateConfig.

`score_value` ValueToFloat \| None  
Function used to extract float from scores (defaults to standard
value_to_float())

`incorrect_message` str \| Callable\[\[[TaskState](inspect_ai.solver.qmd#taskstate), list\[[Score](inspect_ai.scorer.qmd#score)\]\], str \| Awaitable\[str\]\]  
User message reply for an incorrect submission from the model.
Alternatively, a function which returns a message (function may
optionally be async)

`continue_message` str  
User message to urge the model to continue when it doesn’t make a tool
call.

`submit_name` str  
Name for tool used to make submissions (defaults to ‘submit’)

`submit_description` str  
Description of submit tool (defaults to ‘Submit an answer for
evaluation’)

`**kwargs` Unpack\[BasicAgentDeprecatedArgs\]  
Deprecated arguments for backward compatibility.

### human_agent

Human solver for agentic tasks that run in a Linux environment.

The Human agent solver installs agent task tools in the default sandbox
and presents the user with both task instructions and documentation for
the various tools (e.g. `task submit`, `task start`, `task stop`
`task instructions`, etc.). A human agent panel is displayed with
instructions for logging in to the sandbox.

If the user is running in VS Code with the Inspect extension, they will
also be presented with links to login to the sandbox using a VS Code
Window or Terminal.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_human_agent/agent.py#L14)

``` python
@solver
def human_agent(
    answer: bool | str = True,
    intermediate_scoring: bool = False,
    record_session: bool = True,
) -> Solver
```

`answer` bool \| str  
Is an explicit answer required for this task or is it scored based on
files in the container? Pass a `str` with a regex to validate that the
answer matches the expected format.

`intermediate_scoring` bool  
Allow the human agent to check their score while working.

`record_session` bool  
Record all user commands and outputs in the sandbox bash session.

### bridge

Bridge an external agent into an Inspect Solver.

See documentation at
<https://inspect.ai-safety-institute.org.uk/agent-bridge.html>

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_bridge/bridge.py#L16)

``` python
@solver
def bridge(agent: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> Solver
```

`agent` Callable\[\[dict\[str, Any\]\], Awaitable\[dict\[str, Any\]\]\]  
Callable which takes a sample `dict` and returns a result `dict`.

## Composition

### chain

Compose a solver from multiple other solvers.

Solvers are executed in turn, and a solver step event is added to the
transcript for each. If a solver returns a state with `completed=True`,
the chain is terminated early.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_chain.py#L9)

``` python
def chain(*solvers: Solver | list[Solver]) -> Solver
```

`*solvers` [Solver](inspect_ai.solver.qmd#solver) \| list\[[Solver](inspect_ai.solver.qmd#solver)\]  
One or more solvers or lists of solvers to chain together.

### fork

Fork the TaskState and evaluate it against multiple solvers in parallel.

Run several solvers against independent copies of a TaskState. Each
Solver gets its own copy of the TaskState and is run (in parallel) in an
independent Subtask (meaning that is also has its own independent Store
that doesn’t affect the Store of other subtasks or the parent).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_fork.py#L24)

``` python
async def fork(
    state: TaskState, solvers: Solver | list[Solver]
) -> TaskState | list[TaskState]
```

`state` [TaskState](inspect_ai.solver.qmd#taskstate)  
Beginning TaskState

`solvers` [Solver](inspect_ai.solver.qmd#solver) \| list\[[Solver](inspect_ai.solver.qmd#solver)\]  
Solvers to apply on the TaskState. Each Solver will get a standalone
copy of the TaskState.

## Types

### Solver

Contribute to solving an evaluation task.

Transform a `TaskState`, returning the new state. Solvers may optionally
call the `generate()` function to create a new state resulting from
model generation. Solvers may also do prompt engineering or other types
of elicitation.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_solver.py#L73)

``` python
class Solver(Protocol):
    async def __call__(
        self,
        state: TaskState,
        generate: Generate,
    ) -> TaskState
```

`state` [TaskState](inspect_ai.solver.qmd#taskstate)  
State for tasks being evaluated.

`generate` [Generate](inspect_ai.solver.qmd#generate)  
Function for generating outputs.

#### Examples

``` python
@solver
def prompt_cot(template: str) -> Solver:
    def solve(state: TaskState, generate: Generate) -> TaskState:
        # insert chain of thought prompt
        return state

    return solve
```

### SolverSpec

Solver specification used to (re-)create solvers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_solver.py#L60)

``` python
@dataclass(frozen=True)
class SolverSpec
```

#### Attributes

`solver` str  
Solver name (simple name or <file.py@name>).

`args` dict\[str, Any\]  
Solver arguments.

### TaskState

The `TaskState` represents the internal state of the `Task` being run
for a single `Sample`.

The `TaskState` is passed to and returned from each solver during a
sample’s evaluation. It allows us to manipulated the message history,
the tools available to the model, the final output of the model, and
whether the task is completed or has hit a limit.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_task_state.py#L129)

``` python
class TaskState
```

#### Attributes

`model` ModelName  
Name of model being evaluated.

`sample_id` int \| str  
Unique id for sample.

`epoch` int  
Epoch number for sample.

`input` str \| list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Input from the `Sample`, should be considered immutable.

`input_text` str  
Convenience function for accessing the initial input from the `Sample`
as a string.

If the `input` is a `list[ChatMessage]`, this will return the text from
the first chat message

`user_prompt` [ChatMessageUser](inspect_ai.model.qmd#chatmessageuser)  
User prompt for this state.

Tasks are very general and can have may types of inputs. However, in
many cases solvers assume they can interact with the state as a “chat”
in a predictable fashion (e.g. prompt engineering solvers). This
property enables easy read and write access to the user chat prompt.
Raises an exception if there is no user prompt

`metadata` dict\[str, Any\]  
Metadata from the `Sample` for this `TaskState`

`messages` list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Chat conversation history for sample.

This will generally get appended to every time a `generate` call is made
to the model. Useful for both debug and for solvers/scorers to assess
model performance or choose the next step.

`output` [ModelOutput](inspect_ai.model.qmd#modeloutput)  
The ‘final’ model output once we’ve completed all solving.

For simple evals this may just be the last `message` from the
conversation history, but more complex solvers may set this directly.

`store` [Store](inspect_ai.util.qmd#store)  
Store for shared data

`tools` list\[[Tool](inspect_ai.tool.qmd#tool)\]  
Tools available to the model.

`tool_choice` [ToolChoice](inspect_ai.tool.qmd#toolchoice) \| None  
Tool choice directive.

`message_limit` int \| None  
Limit on total messages allowed per conversation.

`token_limit` int \| None  
Limit on total tokens allowed per conversation.

`token_usage` int  
Total tokens used for the current sample.

`completed` bool  
Is the task completed.

Additionally, checks message and token limits and raises if they are
exceeded.

`target` [Target](inspect_ai.scorer.qmd#target)  
The scoring target for this `Sample`.

`scores` dict\[str, [Score](inspect_ai.scorer.qmd#score)\] \| None  
Scores yielded by running task.

#### Methods

metadata_as  
Pydantic model interface to metadata.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_task_state.py#L374)

``` python
def metadata_as(self, metadata_cls: Type[MT]) -> MT
```

`metadata_cls` Type\[MT\]  
Pydantic model type

store_as  
Pydantic model interface to the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_task_state.py#L388)

``` python
def store_as(self, model_cls: Type[SMT]) -> SMT
```

`model_cls` Type\[SMT\]  
Pydantic model type (must derive from StoreModel)

### Generate

Generate using the model and add the assistant message to the task
state.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_solver.py#L32)

``` python
class Generate(Protocol):
    async def __call__(
        self,
        state: TaskState,
        tool_calls: Literal["loop", "single", "none"] = "loop",
        cache: bool | CachePolicy = False,
        **kwargs: Unpack[GenerateConfigArgs],
    ) -> TaskState
```

`state` [TaskState](inspect_ai.solver.qmd#taskstate)  
Beginning task state.

`tool_calls` Literal\['loop', 'single', 'none'\]  
- `"loop"` resolves tools calls and then invokes `generate()`,
  proceeding in a loop which terminates when there are no more tool
  calls, or `message_limit` or `token_limit` is exceeded. This is the
  default behavior.
- `"single"` resolves at most a single set of tool calls and then
  returns.
- `"none"` does not resolve tool calls at all (in this case you will
  need to invoke `call_tools()` directly).

`cache` bool \| [CachePolicy](inspect_ai.model.qmd#cachepolicy)  
Caching behaviour for generate responses (defaults to no caching).

`**kwargs` Unpack\[[GenerateConfigArgs](inspect_ai.model.qmd#generateconfigargs)\]  
Optional generation config arguments.

## Decorators

### solver

Decorator for registering solvers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/22b7df17d5899a9e60a74bd080a2e1dc93596cb0/src/inspect_ai/solver/_solver.py#L146)

``` python
def solver(
    name: str | Callable[P, Solver],
) -> Callable[[Callable[P, Solver]], Callable[P, Solver]] | Callable[P, Solver]
```

`name` str \| Callable\[P, [Solver](inspect_ai.solver.qmd#solver)\]  
Optional name for solver. If the decorator has no name argument then the
name of the underlying Callable\[P, Solver\] object will be used to
automatically assign a name.

#### Examples

``` python
@solver
def prompt_cot(template: str) -> Solver:
    def solve(state: TaskState, generate: Generate) -> TaskState:
        # insert chain of thought prompt
        return state

    return solve
```
