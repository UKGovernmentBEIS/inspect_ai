# inspect_ai.solver


## Generation

### generate

Generate output from the model and append it to task message history.

generate() is the default solver if none is specified for a given task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_solver.py#L264)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_use_tools.py#L11)

``` python
@solver
def use_tools(
    *tools: Tool | ToolDef | ToolSource | Sequence[Tool | ToolDef | ToolSource],
    tool_choice: ToolChoice | None = "auto",
    append: bool = False,
) -> Solver
```

`*tools` [Tool](inspect_ai.tool.qmd#tool) \| [ToolDef](inspect_ai.tool.qmd#tooldef) \| [ToolSource](inspect_ai.tool.qmd#toolsource) \| Sequence\[[Tool](inspect_ai.tool.qmd#tool) \| [ToolDef](inspect_ai.tool.qmd#tooldef) \| [ToolSource](inspect_ai.tool.qmd#toolsource)\]  
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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_prompt.py#L17)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_prompt.py#L45)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_prompt.py#L77)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_prompt.py#L104)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_prompt.py#L142)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_critique.py#L13)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_multiple_choice.py#L197)

``` python
@solver
def multiple_choice(
    *,
    template: str | None = None,
    cot: bool = False,
    multiple_correct: bool = False,
    max_tokens: int | None = None,
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

`max_tokens` int \| None  
Default `None`. Controls the number of tokens generated through the call
to generate().

`**kwargs` Unpack\[DeprecatedArgs\]  
Deprecated arguments for backward compatibility.

## Composition

### chain

Compose a solver from multiple other solvers and/or agents.

Solvers are executed in turn, and a solver step event is added to the
transcript for each. If a solver returns a state with `completed=True`,
the chain is terminated early.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_chain.py#L12)

``` python
@solver
def chain(
    *solvers: Solver | Agent | list[Solver] | list[Solver | Agent],
) -> Solver
```

`*solvers` [Solver](inspect_ai.solver.qmd#solver) \| [Agent](inspect_ai.agent.qmd#agent) \| list\[[Solver](inspect_ai.solver.qmd#solver)\] \| list\[[Solver](inspect_ai.solver.qmd#solver) \| [Agent](inspect_ai.agent.qmd#agent)\]  
One or more solvers or agents to chain together.

### fork

Fork the TaskState and evaluate it against multiple solvers in parallel.

Run several solvers against independent copies of a TaskState. Each
Solver gets its own copy of the TaskState and is run (in parallel) in an
independent Subtask (meaning that is also has its own independent Store
that doesn’t affect the Store of other subtasks or the parent).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_fork.py#L25)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_solver.py#L77)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_solver.py#L64)

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
sample’s evaluation. It allows us to maintain the manipulated message
history, the tools available to the model, the final output of the
model, and whether the task is completed or has hit a limit.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_task_state.py#L136)

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
the last chat message

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
exceeded, and also checks for an operator interrupt of the sample.

`target` [Target](inspect_ai.scorer.qmd#target)  
The scoring target for this `Sample`.

`scores` dict\[str, [Score](inspect_ai.scorer.qmd#score)\] \| None  
Scores yielded by running task.

`uuid` str  
Globally unique identifier for sample run.

#### Methods

metadata_as  
Pydantic model interface to metadata.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_task_state.py#L387)

``` python
def metadata_as(self, metadata_cls: Type[MT]) -> MT
```

`metadata_cls` Type\[MT\]  
Pydantic model type

store_as  
Pydantic model interface to the store.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_task_state.py#L401)

``` python
def store_as(self, model_cls: Type[SMT], instance: str | None = None) -> SMT
```

`model_cls` Type\[SMT\]  
Pydantic model type (must derive from StoreModel)

`instance` str \| None  
Optional instances name for store (enables multiple instances of a given
StoreModel type within a single sample)

### Generate

Generate using the model and add the assistant message to the task
state.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_solver.py#L36)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/solver/_solver.py#L154)

``` python
def solver(
    name: str | Callable[P, SolverType],
) -> Callable[[Callable[P, Solver]], Callable[P, Solver]] | Callable[P, Solver]
```

`name` str \| Callable\[P, SolverType\]  
Optional name for solver. If the decorator has no name argument then the
name of the underlying Callable\[P, SolverType\] object will be used to
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
