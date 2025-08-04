# inspect_ai.agent


## Agents

### react

Extensible ReAct agent based on the paper [ReAct: Synergizing Reasoning
and Acting in Language Models](https://arxiv.org/abs/2210.03629).

Provide a `name` and `description` for the agent if you plan on using it
in a multi-agent system (this is so other agents can clearly identify
its name and purpose). These fields are not required when using
`react()` as a top-level solver.

The agent runs a tool use loop until the model submits an answer using
the `submit()` tool. Use `instructions` to tailor the agent’s system
message (the default `instructions` provides a basic ReAct prompt).

Use the `attempts` option to enable additional submissions if the
initial submission(s) are incorrect (by default, no additional attempts
are permitted).

By default, the model will be urged to continue if it fails to call a
tool. Customise this behavior using the `on_continue` option.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_react.py#L36)

``` python
@agent
def react(
    *,
    name: str | None = None,
    description: str | None = None,
    prompt: str | AgentPrompt | None = AgentPrompt(),
    tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    model: str | Model | Agent | None = None,
    attempts: int | AgentAttempts = 1,
    submit: AgentSubmit | bool | None = None,
    on_continue: str | AgentContinue | None = None,
    truncation: Literal["auto", "disabled"] | MessageFilter = "disabled",
) -> Agent
```

`name` str \| None  
Agent name (required when using with `handoff()` or `as_tool()`)

`description` str \| None  
Agent description (required when using with `handoff()` or `as_tool()`)

`prompt` str \| [AgentPrompt](inspect_ai.agent.qmd#agentprompt) \| None  
Prompt for agent. Includes agent-specific contextual `instructions` as
well as an optional `assistant_prompt` and `handoff_prompt` (for agents
that use handoffs). both are provided by default but can be removed or
customized). Pass `str` to specify the instructions and use the defaults
for handoff and prompt messages.

`tools` Sequence\[[Tool](inspect_ai.tool.qmd#tool) \| [ToolDef](inspect_ai.tool.qmd#tooldef) \| [ToolSource](inspect_ai.tool.qmd#toolsource)\] \| None  
Tools available for the agent.

`model` str \| [Model](inspect_ai.model.qmd#model) \| [Agent](inspect_ai.agent.qmd#agent) \| None  
Model to use for agent (defaults to currently evaluated model).

`attempts` int \| [AgentAttempts](inspect_ai.agent.qmd#agentattempts)  
Configure agent to make multiple attempts.

`submit` [AgentSubmit](inspect_ai.agent.qmd#agentsubmit) \| bool \| None  
Use a submit tool for reporting the final answer. Defaults to `True`
which uses the default submit behavior. Pass an `AgentSubmit` to
customize the behavior or pass `False` to disable the submit tool.

`on_continue` str \| [AgentContinue](inspect_ai.agent.qmd#agentcontinue) \| None  
Message to play back to the model to urge it to continue when it stops
calling tools. Use the placeholder {submit} to refer to the submit tool
within the message. Alternatively, an async function to call to
determine whether the loop should continue and what message to play
back. Note that this function is called on *every* iteration of the loop
so if you only want to send a message back when the model fails to call
tools you need to code that behavior explicitly.

`truncation` Literal\['auto', 'disabled'\] \| [MessageFilter](inspect_ai.analysis.qmd#messagefilter)  
Truncate the conversation history in the event of a context window
overflow. Defaults to “disabled” which does no truncation. Pass “auto”
to use `trim_messages()` to reduce the context size. Pass a
`MessageFilter` function to do custom truncation.

### bridge

Bridge an external agent into an Inspect Agent.

See documentation at <https://inspect.aisi.org.uk/agent-bridge.html>

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_bridge/bridge.py#L15)

``` python
@agent
def bridge(agent: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> Agent
```

`agent` Callable\[\[dict\[str, Any\]\], Awaitable\[dict\[str, Any\]\]\]  
Callable which takes a sample `dict` and returns a result `dict`.

### human_cli

Human CLI agent for tasks that run in a sandbox.

The Human CLI agent installs agent task tools in the default sandbox and
presents the user with both task instructions and documentation for the
various tools (e.g. `task submit`, `task start`, `task stop`
`task instructions`, etc.). A human agent panel is displayed with
instructions for logging in to the sandbox.

If the user is running in VS Code with the Inspect extension, they will
also be presented with links to login to the sandbox using a VS Code
Window or Terminal.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_human/agent.py#L16)

``` python
@agent
def human_cli(
    answer: bool | str = True,
    intermediate_scoring: bool = False,
    record_session: bool = True,
    user: str | None = None,
) -> Agent
```

`answer` bool \| str  
Is an explicit answer required for this task or is it scored based on
files in the container? Pass a `str` with a regex to validate that the
answer matches the expected format.

`intermediate_scoring` bool  
Allow the human agent to check their score while working.

`record_session` bool  
Record all user commands and outputs in the sandbox bash session.

`user` str \| None  
User to login as. Defaults to the sandbox environment’s default user.

## Execution

### handoff

Create a tool that enables models to handoff to agents.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_handoff.py#L19)

``` python
def handoff(
    agent: Agent,
    description: str | None = None,
    input_filter: MessageFilter | None = None,
    output_filter: MessageFilter | None = None,
    tool_name: str | None = None,
    limits: list[Limit] = [],
    **agent_kwargs: Any,
) -> Tool
```

`agent` [Agent](inspect_ai.agent.qmd#agent)  
Agent to hand off to.

`description` str \| None  
Handoff tool description (defaults to agent description)

`input_filter` [MessageFilter](inspect_ai.analysis.qmd#messagefilter) \| None  
Filter to modify the message history before calling the tool. Use the
built-in `remove_tools` filter to remove all tool calls or alternatively
specify a custom `MessageFilter` function.

`output_filter` [MessageFilter](inspect_ai.analysis.qmd#messagefilter) \| None  
Filter to modify the message history after calling the tool. Use the
built-in `last_message` filter to return only the last message or
alternatively specify a custom `MessageFilter` function.

`tool_name` str \| None  
Alternate tool name (defaults to `transfer_to_{agent_name}`)

`limits` list\[[Limit](inspect_ai.util.qmd#limit)\]  
List of limits to apply to the agent. Limits are scoped to each handoff
to the agent. Should a limit be exceeded, the agent stops and a user
message is appended explaining that a limit was exceeded.

`**agent_kwargs` Any  
Arguments to curry to `Agent` function (arguments provided here will not
be presented to the model as part of the tool interface).

### run

Run an agent.

The input messages(s) will be copied prior to running so are not
modified in place.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_run.py#L33)

``` python
async def run(
    agent: Agent,
    input: str | list[ChatMessage] | AgentState,
    limits: list[Limit] = [],
    *,
    name: str | None = None,
    **agent_kwargs: Any,
) -> AgentState | tuple[AgentState, LimitExceededError | None]
```

`agent` [Agent](inspect_ai.agent.qmd#agent)  
Agent to run.

`input` str \| list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\] \| [AgentState](inspect_ai.agent.qmd#agentstate)  
Agent input (string, list of messages, or an `AgentState`).

`limits` list\[[Limit](inspect_ai.util.qmd#limit)\]  
List of limits to apply to the agent. Should one of these limits be
exceeded, the `LimitExceededError` is caught and returned.

`name` str \| None  
Optional display name for the transcript entry. If not provided, the
agent’s name as defined in the registry will be used.

`**agent_kwargs` Any  
Additional arguments to pass to agent.

### as_tool

Convert an agent to a tool.

By default the model will see all of the agent’s arguments as tool
arguments (save for `state` which is converted to an `input` arguments
of type `str`). Provide optional `agent_kwargs` to mask out agent
parameters with default values (these parameters will not be presented
to the model as part of the tool interface)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_as_tool.py#L19)

``` python
@tool
def as_tool(
    agent: Agent,
    description: str | None = None,
    limits: list[Limit] = [],
    **agent_kwargs: Any,
) -> Tool
```

`agent` [Agent](inspect_ai.agent.qmd#agent)  
Agent to convert.

`description` str \| None  
Tool description (defaults to agent description)

`limits` list\[[Limit](inspect_ai.util.qmd#limit)\]  
List of limits to apply to the agent. Should a limit be exceeded, the
tool call ends and returns an error explaining that a limit was
exceeded.

`**agent_kwargs` Any  
Arguments to curry to Agent function (arguments provided here will not
be presented to the model as part of the tool interface).

### as_solver

Convert an agent to a solver.

Note that agents used as solvers will only receive their first parameter
(`state`). Any other parameters must provide appropriate defaults or be
explicitly specified in `agent_kwargs`

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_as_solver.py#L20)

``` python
def as_solver(agent: Agent, limits: list[Limit] = [], **agent_kwargs: Any) -> Solver
```

`agent` [Agent](inspect_ai.agent.qmd#agent)  
Agent to convert.

`limits` list\[[Limit](inspect_ai.util.qmd#limit)\]  
List of limits to apply to the agent. Should a limit be exceeded, the
Sample ends and proceeds to scoring.

`**agent_kwargs` Any  
Arguments to curry to Agent function (required if the agent has
parameters without default values).

## Filters

### remove_tools

Remove tool calls from messages.

Removes all instances of `ChatMessageTool` as well as the `tool_calls`
field from `ChatMessageAssistant`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_filter.py#L13)

``` python
async def remove_tools(messages: list[ChatMessage]) -> list[ChatMessage]
```

`messages` list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Messages to remove tool calls from.

### last_message

Remove all but the last message.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_filter.py#L36)

``` python
async def last_message(messages: list[ChatMessage]) -> list[ChatMessage]
```

`messages` list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Target messages.

### MessageFilter

Filter messages sent to or received from agent handoffs.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_filter.py#L9)

``` python
MessageFilter = Callable[[list[ChatMessage]], Awaitable[list[ChatMessage]]]
```

## Protocol

### Agent

Agents perform tasks and participate in conversations.

Agents are similar to tools however they are participants in
conversation history and can optionally append messages and model output
to the current conversation state.

You can give the model a tool that enables handoff to your agent using
the `handoff()` function.

You can create a simple tool (that receives a string as input) from an
agent using `as_tool()`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_agent.py#L92)

``` python
class Agent(Protocol):
    async def __call__(
        self,
        state: AgentState,
        *args: Any,
        **kwargs: Any,
    ) -> AgentState
```

`state` [AgentState](inspect_ai.agent.qmd#agentstate)  
Agent state (conversation history and last model output)

`*args` Any  
Arguments for the agent.

`**kwargs` Any  
Keyword arguments for the agent.

### AgentState

Agent state.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_agent.py#L33)

``` python
class AgentState
```

#### Attributes

`messages` list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Conversation history.

`output` [ModelOutput](inspect_ai.model.qmd#modeloutput)  
Model output.

### agent

Decorator for registering agents.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_agent.py#L140)

``` python
def agent(
    func: Callable[P, Agent] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Callable[P, Agent] | Callable[[Callable[P, Agent]], Callable[P, Agent]]
```

`func` Callable\[P, [Agent](inspect_ai.agent.qmd#agent)\] \| None  
Agent function

`name` str \| None  
Optional name for agent. If the decorator has no name argument then the
name of the agent creation function will be used as the name of the
agent.

`description` str \| None  
Description for the agent when used as an ordinary tool or handoff tool.

### agent_with

Agent with modifications to name and/or description

This function modifies the passed agent in place and returns it. If you
want to create multiple variations of a single agent using
`agent_with()` you should create the underlying agent multiple times.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_agent.py#L214)

``` python
def agent_with(
    agent: Agent,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Agent
```

`agent` [Agent](inspect_ai.agent.qmd#agent)  
Agent instance to modify.

`name` str \| None  
Agent name (optional).

`description` str \| None  
Agent description (optional).

### is_agent

Check if an object is an Agent.

Determines if the provided object is registered as an Agent in the
system registry. When this function returns True, type checkers will
recognize ‘obj’ as an Agent type.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_agent.py#L273)

``` python
def is_agent(obj: Any) -> TypeGuard[Agent]
```

`obj` Any  
Object to check against the registry.

## Types

### AgentPrompt

Prompt for agent.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_types.py#L33)

``` python
class AgentPrompt(NamedTuple)
```

#### Attributes

`instructions` str \| None  
Agent-specific contextual instructions.

`handoff_prompt` str \| None  
Prompt used when there are additional handoff agents active. Pass `None`
for no additional handoff prompt.

`assistant_prompt` str \| None  
Prompt for assistant (covers tool use, CoT, etc.). Pass `None` for no
additional assistant prompt.

`submit_prompt` str \| None  
Prompt to tell the model about the submit tool.

Pass `None` for no additional submit prompt.

This prompt is not used if the `assistant_prompt` contains a {submit}
placeholder.

### AgentAttempts

Configure a react agent to make multiple attempts.

Submissions are evaluated using the task’s main scorer, with value of
1.0 indicating a correct answer. Scorer values are converted to float
(e.g. “C” becomes 1.0) using the standard value_to_float() function.
Provide an alternate conversion scheme as required via `score_value`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_types.py#L76)

``` python
class AgentAttempts(NamedTuple)
```

#### Attributes

`attempts` int  
Maximum number of attempts.

`incorrect_message` str \| Callable\[\[[AgentState](inspect_ai.agent.qmd#agentstate), list\[[Score](inspect_ai.scorer.qmd#score)\]\], Awaitable\[str\]\]  
User message reply for an incorrect submission from the model.
Alternatively, an async function which returns a message.

`score_value` ValueToFloat  
Function used to extract float from scores (defaults to standard
value_to_float())

### AgentContinue

Function called to determine whether the agent should continue.

Returns `True` to continue (with no additional messages inserted),
return `False` to stop. Returns `str` to continue with an additional
custom user message inserted.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_types.py#L67)

``` python
AgentContinue: TypeAlias = Callable[[AgentState], Awaitable[bool | str]]
```

### AgentSubmit

Configure the submit tool of a react agent.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/b9433db1cdc8b2f9c21dfbf57f2ade2e5e2188df/src/inspect_ai/agent/_types.py#L98)

``` python
class AgentSubmit(NamedTuple)
```

#### Attributes

`name` str \| None  
Name for submit tool (defaults to ‘submit’).

`description` str \| None  
Description of submit tool (defaults to ‘Submit an answer for
evaluation’).

`tool` [Tool](inspect_ai.tool.qmd#tool) \| None  
Alternate implementation for submit tool.

The tool can provide its `name` and `description` internally, or these
values can be overriden by the `name` and `description` fields in
`AgentSubmit`

The tool should return the `answer` provided to it for scoring.

`answer_only` bool  
Set the completion to only the answer provided by the submit tool.

By default, the answer is appended (with `answer_delimiter`) to whatever
other content the model generated along with the call to `submit()`.

`answer_delimiter` str  
Delimter used when appending submit tool answer to other content the
model generated along with the call to `submit()`.

`keep_in_messages` bool  
Keep the submit tool call in the message history.

Defaults to `False`, which results in calls to the `submit()` tool being
removed from message history so that the model’s response looks like a
standard assistant message.

This is particularly important for multi-agent systems where the
presence of `submit()` calls in the history can cause coordinator agents
to terminate early because they think they are done. You should
therefore not set this to `True` if you are using `handoff()` in a
multi-agent system.
