# inspect_ai.agent – Inspect

## Agents

### react

Extensible ReAct agent based on the paper [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629).

Provide a `name` and `description` for the agent if you plan on using it in a multi-agent system (this is so other agents can clearly identify its name and purpose). These fields are not required when using [react()](../reference/inspect_ai.agent.html.md#react) as a top-level solver.

The agent runs a tool use loop until the model submits an answer using the `submit()` tool. Use `instructions` to tailor the agent’s system message (the default `instructions` provides a basic ReAct prompt).

Use the `attempts` option to enable additional submissions if the initial submission(s) are incorrect (by default, no additional attempts are permitted).

When using the `submit()` tool, the model will be urged to continue if it fails to call a tool. When not using a `submit()` tool, the agent will terminate if it fails to call a tool. Customise this behavior using the `on_continue` option.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_react.py#L50)

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
    retry_refusals: int | None = None,
    compaction: CompactionStrategy | None = None,
    truncation: Literal["auto", "disabled"] | MessageFilter = "disabled",
    approval: list[ApprovalPolicy] | None = None,
) -> Agent
```

`name` str \| None  
Agent name (required when using with [handoff()](../reference/inspect_ai.agent.html.md#handoff) or [as_tool()](../reference/inspect_ai.agent.html.md#as_tool))

`description` str \| None  
Agent description (required when using with [handoff()](../reference/inspect_ai.agent.html.md#handoff) or [as_tool()](../reference/inspect_ai.agent.html.md#as_tool))

`prompt` str \| [AgentPrompt](../reference/inspect_ai.agent.html.md#agentprompt) \| None  
Prompt for agent. Includes agent-specific contextual `instructions` as well as an optional `assistant_prompt` and `handoff_prompt` (for agents that use handoffs). both are provided by default but can be removed or customized). Pass `str` to specify the instructions and use the defaults for handoff and prompt messages.

`tools` Sequence\[[Tool](../reference/inspect_ai.tool.html.md#tool) \| [ToolDef](../reference/inspect_ai.tool.html.md#tooldef) \| [ToolSource](../reference/inspect_ai.tool.html.md#toolsource)\] \| None  
Tools available for the agent.

`model` str \| [Model](../reference/inspect_ai.model.html.md#model) \| [Agent](../reference/inspect_ai.agent.html.md#agent) \| None  
Model to use for agent (defaults to currently evaluated model).

`attempts` int \| [AgentAttempts](../reference/inspect_ai.agent.html.md#agentattempts)  
Configure agent to make multiple attempts.

`submit` [AgentSubmit](../reference/inspect_ai.agent.html.md#agentsubmit) \| bool \| None  
Use a submit tool for reporting the final answer. Defaults to `True` which uses the default submit behavior. Pass an [AgentSubmit](../reference/inspect_ai.agent.html.md#agentsubmit) to customize the behavior or pass `False` to disable the submit tool.

`on_continue` str \| [AgentContinue](../reference/inspect_ai.agent.html.md#agentcontinue) \| None  
Message to play back to the model to urge it to continue when it stops calling tools. Use the placeholder {submit} to refer to the submit tool within the message. Alternatively, an async function to call to determine whether the loop should continue and what message to play back. Note that this function is called on *every* iteration of the loop so if you only want to send a message back when the model fails to call tools you need to code that behavior explicitly.

`retry_refusals` int \| None  
Should refusals be retried? (pass number of times to retry)

`compaction` [CompactionStrategy](../reference/inspect_ai.model.html.md#compactionstrategy) \| None  
Compact the conversation when it it is close to overflowing the model’s context window. See [Compaction](https://inspect.aisi.org.uk/compaction.html) for details on compaction strategies.

`truncation` Literal\['auto', 'disabled'\] \| [MessageFilter](../reference/inspect_ai.analysis.html.md#messagefilter)  
Truncate the conversation history in the event of a context window overflow. Defaults to “disabled” which does no truncation. Pass “auto” to use [trim_messages()](../reference/inspect_ai.model.html.md#trim_messages) to reduce the context size. Pass a [MessageFilter](../reference/inspect_ai.analysis.html.md#messagefilter) function to do custom truncation.

`approval` list\[[ApprovalPolicy](../reference/inspect_ai.approval.html.md#approvalpolicy)\] \| None  
Approval policies to use for tool calls within this agent. Temporarily replaces any active approval policies for the duration of tool execution.

### human_cli

Human CLI agent for tasks that run in a sandbox.

The Human CLI agent installs agent task tools in the default sandbox and presents the user with both task instructions and documentation for the various tools (e.g. `task submit`, `task start`, `task stop` `task instructions`, etc.). A human agent panel is displayed with instructions for logging in to the sandbox.

If the user is running in VS Code with the Inspect extension, they will also be presented with links to login to the sandbox using a VS Code Window or Terminal.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_human/agent.py#L16)

``` python
@agent
def human_cli(
    answer: bool | str = True,
    intermediate_scoring: bool = False,
    record_session: bool = True,
    user: str | None = None,
    instructions: str | None = None,
    bashrc: str | None = None,
) -> Agent
```

`answer` bool \| str  
Is an explicit answer required for this task or is it scored based on files in the container? Pass a `str` with a regex to validate that the answer matches the expected format.

`intermediate_scoring` bool  
Allow the human agent to check their score while working.

`record_session` bool  
Record all user commands and outputs in the sandbox bash session.

`user` str \| None  
User to login as. Defaults to the sandbox environment’s default user.

`instructions` str \| None  
Additional instructions beyond the default task command instructions.

`bashrc` str \| None  
Additional content to include in the .bashrc file for the human cli shell.

## Deep Agent

### deepagent

Deep agent with subagent delegation, memory, and planning.

A batteries-included agent that bundles the patterns popularized by Claude Code and Codex CLI into a single entry point. Builds on [react()](../reference/inspect_ai.agent.html.md#react) with subagent delegation via an agent tool, persistent memory, structured planning, and an opinionated system prompt.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_deepagent/deepagent.py#L49)

``` python
@agent(description="Autonomous agent for complex, multi-step tasks.")
def deepagent(
    *,
    tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    subagents: list[Subagent] | None = None,
    memory: bool = True,
    todo_write: bool = True,
    web_search: bool | Tool = False,
    background: bool | int = False,
    skills: list[str | Path | Skill] | None = None,
    model: str | Model | None = None,
    attempts: int | AgentAttempts = 1,
    submit: AgentSubmit | bool | None = None,
    on_continue: str | AgentContinue | None = None,
    retry_refusals: int | None = 3,
    compaction: CompactionStrategy | Literal["auto"] | None = "auto",
    approval: list[ApprovalPolicy] | None = None,
    instructions: str | None = None,
    prompt: str | None = None,
    max_depth: int = 1,
) -> Agent
```

`tools` Sequence\[[Tool](../reference/inspect_ai.tool.html.md#tool) \| [ToolDef](../reference/inspect_ai.tool.html.md#tooldef) \| [ToolSource](../reference/inspect_ai.tool.html.md#toolsource)\] \| None  
Additional tools beyond defaults. Flow to the top-level agent and to general() subagents.

`subagents` list\[[Subagent](../reference/inspect_ai.agent.html.md#subagent)\] \| None  
Subagent configurations. Defaults to \[research(), plan(), general()\].

`memory` bool  
Include the memory tool. False disables memory for the top-level agent and all subagents.

`todo_write` bool  
Include the todo_write planning tool.

`web_search` bool \| [Tool](../reference/inspect_ai.tool.html.md#tool)  
Include web_search tool for all agents. Pass True for default config, or a pre-configured web_search() tool instance for custom setup.

`background` bool \| int  
Background subagent dispatch. `False` (the default) disables background dispatch — the `agent` tool’s schema omits the `background` parameter and the lifecycle tools (agent_status, agent_wait, agent_cancel, agent_list) are not surfaced. `True` enables background dispatch with a cap of 8 concurrent running agents. Pass a positive integer to enable with that as the cap. `0` or negative values raise `ValueError` — use `False` to disable.

`skills` list\[str \| Path \| [Skill](../reference/inspect_ai.tool.html.md#skill)\] \| None  
Skills available to the agent.

`model` str \| [Model](../reference/inspect_ai.model.html.md#model) \| None  
Model to use.

`attempts` int \| [AgentAttempts](../reference/inspect_ai.agent.html.md#agentattempts)  
Number of submission attempts.

`submit` [AgentSubmit](../reference/inspect_ai.agent.html.md#agentsubmit) \| bool \| None  
Submit tool configuration.

`on_continue` str \| [AgentContinue](../reference/inspect_ai.agent.html.md#agentcontinue) \| None  
Continuation behavior when the model stops calling tools. Applies to the top-level agent only.

`retry_refusals` int \| None  
Number of times to retry on content filter refusals (default: 3). Propagated to subagents.

`compaction` [CompactionStrategy](../reference/inspect_ai.model.html.md#compactionstrategy) \| Literal\['auto'\] \| None  
Compaction strategy for context management. Defaults to “auto” which uses CompactionAuto (native compaction with summary fallback). Pass None to disable compaction, or a specific strategy to override.

`approval` list\[[ApprovalPolicy](../reference/inspect_ai.approval.html.md#approvalpolicy)\] \| None  
Approval policies for tool calls. Propagated to subagents.

`instructions` str \| None  
Additional instructions appended to the system prompt.

`prompt` str \| None  
Full replacement system prompt. Supports placeholders: {core_behavior}, {subagent_dispatch}, {memory_instructions}, {instructions}. When provided, replaces the default system prompt entirely.

`max_depth` int  
Maximum subagent recursion depth.

### subagent

Create a subagent configuration for use within a deep agent system.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_deepagent/subagent.py#L56)

``` python
def subagent(
    *,
    name: str,
    description: str,
    prompt: str,
    tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    extra_tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    model: str | Model | None = None,
    fork: bool = False,
    skills: list[str | Path | Skill] | None = None,
    memory: Literal["readwrite", "readonly"] | bool = False,
    limits: list[Limit] | None = None,
    compaction: CompactionStrategy | None = None,
) -> Subagent
```

`name` str  
Identifier used as the subagent_type value in agent() dispatch. Must be a valid Python identifier (letters, digits, underscores).

`description` str  
Role description shown in the agent() tool description so the model knows when to delegate to this subagent.

`prompt` str  
System prompt for the subagent’s react() loop. For built-in subagents (research, plan, general), this is assembled by the factory from its default prompt plus any user-provided instructions.

`tools` Sequence\[[Tool](../reference/inspect_ai.tool.html.md#tool) \| [ToolDef](../reference/inspect_ai.tool.html.md#tooldef) \| [ToolSource](../reference/inspect_ai.tool.html.md#toolsource)\] \| None  
Tools available to this subagent. None means “use defaults” (built-in factories set their own defaults; agent() resolves at dispatch time).

`extra_tools` Sequence\[[Tool](../reference/inspect_ai.tool.html.md#tool) \| [ToolDef](../reference/inspect_ai.tool.html.md#tooldef) \| [ToolSource](../reference/inspect_ai.tool.html.md#toolsource)\] \| None  
Additional tools merged with the subagent’s default tools. Use this to extend a built-in subagent without replacing its default tool set.

`model` str \| [Model](../reference/inspect_ai.model.html.md#model) \| None  
Model override for this subagent. None inherits the parent agent’s model.

`fork` bool  
Dispatch mode. False (default) runs the subagent with isolated context (only the summary returns). True runs with forked context (inherits the parent’s full message history). Use the same model or model family as the parent when forking to preserve the prompt cache and avoid errors from incompatible tool call formats or reasoning content.

`skills` list\[str \| Path \| [Skill](../reference/inspect_ai.tool.html.md#skill)\] \| None  
Subagent-specific skills. Merged with parent skills at dispatch time — the subagent sees both.

`memory` Literal\['readwrite', 'readonly'\] \| bool  
Memory tool access level. “readwrite” gives full memory access, “readonly” exposes only read/search operations, False disables memory entirely. Overridden to False when the parent deepagent sets memory=False.

`limits` list\[[Limit](../reference/inspect_ai.util.html.md#limit)\] \| None  
Scoped limits applied to each invocation of this subagent (e.g. token_limit, message_limit, time_limit, cost_limit).

`compaction` [CompactionStrategy](../reference/inspect_ai.model.html.md#compactionstrategy) \| None  
Compaction strategy for context management. None inherits the parent agent’s compaction strategy.

### Subagent

Configuration blueprint for a subagent within a deep agent system.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_deepagent/subagent.py#L13)

``` python
@dataclass(kw_only=True)
class Subagent
```

#### Attributes

`name` str  
Identifier used as the subagent_type value in agent() dispatch.

`description` str  
Role description shown in the agent() tool description.

`prompt` str  
System prompt for the subagent’s react() loop.

`tools` list\[[Tool](../reference/inspect_ai.tool.html.md#tool) \| [ToolDef](../reference/inspect_ai.tool.html.md#tooldef) \| [ToolSource](../reference/inspect_ai.tool.html.md#toolsource)\] \| None  
Tools available to this subagent.

`extra_tools` list\[[Tool](../reference/inspect_ai.tool.html.md#tool) \| [ToolDef](../reference/inspect_ai.tool.html.md#tooldef) \| [ToolSource](../reference/inspect_ai.tool.html.md#toolsource)\] \| None  
Additional tools merged with the subagent’s default tools.

`model` str \| [Model](../reference/inspect_ai.model.html.md#model) \| None  
Model override for this subagent.

`fork` bool  
Dispatch mode (False = isolated, True = forked). Use same model or model family as parent when forking to preserve the prompt cache and avoid errors from incompatible tool call formats or reasoning content in the inherited message history.

`skills` list\[str \| Path \| [Skill](../reference/inspect_ai.tool.html.md#skill)\] \| None  
Subagent-specific skills. Merged with parent skills at dispatch time — the subagent sees both parent and its own skills.

`memory` Literal\['readwrite', 'readonly'\] \| bool  
Memory tool access level.

`limits` list\[[Limit](../reference/inspect_ai.util.html.md#limit)\] \| None  
Scoped limits applied to each invocation of this subagent.

`compaction` [CompactionStrategy](../reference/inspect_ai.model.html.md#compactionstrategy) \| None  
Compaction strategy for context management. None inherits the parent agent’s compaction strategy.

### research

Create a research subagent for read-only information gathering.

The research subagent is configured with read-only tools by default and is intended for tasks that involve gathering and synthesizing information without modifying state.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_deepagent/research.py#L35)

``` python
def research(
    *,
    tools: Sequence[Tool | ToolDef | ToolSource] | Literal["default"] = "default",
    extra_tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    instructions: str | None = None,
    skills: list[str | Path | Skill] | None = None,
    memory: Literal["readwrite", "readonly"] | bool = False,
    limits: list[Limit] | None = None,
    model: str | Model | None = None,
    fork: bool = False,
) -> Subagent
```

`tools` Sequence\[[Tool](../reference/inspect_ai.tool.html.md#tool) \| [ToolDef](../reference/inspect_ai.tool.html.md#tooldef) \| [ToolSource](../reference/inspect_ai.tool.html.md#toolsource)\] \| Literal\['default'\]  
Tools for this subagent. “default” provides read-only sandbox tools (read_file, list_files, grep) when a sandbox is available. Pass a list to replace defaults entirely.

`extra_tools` Sequence\[[Tool](../reference/inspect_ai.tool.html.md#tool) \| [ToolDef](../reference/inspect_ai.tool.html.md#tooldef) \| [ToolSource](../reference/inspect_ai.tool.html.md#toolsource)\] \| None  
Additional tools added on top of the default or custom tools.

`instructions` str \| None  
Additional instructions appended to the default research prompt.

`skills` list\[str \| Path \| [Skill](../reference/inspect_ai.tool.html.md#skill)\] \| None  
Subagent-specific skills (merged with parent skills).

`memory` Literal\['readwrite', 'readonly'\] \| bool  
Memory access level (“readonly”, “readwrite”, or False).

`limits` list\[[Limit](../reference/inspect_ai.util.html.md#limit)\] \| None  
Scoped limits for each invocation.

`model` str \| [Model](../reference/inspect_ai.model.html.md#model) \| None  
Model override (None inherits from parent).

`fork` bool  
If True, inherits parent conversation context. Use same model or model family as parent to preserve the prompt cache and avoid errors from incompatible tool call formats or reasoning content.

### plan

Create a plan subagent for structured planning.

The plan subagent is configured with read-only tools by default and is intended for analyzing tasks and producing structured implementation plans without executing changes.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_deepagent/plan.py#L35)

``` python
def plan(
    *,
    tools: Sequence[Tool | ToolDef | ToolSource] | Literal["default"] = "default",
    extra_tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    instructions: str | None = None,
    skills: list[str | Path | Skill] | None = None,
    memory: Literal["readwrite", "readonly"] | bool = False,
    limits: list[Limit] | None = None,
    model: str | Model | None = None,
    fork: bool = False,
) -> Subagent
```

`tools` Sequence\[[Tool](../reference/inspect_ai.tool.html.md#tool) \| [ToolDef](../reference/inspect_ai.tool.html.md#tooldef) \| [ToolSource](../reference/inspect_ai.tool.html.md#toolsource)\] \| Literal\['default'\]  
Tools for this subagent. “default” provides read-only sandbox tools (read_file, list_files, grep) when a sandbox is available. Pass a list to replace defaults entirely.

`extra_tools` Sequence\[[Tool](../reference/inspect_ai.tool.html.md#tool) \| [ToolDef](../reference/inspect_ai.tool.html.md#tooldef) \| [ToolSource](../reference/inspect_ai.tool.html.md#toolsource)\] \| None  
Additional tools added on top of the default or custom tools.

`instructions` str \| None  
Additional instructions appended to the default plan prompt.

`skills` list\[str \| Path \| [Skill](../reference/inspect_ai.tool.html.md#skill)\] \| None  
Subagent-specific skills (merged with parent skills).

`memory` Literal\['readwrite', 'readonly'\] \| bool  
Memory access level (“readonly”, “readwrite”, or False).

`limits` list\[[Limit](../reference/inspect_ai.util.html.md#limit)\] \| None  
Scoped limits for each invocation.

`model` str \| [Model](../reference/inspect_ai.model.html.md#model) \| None  
Model override (None inherits from parent).

`fork` bool  
If True, inherits parent conversation context. Use same model or model family as parent to preserve the prompt cache and avoid errors from incompatible tool call formats or reasoning content.

### general

Create a general-purpose subagent with full tool access.

The general subagent inherits the parent agent’s tools (including skills) by default and has read-write memory access. It is intended for tasks that require full capabilities in an isolated context.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_deepagent/general.py#L32)

``` python
def general(
    *,
    tools: Sequence[Tool | ToolDef | ToolSource] | Literal["default"] = "default",
    extra_tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    instructions: str | None = None,
    skills: list[str | Path | Skill] | None = None,
    memory: Literal["readwrite", "readonly"] | bool = False,
    limits: list[Limit] | None = None,
    model: str | Model | None = None,
    fork: bool = False,
) -> Subagent
```

`tools` Sequence\[[Tool](../reference/inspect_ai.tool.html.md#tool) \| [ToolDef](../reference/inspect_ai.tool.html.md#tooldef) \| [ToolSource](../reference/inspect_ai.tool.html.md#toolsource)\] \| Literal\['default'\]  
Tools for this subagent. “default” inherits the parent agent’s tools. Pass a list to replace defaults entirely.

`extra_tools` Sequence\[[Tool](../reference/inspect_ai.tool.html.md#tool) \| [ToolDef](../reference/inspect_ai.tool.html.md#tooldef) \| [ToolSource](../reference/inspect_ai.tool.html.md#toolsource)\] \| None  
Additional tools added on top of the default or custom tools.

`instructions` str \| None  
Additional instructions appended to the default general prompt.

`skills` list\[str \| Path \| [Skill](../reference/inspect_ai.tool.html.md#skill)\] \| None  
Subagent-specific skills (merged with parent skills).

`memory` Literal\['readwrite', 'readonly'\] \| bool  
Memory access level (“readwrite”, “readonly”, or False).

`limits` list\[[Limit](../reference/inspect_ai.util.html.md#limit)\] \| None  
Scoped limits for each invocation.

`model` str \| [Model](../reference/inspect_ai.model.html.md#model) \| None  
Model override (None inherits from parent).

`fork` bool  
If True, inherits parent conversation context. Use same model or model family as parent to preserve the prompt cache and avoid errors from incompatible tool call formats or reasoning content.

## Execution

### handoff

Create a tool that enables models to handoff to agents.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_handoff.py#L19)

``` python
def handoff(
    agent: Agent,
    description: str | None = None,
    input_filter: MessageFilter | None = None,
    output_filter: MessageFilter | None = content_only,
    tool_name: str | None = None,
    limits: list[Limit] = [],
    **agent_kwargs: Any,
) -> Tool
```

`agent` [Agent](../reference/inspect_ai.agent.html.md#agent)  
Agent to hand off to.

`description` str \| None  
Handoff tool description (defaults to agent description)

`input_filter` [MessageFilter](../reference/inspect_ai.analysis.html.md#messagefilter) \| None  
Filter to modify the message history before calling the tool. Use the built-in `remove_tools` filter to remove all tool calls. Alternatively specify another [MessageFilter](../reference/inspect_ai.analysis.html.md#messagefilter) function or list of [MessageFilter](../reference/inspect_ai.analysis.html.md#messagefilter) functions.

`output_filter` [MessageFilter](../reference/inspect_ai.analysis.html.md#messagefilter) \| None  
Filter to modify the message history after calling the tool. Defaults to [content_only()](../reference/inspect_ai.agent.html.md#content_only), which produces a history that should be safe to read by other models (tool calls are converted to text, and both system messages and reasoning blocks are removed). Alternatively specify another [MessageFilter](../reference/inspect_ai.analysis.html.md#messagefilter) function or list of [MessageFilter](../reference/inspect_ai.analysis.html.md#messagefilter) functions.

`tool_name` str \| None  
Alternate tool name (defaults to `transfer_to_{agent_name}`)

`limits` list\[[Limit](../reference/inspect_ai.util.html.md#limit)\]  
List of limits to apply to the agent. Limits are scoped to each handoff to the agent. Should a limit be exceeded, the agent stops and a user message is appended explaining that a limit was exceeded.

`**agent_kwargs` Any  
Arguments to curry to [Agent](../reference/inspect_ai.agent.html.md#agent) function (arguments provided here will not be presented to the model as part of the tool interface).

### run

Run an agent.

The input messages(s) will be copied prior to running so are not modified in place.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_run.py#L35)

``` python
async def run(
    agent: Agent,
    input: str | list[ChatMessage] | AgentState,
    limits: list[Limit] | None = None,
    *,
    name: str | None = None,
    span_id: str | None = None,
    **agent_kwargs: Any,
) -> AgentState | tuple[AgentState, LimitExceededError | None]
```

`agent` [Agent](../reference/inspect_ai.agent.html.md#agent)  
Agent to run.

`input` str \| list\[[ChatMessage](../reference/inspect_ai.model.html.md#chatmessage)\] \| [AgentState](../reference/inspect_ai.agent.html.md#agentstate)  
Agent input (string, list of messages, or an [AgentState](../reference/inspect_ai.agent.html.md#agentstate)).

`limits` list\[[Limit](../reference/inspect_ai.util.html.md#limit)\] \| None  
List of limits to apply to the agent. Should one of these limits be exceeded, the [LimitExceededError](../reference/inspect_ai.util.html.md#limitexceedederror) is caught and returned.

`name` str \| None  
Optional display name for the transcript entry. If not provided, the agent’s name as defined in the registry will be used.

`span_id` str \| None  
Optional span ID for the agent span. If not provided, one is generated automatically.

`**agent_kwargs` Any  
Additional arguments to pass to agent.

### as_tool

Convert an agent to a tool.

By default the model will see all of the agent’s arguments as tool arguments (save for `state` which is converted to an `input` arguments of type `str`). Provide optional `agent_kwargs` to mask out agent parameters with default values (these parameters will not be presented to the model as part of the tool interface)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_as_tool.py#L22)

``` python
@tool
def as_tool(
    agent: Agent,
    description: str | None = None,
    limits: list[Limit] = [],
    **agent_kwargs: Any,
) -> Tool
```

`agent` [Agent](../reference/inspect_ai.agent.html.md#agent)  
Agent to convert.

`description` str \| None  
Tool description (defaults to agent description)

`limits` list\[[Limit](../reference/inspect_ai.util.html.md#limit)\]  
List of limits to apply to the agent. Should a limit be exceeded, the tool call ends and returns an error explaining that a limit was exceeded.

`**agent_kwargs` Any  
Arguments to curry to Agent function (arguments provided here will not be presented to the model as part of the tool interface).

### as_solver

Convert an agent to a solver.

Note that agents used as solvers will only receive their first parameter (`state`). Any other parameters must provide appropriate defaults or be explicitly specified in `agent_kwargs`

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_as_solver.py#L24)

``` python
def as_solver(agent: Agent, limits: list[Limit] = [], **agent_kwargs: Any) -> Solver
```

`agent` [Agent](../reference/inspect_ai.agent.html.md#agent)  
Agent to convert.

`limits` list\[[Limit](../reference/inspect_ai.util.html.md#limit)\]  
List of limits to apply to the agent. Should a limit be exceeded, the Sample ends and proceeds to scoring.

`**agent_kwargs` Any  
Arguments to curry to Agent function (required if the agent has parameters without default values).

## Bridging

### agent_bridge

Agent bridge.

Provide Inspect integration for 3rd party agents that use the the OpenAI Completions API, OpenAI Responses API, or Anthropic API. The bridge patches the OpenAI and Anthropic client libraries to redirect any model named “inspect” (or prefaced with “inspect/” for non-default models) into the Inspect model API.

See the [Agent Bridge](https://inspect.aisi.org.uk/agent-bridge.html) documentation for additional details.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_bridge/bridge.py#L84)

``` python
@contextlib.asynccontextmanager
async def agent_bridge(
    state: AgentState | None = None,
    *,
    filter: GenerateFilter | None = None,
    retry_refusals: int | None = None,
    compaction: CompactionStrategy | None = None,
    web_search: WebSearchProviders | None = None,
    code_execution: CodeExecutionProviders | None = None,
    model_event_sink: ModelEventSink | None = None,
    forward_generation_config: bool = False,
) -> AsyncGenerator[AgentBridge, None]
```

`state` [AgentState](../reference/inspect_ai.agent.html.md#agentstate) \| None  
Initial state for agent bridge. Used as a basis for yielding an updated state based on traffic over the bridge.

`filter` [GenerateFilter](../reference/inspect_ai.model.html.md#generatefilter) \| None  
Filter for bridge model generation.

`retry_refusals` int \| None  
Should refusals be retried? (pass number of times to retry)

`compaction` [CompactionStrategy](../reference/inspect_ai.model.html.md#compactionstrategy) \| None  
Compact the conversation when it it is close to overflowing the model’s context window. See [Compaction](https://inspect.aisi.org.uk/compaction.html) for details on compaction strategies.

`web_search` [WebSearchProviders](../reference/inspect_ai.tool.html.md#websearchproviders) \| None  
Configuration for mapping model internal web_search tools to Inspect. By default, will map to the internal provider of the target model (supported for OpenAI, Anthropic, Gemini, Grok, and Perplexity). Pass an alternate configuration to use to use an external provider like Tavili or Exa for models that don’t support internal search.

`code_execution` [CodeExecutionProviders](../reference/inspect_ai.tool.html.md#codeexecutionproviders) \| None  
Configuration for mapping model internal code_execution tools to Inspect. By default, will map to the internal provider of the target model (supported for OpenAI, Anthropic, Google, and Grok). If the provider does not support native code execution then the bash() tool will be provided (note that this requires a sandbox by declared for the task).

`model_event_sink` ModelEventSink \| None  
Optional sink that takes ownership of [ModelEvent](../reference/inspect_ai.event.html.md#modelevent) emission for calls routed through the bridge. When set, the bridge installs it around `model.generate()` so the sink decides when and under which span each event is emitted to the transcript.

`forward_generation_config` bool  
Forward client generation parameters (e.g. `max_tokens`, `temperature`, reasoning effort) to the model. Defaults to `False`, in which case those parameters are dropped and the resolved Inspect model config and provider defaults govern generation (structural parameters like the system prompt, tools, and response format are always forwarded). Set `True` for faithful-proxy behavior where the client’s generation parameters are authoritative.

### AgentBridge

Agent bridge.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_bridge/types.py#L23)

``` python
class AgentBridge
```

#### Attributes

`state` [AgentState](../reference/inspect_ai.agent.html.md#agentstate)  
State updated from messages traveling over the bridge.

`filter` [GenerateFilter](../reference/inspect_ai.model.html.md#generatefilter) \| None  
Filter for bridge model generation.

A filter may substitute for the default model generation by returning a ModelOutput or return None to allow default processing to continue.

`model` str \| None  
Fallback model for requests that don’t use `inspect` or `inspect/` prefixed names. `None` means no fallback (the request model name is used as-is).

`model_aliases` dict\[str, str \| [Model](../reference/inspect_ai.model.html.md#model)\]  
Map of model name aliases. When a request uses a name that appears here, the corresponding value (a [Model](../reference/inspect_ai.model.html.md#model) instance or model spec string) is used instead. Checked before the fallback `model`.

`model_event_sink` ModelEventSink \| None  
Optional sink that takes ownership of [ModelEvent](../reference/inspect_ai.event.html.md#modelevent) emission for calls routed through the bridge. When set, the bridge installs it around `model.generate()`; `_record_model_interaction` then dispatches pending / complete events to the sink instead of emitting them to the transcript. Use this to attribute bridge model events to externally-managed agent spans (e.g. spans driven by a side-channel event stream).

`forward_generation_config` bool  
Whether to forward client generation parameters to the model.

When `False` (the default), generation-tuning parameters from the incoming request (e.g. `max_tokens`, `temperature`, `top_p`/`top_k`, reasoning effort / thinking budget, penalties, `n`, logprobs) are dropped; the resolved Inspect model config and provider defaults govern generation. This prevents a scaffold from imposing parameters it computed for a different model than the one actually serving the request. Structural parameters (system prompt, tools, tool choice, response format, stop sequences) are always forwarded. Set `True` to forward the client’s generation parameters (faithful-proxy behavior).

#### Methods

compaction  
Compaction function for bridge.

Note: This will always return the same compaction function for a given instance of the bridge.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_bridge/types.py#L95)

``` python
def compaction(
    self, tools: Sequence[ToolInfo | Tool], model: Model
) -> Compact | None
```

`tools` Sequence\[[ToolInfo](../reference/inspect_ai.tool.html.md#toolinfo) \| [Tool](../reference/inspect_ai.tool.html.md#tool)\]  
Tool definitions (included in token count as they consume context).

`model` [Model](../reference/inspect_ai.model.html.md#model)  
Target model for compacted input.

note_operator_message  
Record that an operator-injected user message is entering the agent.

Called by a bridged scaffold (e.g. inspect_swe, issue \#66) right after it drains an operator message from the agent channel and forwards it to its underlying CLI. A bridged scaffold round-trips the message through its own conversation store, so it re-enters `bridge_generate` as a plain [ChatMessageUser](../reference/inspect_ai.model.html.md#chatmessageuser) with `source=None` (the provenance the ACP transport stamped at submit time is lost). The bridge restores `source="operator"` inside `bridge_generate` so it renders distinctly in the ACP TUI and persists into the eval log (model events + final messages).

Recognition is positional — the operator turn is the latest user message in the next request (queued sends coalesce into one) — so only the pending count is used here; the `message` argument is accepted for caller clarity.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_bridge/types.py#L116)

``` python
def note_operator_message(self, message: ChatMessageUser) -> None
```

`message` [ChatMessageUser](../reference/inspect_ai.model.html.md#chatmessageuser)  

### sandbox_agent_bridge

Sandbox agent bridge.

Provide Inspect integration for agents running inside sandboxes. Runs a proxy server in the container that provides REST endpoints for the OpenAI Completions API, OpenAI Responses API, Anthropic API, and Google API. This proxy server runs on port 13131 and routes requests to the current Inspect model provider.

You should set `OPENAI_BASE_URL=http://localhost:13131/v1`, `ANTHROPIC_BASE_URL=http://localhost:13131`, or `GOOGLE_GEMINI_BASE_URL=http://localhost:13131` when executing the agent within the container and ensure that your agent targets the model name “inspect” when calling OpenAI, Anthropic, or Google. Use “inspect/” to target other Inspect model providers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_bridge/sandbox/bridge.py#L36)

``` python
@contextlib.asynccontextmanager
async def sandbox_agent_bridge(
    state: AgentState | None = None,
    *,
    model: str | None = None,
    model_aliases: dict[str, str | Model] | None = None,
    filter: GenerateFilter | None = None,
    retry_refusals: int | None = None,
    compaction: CompactionStrategy | None = None,
    sandbox: str | None = None,
    port: int = 13131,
    web_search: WebSearchProviders | None = None,
    code_execution: CodeExecutionProviders | None = None,
    bridged_tools: Sequence[BridgedToolsSpec] | None = None,
    model_event_sink: ModelEventSink | None = None,
    forward_generation_config: bool = False,
) -> AsyncIterator[SandboxAgentBridge]
```

`state` [AgentState](../reference/inspect_ai.agent.html.md#agentstate) \| None  
Initial state for agent bridge. Used as a basis for yielding an updated state based on traffic over the bridge.

`model` str \| None  
Fallback model for requests that don’t use “inspect” or an “inspect/” prefixed model (defaults to “inspect”, can also specify e.g. “inspect/openai/gpt-4o” to force another specific model).

`model_aliases` dict\[str, str \| [Model](../reference/inspect_ai.model.html.md#model)\] \| None  
Map of model name aliases. When a request uses a name that appears here, the corresponding value (a [Model](../reference/inspect_ai.model.html.md#model) instance or model spec string) is used instead. Checked before the fallback `model`.

`filter` [GenerateFilter](../reference/inspect_ai.model.html.md#generatefilter) \| None  
Filter for bridge model generation.

`retry_refusals` int \| None  
Should refusals be retried? (pass number of times to retry)

`compaction` [CompactionStrategy](../reference/inspect_ai.model.html.md#compactionstrategy) \| None  
Compact the conversation when it it is close to overflowing the model’s context window. See [Compaction](https://inspect.aisi.org.uk/compaction.html) for details on compaction strategies.

`sandbox` str \| None  
Sandbox to run model proxy server within.

`port` int  
Port to run proxy server on.

`web_search` [WebSearchProviders](../reference/inspect_ai.tool.html.md#websearchproviders) \| None  
Configuration for mapping model internal web_search tools to Inspect. By default, will map to the internal provider of the target model (supported for OpenAI, Anthropic, Gemini, Grok, and Perplexity). Pass an alternate configuration to use to use an external provider like Tavily or Exa for models that don’t support internal search.

`code_execution` [CodeExecutionProviders](../reference/inspect_ai.tool.html.md#codeexecutionproviders) \| None  
Configuration for mapping model internal code_execution tools to Inspect. By default, will map to the internal provider of the target model (supported for OpenAI, Anthropic, Google, and Grok). If the provider does not support native code execution then the bash() tool will be provided (note that this requires a sandbox by declared for the task).

`bridged_tools` Sequence\[[BridgedToolsSpec](../reference/inspect_ai.agent.html.md#bridgedtoolsspec)\] \| None  
Host-side Inspect tools to expose to the sandboxed agent via MCP protocol. Each BridgedToolsSpec creates an MCP server that makes the specified tools available to the agent. The resolved MCPServerConfigStdio objects to pass to CLI agents are available via bridge.mcp_server_configs.

`model_event_sink` ModelEventSink \| None  
Optional sink that takes ownership of [ModelEvent](../reference/inspect_ai.event.html.md#modelevent) emission for calls routed through the bridge. When set, the bridge installs it around `model.generate()` so the sink decides when and under which span each event is emitted to the transcript.

`forward_generation_config` bool  
Forward client generation parameters (e.g. `max_tokens`, `temperature`, reasoning effort) to the model. Defaults to `False`, in which case those parameters are dropped and the resolved Inspect model config and provider defaults govern generation (structural parameters like the system prompt, tools, and response format are always forwarded). Set `True` for faithful-proxy behavior where the client’s generation parameters are authoritative.

### SandboxAgentBridge

Sandbox agent bridge.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_bridge/sandbox/types.py#L9)

``` python
class SandboxAgentBridge(AgentBridge)
```

#### Attributes

`state` [AgentState](../reference/inspect_ai.agent.html.md#agentstate)  
State updated from messages traveling over the bridge.

`filter` [GenerateFilter](../reference/inspect_ai.model.html.md#generatefilter) \| None  
Filter for bridge model generation.

A filter may substitute for the default model generation by returning a ModelOutput or return None to allow default processing to continue.

`model` str \| None  
Fallback model for requests that don’t use `inspect` or `inspect/` prefixed names. `None` means no fallback (the request model name is used as-is).

`model_aliases` dict\[str, str \| [Model](../reference/inspect_ai.model.html.md#model)\]  
Map of model name aliases. When a request uses a name that appears here, the corresponding value (a [Model](../reference/inspect_ai.model.html.md#model) instance or model spec string) is used instead. Checked before the fallback `model`.

`model_event_sink` ModelEventSink \| None  
Optional sink that takes ownership of [ModelEvent](../reference/inspect_ai.event.html.md#modelevent) emission for calls routed through the bridge. When set, the bridge installs it around `model.generate()`; `_record_model_interaction` then dispatches pending / complete events to the sink instead of emitting them to the transcript. Use this to attribute bridge model events to externally-managed agent spans (e.g. spans driven by a side-channel event stream).

`forward_generation_config` bool  
Whether to forward client generation parameters to the model.

When `False` (the default), generation-tuning parameters from the incoming request (e.g. `max_tokens`, `temperature`, `top_p`/`top_k`, reasoning effort / thinking budget, penalties, `n`, logprobs) are dropped; the resolved Inspect model config and provider defaults govern generation. This prevents a scaffold from imposing parameters it computed for a different model than the one actually serving the request. Structural parameters (system prompt, tools, tool choice, response format, stop sequences) are always forwarded. Set `True` to forward the client’s generation parameters (faithful-proxy behavior).

`port` int  
Model proxy server port.

`mcp_server_configs` list\[MCPServerConfigHTTP\]  
MCP server configs for bridged tools (resolved from bridged_tools parameter).

`bridged_tools` dict\[str, dict\[str, [Tool](../reference/inspect_ai.tool.html.md#tool)\]\]  
Registry of bridged tools by server name, then tool name.

#### Methods

compaction  
Compaction function for bridge.

Note: This will always return the same compaction function for a given instance of the bridge.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_bridge/types.py#L95)

``` python
def compaction(
    self, tools: Sequence[ToolInfo | Tool], model: Model
) -> Compact | None
```

`tools` Sequence\[[ToolInfo](../reference/inspect_ai.tool.html.md#toolinfo) \| [Tool](../reference/inspect_ai.tool.html.md#tool)\]  
Tool definitions (included in token count as they consume context).

`model` [Model](../reference/inspect_ai.model.html.md#model)  
Target model for compacted input.

note_operator_message  
Record that an operator-injected user message is entering the agent.

Called by a bridged scaffold (e.g. inspect_swe, issue \#66) right after it drains an operator message from the agent channel and forwards it to its underlying CLI. A bridged scaffold round-trips the message through its own conversation store, so it re-enters `bridge_generate` as a plain [ChatMessageUser](../reference/inspect_ai.model.html.md#chatmessageuser) with `source=None` (the provenance the ACP transport stamped at submit time is lost). The bridge restores `source="operator"` inside `bridge_generate` so it renders distinctly in the ACP TUI and persists into the eval log (model events + final messages).

Recognition is positional — the operator turn is the latest user message in the next request (queued sends coalesce into one) — so only the pending count is used here; the `message` argument is accepted for caller clarity.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_bridge/types.py#L116)

``` python
def note_operator_message(self, message: ChatMessageUser) -> None
```

`message` [ChatMessageUser](../reference/inspect_ai.model.html.md#chatmessageuser)  

### BridgedToolsSpec

Specification for host-side tools to expose via MCP bridge.

This allows Inspect tools defined on the host to be exposed to agents running inside a sandbox via MCP.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/tool/_mcp/_tools_bridge/bridge.py#L9)

``` python
@dataclass
class BridgedToolsSpec
```

#### Attributes

`name` str  
Name of the MCP server (visible to agent as mcp\_*{name}*\*).

`tools` Sequence\[[Tool](../reference/inspect_ai.tool.html.md#tool)\]  
Inspect Tool objects to expose via MCP.

## Filters

### content_only

Remove (or convert) message history to pure content.

This is the default filter for agent handoffs and is intended to present a history that doesn’t confound the parent model with tools it doesn’t have, reasoning traces it didn’t create, etc.

- Removes system messages
- Removes reasoning traces
- Removes `internal` attribute on content
- Converts tool calls to user messages
- Converts server tool calls to text

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_filter.py#L22)

``` python
async def content_only(messages: list[ChatMessage]) -> list[ChatMessage]
```

`messages` list\[[ChatMessage](../reference/inspect_ai.model.html.md#chatmessage)\]  
Messages to filter.

### last_message

Remove all but the last message.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_filter.py#L119)

``` python
async def last_message(messages: list[ChatMessage]) -> list[ChatMessage]
```

`messages` list\[[ChatMessage](../reference/inspect_ai.model.html.md#chatmessage)\]  
Target messages.

### remove_tools

Remove tool calls from messages.

Removes all instances of [ChatMessageTool](../reference/inspect_ai.model.html.md#chatmessagetool) as well as the `tool_calls` field from [ChatMessageAssistant](../reference/inspect_ai.model.html.md#chatmessageassistant).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_filter.py#L96)

``` python
async def remove_tools(messages: list[ChatMessage]) -> list[ChatMessage]
```

`messages` list\[[ChatMessage](../reference/inspect_ai.model.html.md#chatmessage)\]  
Messages to remove tool calls from.

### MessageFilter

Filter messages sent to or received from agent handoffs.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_filter.py#L18)

``` python
MessageFilter = Callable[[list[ChatMessage]], Awaitable[list[ChatMessage]]]
```

## Channel

### agent_channel

Open a fresh :class:[AgentChannel](../reference/inspect_ai.agent.html.md#agentchannel) for the enclosing scope.

Use as an async context manager::

    async with agent_channel() as ch:
        ...

Inside the `with` block, :func:`current_agent_channel` returns `ch`. The channel is uniform at every nesting level: nested [agent_channel()](../reference/inspect_ai.agent.html.md#agent_channel) opens (e.g. a sub-agent invoked via handoff) each get their own working channel.

Opening also offers the channel’s :class:`AgentRef` to the active sample’s ACP session (if any) via `maybe_bind` — first-binder-wins, so a nested sub-agent’s open is silently rejected and the outer react remains the producer target. `unbind` on exit clears the slot iff this channel was the binder, letting a successor react in the same sample rebind. The channel itself never knows whether it is nested; the bind-once semantics live on the ACP session.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_channel/__init__.py#L95)

``` python
@contextlib.asynccontextmanager
async def agent_channel() -> AsyncIterator[AgentChannel]
```

### AgentChannel

Per-execution intervention channel.

There are two ways to consume a channel from an agent loop. Most custom agents should use the **high-level facade** — it’s three method calls per turn and matches the documented pattern in `docs/intervention.qmd`::

    async with agent_channel() as ch:
        while True:
            state.messages.extend(await ch.before_turn(state.messages))
            try:
                with ch.turn_scope():
                    # generate + tool calls...
            except AgentInterrupted:
                state.messages.extend(await ch.after_cancel(state.messages))
                continue

- :meth:`before_turn` — drain queued operator messages at the start of a turn (blocks for an initial one if state has none).
- :meth:`turn_scope` — cancellable region for model generation + tool execution; an operator interrupt raises :exc:[AgentInterrupted](../reference/inspect_ai.agent.html.md#agentinterrupted).
- :meth:`after_cancel` — recovery messages (repair + follow-up) after :exc:[AgentInterrupted](../reference/inspect_ai.agent.html.md#agentinterrupted) was caught.

The **low-level primitives** — :meth:`_post`, :meth:`_interrupt`, :meth:`_drain`, :meth:`_recv`, :meth:`_repair`, :meth:`_ref` — are underscored to mark them as internal. They are exposed for producers (ACP transport, tests, future operator consoles) and for the rare custom agent that needs to compose its own intervention semantics. Reach for them only when the facade doesn’t fit; in nearly every agent loop it does.

Owns: an unbounded item queue, an anyio Event for blocking on arrivals, and the currently-bound :class:`anyio.CancelScope` (if any). Source-agnostic — producers and consumers never interact with each other directly; the channel mediates.

Instances are not thread-safe and not designed for use outside an enclosing agent execution (use :func:`agent_channel` / :func:`current_agent_channel` from the package root to acquire one).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_channel/channel.py#L70)

``` python
class AgentChannel
```

#### Attributes

`is_live` bool  
True if any externally-reachable producer is attached.

Inverts the “inert by default” state documented at the top of this module. Use to gate interactive plumbing (e.g. switching an agent CLI into streaming-stdin mode) on whether an external client can actually reach this agent. False on inert channels, on channels with only in-proc bookkeeping producers, and on samples where the ACP server is not running.

#### Methods

turn_scope  
Demarcate an interruptible region.

The agent enters this around foreground work it is willing to have preempted. An :meth:`_interrupt` call cancels the underlying :class:`anyio.CancelScope`; on exit the channel raises :exc:[AgentInterrupted](../reference/inspect_ai.agent.html.md#agentinterrupted) inside the block — but only when the cancel originated from this channel. A sample-level :class:`asyncio.CancelledError` (limit, eval shutdown) passes through unchanged.

Exactly one scope per region is supported; nested scopes on the same channel are not. The scope must enclose tool execution as well as `model.generate()` so a blocking tool call can be cancelled by a producer-initiated interrupt mid-call.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_channel/channel.py#L188)

``` python
@contextlib.contextmanager
def turn_scope(self) -> Iterator[None]
```

subscribe_drained  
Register a callback fired after a non-empty :meth:`_drain`.

The callback receives the list of items that were drained. It runs synchronously in the consumer’s task; exceptions are swallowed so a broken observer cannot stall the agent loop.

Returns an idempotent unsubscribe callable — calling it more than once is safe and has no further effect.

Producer use case: the ACP transport subscribes during :meth:`AcpTransport.maybe_bind` to observe when its queued :class:`UserMessage` items reach the consumer, so it can resolve its `interrupt_pending` flag without the channel needing to know about ACP.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_channel/channel.py#L242)

``` python
def subscribe_drained(
    self, callback: Callable[[list[ChannelItem]], None]
) -> Callable[[], None]
```

`callback` Callable\[\[list\[ChannelItem\]\], None\]  

mark_live  
Producer marker — call iff this producer has external reach.

Distinct from :meth:`subscribe_drained`: every producer subscribes to drains for internal bookkeeping (e.g. clearing an `interrupt_pending` flag), but only producers that represent a reachable external surface — e.g. an ACP socket server actually accepting client connections — call this. Consumers consult :attr:`is_live` to decide whether to enable interactive plumbing (e.g. open an agent CLI in streaming-stdin mode); they shouldn’t pay that cost just because an in-proc bookkeeping producer is attached.

Returns an idempotent clear callable. The producer holds it for the lifetime of its external reach and calls it on unbind / teardown / loss of reach. Multiple producers may mark live concurrently; `is_live` stays True until every clear runs.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_channel/channel.py#L270)

``` python
def mark_live(self) -> Callable[[], None]
```

before_turn  
Pending operator-supplied user messages for the start of a turn.

Drains queued :class:`UserMessage` items, coalesces consecutive operator sends into one, and returns the resulting list ready to extend onto `state.messages`.

Blocks via :meth:`_recv` iff BOTH (a) the drain produced no :class:`UserMessage` AND (b) `messages` contains no :class:[ChatMessageUser](../reference/inspect_ai.model.html.md#chatmessageuser) already. This is the “wait for an initial user message” gate — on every subsequent turn `messages` already has the prior user input so the call returns immediately.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_channel/channel.py#L367)

``` python
async def before_turn(
    self, messages: Sequence[ChatMessage]
) -> list[ChatMessageUser]
```

`messages` Sequence\[[ChatMessage](../reference/inspect_ai.model.html.md#chatmessage)\]  

after_cancel  
Recovery messages after :exc:[AgentInterrupted](../reference/inspect_ai.agent.html.md#agentinterrupted) was caught.

Returns, in order:

- Repair messages — synthetic :class:[ChatMessageTool](../reference/inspect_ai.model.html.md#chatmessagetool) results for any `tool_calls` the last assistant message left in flight, so the conversation is well-formed for the next generation.
- Pending user messages — coalesced producer follow-up posted alongside the interrupt. Always blocks for one if none arrived (preserves the stop-and-redirect semantics: after a cancel the agent waits for the operator’s follow-up before resuming, regardless of how many user messages already exist in the conversation history).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_channel/channel.py#L390)

``` python
async def after_cancel(self, messages: Sequence[ChatMessage]) -> list[ChatMessage]
```

`messages` Sequence\[[ChatMessage](../reference/inspect_ai.model.html.md#chatmessage)\]  

### AgentInterrupted

Raised inside :meth:`AgentChannel.turn_scope` when cancelled by an interrupt.

Source-agnostic: any producer’s interrupt (operator over ACP today, future subagent-supervisor kill, etc.) raises the same exception inside the consuming agent’s turn scope. The consumer catches, drains queued items, and decides how to resume.

Distinct from :class:`asyncio.CancelledError` (which is reserved for sample-level hard cancels propagating from the enclosing task group — limit exceeded, eval shutdown).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_channel/exceptions.py#L6)

``` python
class AgentInterrupted(Exception)
```

## Protocol

### Agent

Agents perform tasks and participate in conversations.

Agents are similar to tools however they are participants in conversation history and can optionally append messages and model output to the current conversation state.

You can give the model a tool that enables handoff to your agent using the [handoff()](../reference/inspect_ai.agent.html.md#handoff) function.

You can create a simple tool (that receives a string as input) from an agent using [as_tool()](../reference/inspect_ai.agent.html.md#as_tool).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_agent.py#L94)

``` python
class Agent(Protocol):
    async def __call__(
        self,
        state: AgentState,
        *args: Any,
        **kwargs: Any,
    ) -> AgentState
```

`state` [AgentState](../reference/inspect_ai.agent.html.md#agentstate)  
Agent state (conversation history and last model output)

`*args` Any  
Arguments for the agent.

`**kwargs` Any  
Keyword arguments for the agent.

### AgentState

Agent state.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_agent.py#L35)

``` python
class AgentState
```

#### Attributes

`messages` list\[[ChatMessage](../reference/inspect_ai.model.html.md#chatmessage)\]  
Conversation history.

`output` [ModelOutput](../reference/inspect_ai.model.html.md#modeloutput)  
Model output.

### agent

Decorator for registering agents.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_agent.py#L142)

``` python
def agent(
    func: Callable[P, Agent] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Callable[P, Agent] | Callable[[Callable[P, Agent]], Callable[P, Agent]]
```

`func` Callable\[P, [Agent](../reference/inspect_ai.agent.html.md#agent)\] \| None  
Agent function

`name` str \| None  
Optional name for agent. If the decorator has no name argument then the name of the agent creation function will be used as the name of the agent.

`description` str \| None  
Description for the agent when used as an ordinary tool or handoff tool.

### agent_with

Agent with modifications to name and/or description

This function modifies the passed agent in place and returns it. If you want to create multiple variations of a single agent using [agent_with()](../reference/inspect_ai.agent.html.md#agent_with) you should create the underlying agent multiple times.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_agent.py#L234)

``` python
def agent_with(
    agent: Agent,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Agent
```

`agent` [Agent](../reference/inspect_ai.agent.html.md#agent)  
Agent instance to modify.

`name` str \| None  
Agent name (optional).

`description` str \| None  
Agent description (optional).

### is_agent

Check if an object is an Agent.

Determines if the provided object is registered as an Agent in the system registry. When this function returns True, type checkers will recognize ‘obj’ as an Agent type.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_agent.py#L294)

``` python
def is_agent(obj: Any) -> TypeGuard[Agent]
```

`obj` Any  
Object to check against the registry.

## Types

### AgentPrompt

Prompt for agent.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_types.py#L25)

``` python
class AgentPrompt(NamedTuple)
```

#### Attributes

`instructions` str \| None  
Agent-specific contextual instructions.

`handoff_prompt` str \| None  
Prompt used when there are additional handoff agents active. Pass `None` for no additional handoff prompt.

`assistant_prompt` str \| None  
Prompt for assistant (covers tool use, CoT, etc.). Pass `None` for no additional assistant prompt.

`submit_prompt` str \| None  
Prompt to tell the model about the submit tool.

Pass `None` for no additional submit prompt.

This prompt is not used if the `assistant_prompt` contains a {submit} placeholder.

### AgentAttempts

Configure a react agent to make multiple attempts.

Submissions are evaluated using the task’s main scorer, with value of 1.0 indicating a correct answer. Scorer values are converted to float (e.g. “C” becomes 1.0) using the standard value_to_float() function. Provide an alternate conversion scheme as required via `score_value`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_types.py#L68)

``` python
class AgentAttempts(NamedTuple)
```

#### Attributes

`attempts` int  
Maximum number of attempts.

`incorrect_message` str \| Callable\[\[[AgentState](../reference/inspect_ai.agent.html.md#agentstate), list\[[Score](../reference/inspect_ai.scorer.html.md#score)\]\], Awaitable\[str\]\]  
User message reply for an incorrect submission from the model. Alternatively, an async function which returns a message.

`score_value` ValueToFloat  
Function used to extract float from scores (defaults to standard value_to_float())

### AgentContinue

Function called to determine whether the agent should continue.

Returns `True` to continue with a default continue message inserted, return `False` to stop. Returns `str` to continue with an additional custom user message inserted. Returns [AgentState](../reference/inspect_ai.agent.html.md#agentstate) to continue with the specified state.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_types.py#L58)

``` python
AgentContinue: TypeAlias = Callable[[AgentState], Awaitable[bool | str | AgentState]]
```

### AgentSubmit

Configure the submit tool of a react agent.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_types.py#L90)

``` python
class AgentSubmit(NamedTuple)
```

#### Attributes

`name` str \| None  
Name for submit tool (defaults to ‘submit’).

`description` str \| None  
Description of submit tool (defaults to ‘Submit an answer for evaluation’).

`tool` [Tool](../reference/inspect_ai.tool.html.md#tool) \| [ToolDef](../reference/inspect_ai.tool.html.md#tooldef) \| None  
Alternate implementation for submit tool.

The tool can provide its `name` and `description` internally, or these values can be overriden by the `name` and `description` fields in [AgentSubmit](../reference/inspect_ai.agent.html.md#agentsubmit)

The tool should return the `answer` provided to it for scoring.

`answer_only` bool  
Set the completion to only the answer provided by the submit tool.

By default, the answer is appended (with `answer_delimiter`) to whatever other content the model generated along with the call to `submit()`.

`answer_delimiter` str  
Delimter used when appending submit tool answer to other content the model generated along with the call to `submit()`.

`keep_in_messages` bool  
Keep the submit tool call in the message history.

Defaults to `False`, which results in calls to the `submit()` tool being removed from message history so that the model’s response looks like a standard assistant message.

This is particularly important for multi-agent systems where the presence of `submit()` calls in the history can cause coordinator agents to terminate early because they think they are done. You should therefore not set this to `True` if you are using [handoff()](../reference/inspect_ai.agent.html.md#handoff) in a multi-agent system.

## Deprecated

### bridge

Bridge an external agent into an Inspect Agent.

> **NOTE: Note**
>
> Note that this function is deprecated in favor of the [agent_bridge()](../reference/inspect_ai.agent.html.md#agent_bridge) function. If you are creating a new agent bridge we recommend you use this function rather than [bridge()](../reference/inspect_ai.agent.html.md#bridge).
>
> If you do choose to use the [bridge()](../reference/inspect_ai.agent.html.md#bridge) function, these [examples](https://github.com/UKGovernmentBEIS/inspect_ai/tree/b4670e798dc8d9ff379d4da4ef469be2468d916f/examples/bridge) demostrate its basic usage.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4ac1eb19f85b1eb9b26596c22ad9b978fc09aa27/src/inspect_ai/agent/_bridge/bridge.py#L421)

``` python
@agent
def bridge(
    agent: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
) -> Agent
```

`agent` Callable\[\[dict\[str, Any\]\], Awaitable\[dict\[str, Any\]\]\]  
Callable which takes a sample `dict` and returns a result `dict`.
