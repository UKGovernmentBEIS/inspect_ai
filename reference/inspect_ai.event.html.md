# inspect_ai.event – Inspect

## Core Events

### ModelEvent

Call to a language model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_model.py#L85)

``` python
class ModelEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['model'\]  
Event type.

`model` str  
Model name.

`role` str \| None  
Model role.

`requested_model` str \| None  
Model name the client requested, for calls made through an agent bridge (`None` for direct calls). Differs from `model` when the bridge served the request with a different model.

`origin` str \| None  
Where the call was made: `"agent"` for one of its conversation’s agent turns; otherwise `"environment"`, `"helper"`, `"tool"`, `"compaction"`, `"approval"`, `"review"`, `"sampling"`, `"sentinel"`, `"scorer"` or `"setup"` (a call outside the solve that is not scoring, such as one at sample init). Inspect owns the set of kinds, and a reader treats a kind it does not know as not an agent turn. `None` in logs written before it was recorded.

`input` list\[[ChatMessage](../reference/inspect_ai.model.html.md#chatmessage)\]  
Model input (list of messages).

`input_refs` list\[tuple\[int, int\]\] \| None  
Message pool references for input. Each element is a (start, end_exclusive) range.

`tools` list\[[ToolInfo](../reference/inspect_ai.tool.html.md#toolinfo)\]  
Tools available to the model.

`tool_choice` [ToolChoice](../reference/inspect_ai.tool.html.md#toolchoice)  
Directive to the model which tools to prefer.

`config` [GenerateConfig](../reference/inspect_ai.model.html.md#generateconfig)  
Generate config used for call to model.

`output` [ModelOutput](../reference/inspect_ai.model.html.md#modeloutput)  
Output from model.

`retries` int \| None  
Retries for the model API request.

`request_ids` list\[[ModelRequestId](../reference/inspect_ai.model.html.md#modelrequestid)\] \| None  
Provider request ids from the responses to this call’s requests (including retries).

`error` str \| None  
Error which occurred during model call.

`traceback` str \| None  
Error traceback (plain text).

`traceback_ansi` str \| None  
Error traceback with ANSI color codes for display.

`cache` Literal\['read', 'write'\] \| None  
Was this a cache read or write.

`call` [ModelCall](../reference/inspect_ai.model.html.md#modelcall) \| None  
Raw call made to model API.

`completed` UtcDatetime \| None  
Time that model call completed (see `timestamp` for started)

`working_time` float \| None  
working time for model call that succeeded (i.e. was not retried).

### ToolEvent

Call to a tool.

A host tool that `sandbox_agent_bridge(bridged_tools=...)` runs for a sandboxed agent is recorded with `metadata["bridge"]`: `server` and `tool` (the bridged server and the tool name within it, also the event’s `function`), `function` (the name the model called it by, or `None`), `proposal_id` (the id of the model’s proposing tool call, or `None`) and `grant` (`"consumed"` when a proposal matched, `"denied"` when the call was refused for lack of one, `"exempt"` when a server registered with `require_proposal=False` ran it without one, or `None` when the request was rejected before that check).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_tool.py#L13)

``` python
class ToolEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['tool'\]  
Event type.

`type` Literal\['function'\]  
Type of tool call (currently only ‘function’)

`id` str  
Unique identifier for tool call.

`function` str  
Function called.

`arguments` dict\[str, JsonValue\]  
Arguments to function.

`view` ToolCallContent \| None  
Custom view of tool call input.

`result` [ToolResult](../reference/inspect_ai.tool.html.md#toolresult)  
Function return value.

`truncated` tuple\[int, int\] \| None  
Bytes truncated (from,to) if truncation occurred

`error` [ToolCallError](../reference/inspect_ai.tool.html.md#toolcallerror) \| None  
Error that occurred during tool call.

`completed` UtcDatetime \| None  
Time that tool call completed (see `timestamp` for started)

`working_time` float \| None  
Working time for tool call (clock time minus the sample’s waiting time).

The sample is waiting while a wait is open and no model call, sandbox command or tool call is running (not counting commands run with `exec_remote()` or inside [sandbox_agent_bridge()](../reference/inspect_ai.agent.html.md#sandbox_agent_bridge)). Other work done during a wait is not counted, so set `time_limit` alongside `working_limit` to bound clock time.

`agent` str \| None  
Name of agent if the tool call was an agent handoff.

`agent_span_id` str \| None  
Span ID of the agent span, if this tool call spawned an agent.

`failed` bool \| None  
Did the tool call fail with a hard error?.

`message_id` str \| None  
Id of ChatMessageTool associated with this event.

`cancelled` bool  
Was the task cancelled?

### BranchEvent

Marks where a branched trajectory’s unique content begins.

Emitted at the point where a branch transitions from replaying its parent’s prefix to live execution. Events before this in the trajectory’s span are replay-phase re-execution; events after are the branch’s genuine new content.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_branch.py#L8)

``` python
class BranchEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['branch'\]  
Event type.

`from_anchor` str  
Anchor at the branch point (matches an `AnchorEvent.anchor_id` in the parent).

### CompactionEvent

Compaction of conversation history.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_compaction.py#L8)

``` python
class CompactionEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['compaction'\]  
Event type.

`type` Literal\['summary', 'edit', 'trim'\]  
Compaction type.

`role` str \| None  
Model role whose conversation was compacted.

`tokens_before` int \| None  
Tokens before compaction.

`tokens_after` int \| None  
Tokens after compaction.

`source` str \| None  
Compaction source (e.g. ‘inspect’, ‘claude_code’, etc.)

### ApprovalEvent

Tool approval.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_approval.py#L9)

``` python
class ApprovalEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['approval'\]  
Event type

`message` str  
Message generated by model along with tool call.

`call` ToolCall  
Tool call being approved.

`view` ToolCallView \| None  
View presented for approval.

`approver` str  
Aprover name.

`decision` Literal\['approve', 'modify', 'reject', 'escalate', 'terminate'\]  
Decision of approver.

`modified` ToolCall \| None  
Modified tool call for decision ‘modify’.

`explanation` str \| None  
Explanation for decision.

### SandboxEvent

Sandbox execution or I/O

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_sandbox.py#L10)

``` python
class SandboxEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['sandbox'\]  
Event type

`action` Literal\['exec', 'read_file', 'write_file'\]  
Sandbox action

`cmd` str \| None  
Command (for exec)

`options` dict\[str, JsonValue\] \| None  
Options for exec, read_file and write_file.

`file` str \| None  
File (for read_file and write_file)

`input` str \| None  
Input (for cmd and write_file). Truncated to 100 lines.

`result` int \| None  
Result (for exec)

`output` str \| None  
Output (for exec and read_file). Truncated to 100 lines.

`completed` UtcDatetime \| None  
Time that sandbox action completed (see `timestamp` for started)

### InfoEvent

Event with custom info/data.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_info.py#L8)

``` python
class InfoEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['info'\]  
Event type.

`source` str \| None  
Optional source for info event.

`data` JsonValue  
Data provided with event.

### ScoreEvent

Event with score.

Can be the final score for a [Sample](../reference/inspect_ai.dataset.html.md#sample), or can be an intermediate score resulting from a call to `score`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_score.py#L10)

``` python
class ScoreEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['score'\]  
Event type.

`score` [Score](../reference/inspect_ai.scorer.html.md#score)  
Score value.

`target` str \| list\[str\] \| None  
“Sample target.

`intermediate` bool  
Was this an intermediate scoring?

`scorer` str \| None  
Name of the scorer that produced this score (unique within the task).

`scorer_args` dict\[str, Any\] \| None  
Arguments the scorer was instantiated with (`None` for scores set directly by a solver via `state.scores`).

`model_usage` dict\[str, [ModelUsage](../reference/inspect_ai.model.html.md#modelusage)\] \| None  
Cumulative model usage at the time of this score.

`role_usage` dict\[str, [ModelUsage](../reference/inspect_ai.model.html.md#modelusage)\] \| None  
Cumulative model usage by role at the time of this score.

### LoggerEvent

Log message recorded with Python logger.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_logger.py#L77)

``` python
class LoggerEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['logger'\]  
Event type.

`message` [LoggingMessage](../reference/inspect_ai.event.html.md#loggingmessage)  
Logging message

### ErrorEvent

Event with sample error.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_error.py#L9)

``` python
class ErrorEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['error'\]  
Event type.

`error` [EvalError](../reference/inspect_ai.log.html.md#evalerror)  
Sample error

### SpanBeginEvent

Mark the beginning of a transcript span.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_span.py#L8)

``` python
class SpanBeginEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['span_begin'\]  
Event type.

`id` str  
Unique identifier for span.

`parent_id` str \| None  
Identifier for parent span.

`type` str \| None  
Optional ‘type’ field for span.

`name` str  
Span name.

### SpanEndEvent

Mark the end of a transcript span.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_span.py#L27)

``` python
class SpanEndEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['span_end'\]  
Event type.

`id` str  
Unique identifier for span.

## Multi-Agent Events

### CommunicationEvent

Communication between agents: a record sent or delivered, a read of what others communicated, or a wait for others.

Experimental: not yet a stable API.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_communication.py#L86)

``` python
class CommunicationEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['communication'\]  
Event type.

`kind` [CommunicationKind](../reference/inspect_ai.event.html.md#communicationkind)  
`sent`: an agent sent a record, which was delivered or refused (`send`). `delivered`: a record reached its channel and recipients (`delivery`). `read`: an agent read what others communicated, or a listing of it. `waited`: an agent waited for others (`wait`).

`source` str  
What produced the event (`"inspect_swarm"`). It names the owner of `data`.

`agent` str  
The name of the agent that acted: the sender (`sent`, `delivered`), the reader (`read`) or the waiter (`waited`).

`agent_span_id` str \| None  
The span of the agent that acted.

`loop_span_id` str \| None  
The agent span of the loop that acted: the agent’s own loop, or a subagent acting for it.

`nested` bool  
The loop that acted is not the agent’s own, such as one of its subagents.

`channel` str \| None  
The channel the communication went through. `None` for a wait, whose channels are in `wait`.

`record_ids` list\[str\]  
The ids of the records the event concerns: the record sent or delivered, or, for `read`, the producer’s records for what was read (for the shared memory, each file’s last write at the version read). They identify state, not text: a listing or a partial view names a record whose content it did not show.

`send` [CommunicationSend](../reference/inspect_ai.event.html.md#communicationsend) \| None  
For `sent`, the record and its refusal.

`delivery` [CommunicationDelivery](../reference/inspect_ai.event.html.md#communicationdelivery) \| None  
For `delivered`, the recipients and the delivery’s order.

`wait` [CommunicationWait](../reference/inspect_ai.event.html.md#communicationwait) \| None  
For `waited`, the wait.

`data` dict\[str, JsonValue\]  
Further details in the format `source` defines, such as a channel’s operation or the versions of files read.

### SwarmEvent

Evidence from an agent swarm (inspect_swarm) other than communication: a member’s result, the final answer’s selection, the swarm’s ledger or its metrics.

The swarm defines `kind` and the format of `data`. Experimental: not yet a stable API.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_swarm.py#L8)

``` python
class SwarmEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['swarm'\]  
Event type.

`kind` str  
What the event records (`"member_result"`, `"final"`, `"ledger"`, `"metrics"`).

`member` str \| None  
The member the event concerns, if any.

`data` dict\[str, JsonValue\]  
The evidence, in the format the swarm defines for `kind`, with that format’s version in `data["version"]`.

## Event Tree

### event_tree

Build a tree representation of a sequence of events.

Organize events heirarchially into event spans.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_tree.py#L43)

``` python
def event_tree(events: Sequence[Event]) -> EventTree
```

`events` Sequence\[Event\]  
Sequence of `Event`.

### event_tree_walk

Walk an event tree yielding nodes matching a filter.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_tree.py#L144)

``` python
def event_tree_walk(
    tree: EventTree,
    filter: type[T]
    | tuple[type[T], ...]
    | Callable[[EventTreeNode], bool]
    | None = None,
) -> Iterable[T] | Iterable[EventTreeNode]
```

`tree` [EventTree](../reference/inspect_ai.event.html.md#eventtree)  
Event tree to walk.

`filter` type\[T\] \| tuple\[type\[T\], ...\] \| Callable\[\[[EventTreeNode](../reference/inspect_ai.event.html.md#eventtreenode)\], bool\] \| None  
A type, tuple of types (passed to `isinstance`), a predicate function, or None to yield all nodes.

### event_sequence

Flatten a span forest back into a properly ordered seqeunce.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_tree.py#L94)

``` python
def event_sequence(tree: EventTree | EventTreeSpan) -> Iterable[Event]
```

`tree` [EventTree](../reference/inspect_ai.event.html.md#eventtree) \| [EventTreeSpan](../reference/inspect_ai.event.html.md#eventtreespan)  
Event tree or EventTreeSpan.

### EventTree

Tree of events (has invividual events and event spans).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_tree.py#L13)

``` python
EventTree: TypeAlias = list[EventTreeNode]
```

### EventTreeSpan

Event tree node representing a span of events.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_tree.py#L17)

``` python
@dataclass
class EventTreeSpan
```

#### Attributes

`id` str  
Span id.

`parent_id` str \| None  
Parent span id.

`type` str \| None  
Optional ‘type’ field for span.

`name` str  
Span name.

`begin` [SpanBeginEvent](../reference/inspect_ai.event.html.md#spanbeginevent)  
Span begin event.

`end` [SpanEndEvent](../reference/inspect_ai.event.html.md#spanendevent) \| None  
Span end event (if any).

`children` list\[[EventTreeNode](../reference/inspect_ai.event.html.md#eventtreenode)\]  
Children in the span.

### EventTreeNode

Node in an event tree.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_tree.py#L10)

``` python
EventTreeNode: TypeAlias = Union["EventTreeSpan", Event]
```

## Timeline

### timeline_build

Build a Timeline from a flat event list.

Transforms a flat event stream into a hierarchical [Timeline](../reference/inspect_ai.event.html.md#timeline) tree with agent-centric interpretation. The pipeline has two phases:

**Phase 1 — Structure extraction:**

Uses [event_tree()](../reference/inspect_ai.event.html.md#event_tree) to parse span_begin/span_end events into a tree, then looks for top-level phase spans (“init”, “solvers”, “scorers”):

- If present, partitions events into init (setup), agent (solvers), and scoring sections.
- If absent, treats the entire event stream as the agent.

**Phase 2 — Agent classification:**

Within the agent section, spans are classified as agents or unrolled:

============================== ======================================= Span type Result ============================== ======================================= `type="agent"` `TimelineSpan(span_type="agent")` `type="solver"` wrapping agent `TimelineSpan(span_type="agent")` `type="solver"` (primitive) Unrolled into parent `type="tool"` + ModelEvents `TimelineSpan(span_type="agent")` ToolEvent with `agent` field `TimelineSpan(span_type="agent")` `type="tool"` (no models) Unrolled into parent Any other span type Unrolled into parent ============================== =======================================

“Unrolled” means the span wrapper is removed and its child events dissolve into the parent’s content list.

**Phase 3 — Post-processing passes:**

- Utility agent classification (single-turn agents with different system prompts)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L374)

``` python
def timeline_build(
    events: list[Event], *, name: str | None = None, description: str | None = None
) -> Timeline
```

`events` list\[Event\]  
Flat list of Events from a transcript.

`name` str \| None  
Optional name for timeline (defaults to “Default”)

`description` str \| None  
Optional description for timeline (defaults to ““)

### timeline_dump

Serialize a Timeline to a JSON-compatible dict.

Converts a Timeline into a plain dictionary suitable for JSON serialization. Event objects within the timeline are replaced by their UUIDs, keeping the serialized form compact and self-referencing.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L333)

``` python
def timeline_dump(timeline: Timeline) -> dict[str, Any]
```

`timeline` [Timeline](../reference/inspect_ai.event.html.md#timeline)  
The Timeline to serialize.

### timeline_filter

Return a new timeline with only spans matching the predicate.

Recursively walks span content and branches, keeping [TimelineSpan](../reference/inspect_ai.event.html.md#timelinespan) items where `predicate(span)` returns `True`. Non-matching spans and their entire subtrees are pruned. [TimelineEvent](../reference/inspect_ai.event.html.md#timelineevent) items are always kept because they belong to the parent span.

Use this to pre-filter a timeline before passing it to `timeline_messages()`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L1381)

``` python
def timeline_filter(
    timeline: Timeline,
    predicate: Callable[[TimelineSpan], bool],
) -> Timeline
```

`timeline` [Timeline](../reference/inspect_ai.event.html.md#timeline)  
The timeline to filter.

`predicate` Callable\[\[[TimelineSpan](../reference/inspect_ai.event.html.md#timelinespan)\], bool\]  
Function that receives a [TimelineSpan](../reference/inspect_ai.event.html.md#timelinespan) and returns `True` to keep it (and its subtree), `False` to prune it.

### timeline_load

Deserialize a Timeline from a dict produced by `timeline_dump`.

Reconstructs a full Timeline by resolving the UUID strings stored in `data` back to their corresponding Event objects from `events`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L351)

``` python
def timeline_load(data: dict[str, Any], events: list[Event]) -> Timeline
```

`data` dict\[str, Any\]  
A dict previously produced by `timeline_dump`.

`events` list\[Event\]  
The flat list of Event objects whose UUIDs appear in `data`. Events without a UUID are ignored.

### timeline_branch

Context manager for creating a timeline branch.

Emits an `AnchorEvent` in the current (parent) span so the viewer can resolve `from_anchor` to a position, then opens a `type="branch"` span and emits a [BranchEvent](../reference/inspect_ai.event.html.md#branchevent) inside it.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L530)

``` python
@contextlib.asynccontextmanager
async def timeline_branch(
    *, name: str, from_anchor: str, id: str | None = None
) -> AsyncIterator[None]
```

`name` str  
Name of branch span.

`from_anchor` str  
Anchor id at the branch point.

`id` str \| None  
Optional span ID. Generated if not provided.

### Timeline

A named timeline view over a transcript.

Multiple timelines allow different interpretations of the same event stream — e.g. a default agent-centric view alongside an alternative grouping or filtered view.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L299)

``` python
class Timeline(BaseModel)
```

#### Methods

render  
Render an ASCII swimlane diagram of the timeline.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L314)

``` python
def render(self, width: int | None = None) -> str
```

`width` int \| None  
Total width of the output in characters. Defaults to 120.

### TimelineEvent

Wraps a single Event.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L89)

``` python
class TimelineEvent(BaseModel)
```

#### Methods

start_time  
Event timestamp (required field on all events).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L116)

``` python
def start_time(self) -> datetime
```

end_time  
Event completion time if available, else timestamp.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L120)

``` python
def end_time(self) -> datetime
```

total_tokens  
Tokens from this event (ModelEvent only).

Includes input_tokens_cache_read and input_tokens_cache_write in the total, as these represent actual token consumption for any LLM system using prompt caching. The sum of all token fields provides an accurate measure of total context window usage across all sources.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L127)

``` python
def total_tokens(self) -> int
```

idle_time  
Seconds of idle time (always 0 for a single event).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L145)

``` python
def idle_time(self) -> float
```

### TimelineSpan

A span of execution — agent, scorer, tool, or root.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L212)

``` python
class TimelineSpan(BaseModel)
```

#### Attributes

`tool_invoked` bool  
True if this agent span was invoked as a tool (via task/as_tool/handoff).

Tool-invoked subagents are explicit user-intended sub-trajectories and are never classified as `utility` regardless of turn count or prompt differences. The `_classify_utility_agents` heuristic targets internal helper model calls, not explicit subagent invocations.

#### Methods

start_time  
Earliest start time among content (and optionally branches).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L247)

``` python
def start_time(self, include_branches: bool = True) -> datetime
```

`include_branches` bool  
Include branches in time calcluation.

end_time  
Latest end time among content (and optionally branches).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L256)

``` python
def end_time(self, include_branches: bool = True) -> datetime
```

`include_branches` bool  
Include branches in time calcluation.

total_tokens  
Sum of tokens from content (and optionally branches).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L265)

``` python
def total_tokens(self, include_branches: bool = True) -> int
```

`include_branches` bool  
Include branches in token calcluation.

idle_time  
Seconds of idle time within this span (and optionally branches).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L274)

``` python
def idle_time(self, include_branches: bool = True) -> float
```

`include_branches` bool  
Include branches in time calcluation.

### Outline

Hierarchical outline of events for an agent.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L293)

``` python
class Outline(BaseModel)
```

### OutlineNode

A node in an agent’s outline, referencing an event by UUID.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_timeline.py#L286)

``` python
class OutlineNode(BaseModel)
```

## Eval Events

### SampleInitEvent

Beginning of processing a Sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_sample_init.py#L15)

``` python
class SampleInitEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['sample_init'\]  
Event type.

`sample` Annotated\[[Sample](../reference/inspect_ai.dataset.html.md#sample), PlainSerializer(lambda sample: sample.model_copy(update={description: None}), return_type=Sample)\]  
Sample.

`state` JsonValue  
Initial state.

Defaults to None so events round-trip through log serialization, which writes with exclude_none=True (a None state is omitted from the written JSON and must not fail validation on read).

### SampleLimitEvent

The sample was unable to finish processing due to a limit

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_sample_limit.py#L8)

``` python
class SampleLimitEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['sample_limit'\]  
Event type.

`type` Literal\['message', 'time', 'working', 'token', 'turn', 'cost', 'operator', 'custom'\]  
Type of limit that halted processing

`message` str  
A message associated with this limit

`limit` float \| None  
The limit value (if any)

### StateEvent

Change to the current [TaskState](../reference/inspect_ai.solver.html.md#taskstate)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_state.py#L9)

``` python
class StateEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['state'\]  
Event type.

`changes` list\[JsonChange\]  
List of changes to the [TaskState](../reference/inspect_ai.solver.html.md#taskstate)

### StoreEvent

Change to data within the current [Store](../reference/inspect_ai.util.html.md#store).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_store.py#L10)

``` python
class StoreEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['store'\]  
Event type.

`changes` list\[JsonChange\]  
List of changes to the [Store](../reference/inspect_ai.util.html.md#store).

### InputEvent

Input screen interaction.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_input.py#L21)

``` python
class InputEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['input'\]  
Event type.

`input` str  
Input interaction (plain text).

`input_ansi` str  
Input interaction (ANSI).

`message` str \| None  
Prompt shown to the user (set for `ask_user`/`request_input` interactions).

`fields` list\[InputField\] \| None  
Fields requested from the user (set for `ask_user`/`request_input` interactions).

`outcome` Literal\['accepted', 'declined', 'cancelled'\] \| None  
How the `ask_user` interaction concluded.

`content` dict\[str, Any\] \| None  
Structured answer when `outcome == "accepted"`.

### ScoreEditEvent

Event recorded when a score is edited.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_score_edit.py#L9)

``` python
class ScoreEditEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['score_edit'\]  
Event type.

`score_name` str  
Name of the score being edited.

`edit` ScoreEdit  
The edit being applied to the score.

### InterruptEvent

Records that an agent’s turn or sample was cut short.

Emitted in three cases:

- `source="user_cancel"` — an ACP client (e.g. an editor or TUI) called `session/cancel` while a turn was in flight.
- `source="limit"` — a sample-level limit (tokens, time, cost, messages) tripped during execution.
- `source="system"` — the eval is shutting down for an external reason and is cancelling active samples.

The `interrupted` field records what was running at the moment the cancel reached the cancel scope. `interrupted_tool_call_id` and `interrupted_model_event_id` give cross-references when applicable so downstream consumers can correlate this event with the in-flight [ToolEvent](../reference/inspect_ai.event.html.md#toolevent) or [ModelEvent](../reference/inspect_ai.event.html.md#modelevent).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_interrupt.py#L8)

``` python
class InterruptEvent(BaseEvent)
```

#### Attributes

`uuid` str \| None  
Unique identifer for event.

`span_id` str \| None  
Span the event occurred within.

`timestamp` UtcDatetime  
Clock time at which event occurred.

`working_start` float  
Working time (within sample) at which the event occurred.

`metadata` dict\[str, Any\] \| None  
Additional event metadata.

`pending` bool \| None  
Is this event pending?

`event` Literal\['interrupt'\]  
Event type.

`source` Literal\['user_cancel', 'limit', 'system'\]  
What caused the interrupt.

`interrupted` Literal\['generate', 'tool_call', 'between_turns'\]  
What was running at the moment of the interrupt.

`interrupted_tool_call_id` str \| None  
`ToolEvent.id` (the underlying `ToolCall.id`) of the in-flight tool, if any.

`interrupted_model_event_id` str \| None  
`ModelEvent.uuid` of the in-flight model call, if any.

## Types

### LoggingLevel

Logging level.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_logger.py#L9)

``` python
LoggingLevel = Literal[
    "debug", "trace", "http", "sandbox", "info", "warning", "error", "critical"
]
```

### LoggingMessage

Message written to Python log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_logger.py#L15)

``` python
class LoggingMessage(BaseModel)
```

#### Attributes

`name` str \| None  
Logger name (e.g. ‘httpx’)

`level` [LoggingLevel](../reference/inspect_ai.event.html.md#logginglevel)  
Logging level.

`message` str  
Log message.

`created` float  
Message created time.

`filename` str  
Logged from filename.

`module` str  
Logged from module.

`lineno` int  
Logged from line number.

### CommunicationKind

What a [CommunicationEvent](../reference/inspect_ai.event.html.md#communicationevent) records.

Experimental: not yet a stable API.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_communication.py#L8)

``` python
CommunicationKind: TypeAlias = Literal["sent", "delivered", "read", "waited"]
```

### CommunicationRecord

For `sent`, what one agent communicated: a message, or a change to state other agents read.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_communication.py#L15)

``` python
class CommunicationRecord(BaseModel)
```

#### Attributes

`id` str \| None  
For `sent`, the producer’s id for the record, if it has one.

`kind` str  
For `sent`, what the record does in its channel, in the channel’s terms (`"message"`, `"create"`, `"append"`).

`sender` str  
For `sent`, the name of the agent that sent it.

`to` list\[str\]  
For `sent`, the addresses as written. Empty for an unaddressed record, such as a write to shared state.

`recipients` list\[str\]  
For `sent`, the agents the addresses resolved to.

`content` str \| None  
For `sent`, the text it carries, or `None` when the producer cannot see it (such as encrypted content).

`reply_to` str \| None  
For `sent`, the id of a record this one answers.

### CommunicationRejection

For `sent`, why a record that was sent was not delivered.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_communication.py#L40)

``` python
class CommunicationRejection(BaseModel)
```

#### Attributes

`control` str  
For `sent`, the control that refused it, in the producer’s terms (`"rate"`, `"admit"`).

`reason` str  
For `sent`, the reason the sender was given.

### CommunicationSend

For `sent`, the record an agent sent, and why it was refused if it was.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_communication.py#L50)

``` python
class CommunicationSend(BaseModel)
```

#### Attributes

`record` [CommunicationRecord](../reference/inspect_ai.event.html.md#communicationrecord)  
For `sent`, the record.

`rejected` [CommunicationRejection](../reference/inspect_ai.event.html.md#communicationrejection) \| None  
For `sent`, why the record was refused; `None` when it was delivered.

### CommunicationDelivery

For `delivered`, whom a record reached and in what order.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_communication.py#L60)

``` python
class CommunicationDelivery(BaseModel)
```

#### Attributes

`recipients` list\[str\]  
For `delivered`, the agents it reached.

`seq` int \| None  
For `delivered`, the delivery’s position in the order the producer delivered records, across its channels.

### CommunicationWait

For `waited`, an agent waiting for other agents.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14fd61845184c432927dd87799b1085516c8826c/src/inspect_ai/event/_communication.py#L70)

``` python
class CommunicationWait(BaseModel)
```

#### Attributes

`id` str \| None  
For `waited`, the producer’s id for the wait.

`channels` list\[str\]  
For `waited`, the channels it waited on.

`outcome` str  
For `waited`, what ended it, in the producer’s terms (`"news"`, `"timeout"`, `"cancelled"`).

`duration` float  
For `waited`, seconds from the start of the wait until it ended.
