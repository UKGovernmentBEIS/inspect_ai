# inspect_ai.event


## Core Events

### ModelEvent

Call to a language model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_model.py#L17)

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

`input` list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
Model input (list of messages).

`tools` list\[[ToolInfo](inspect_ai.tool.qmd#toolinfo)\]  
Tools available to the model.

`tool_choice` [ToolChoice](inspect_ai.tool.qmd#toolchoice)  
Directive to the model which tools to prefer.

`config` [GenerateConfig](inspect_ai.model.qmd#generateconfig)  
Generate config used for call to model.

`output` [ModelOutput](inspect_ai.model.qmd#modeloutput)  
Output from model.

`retries` int \| None  
Retries for the model API request.

`error` str \| None  
Error which occurred during model call.

`traceback` str \| None  
Error traceback (plain text).

`traceback_ansi` str \| None  
Error traceback with ANSI color codes for display.

`cache` Literal\['read', 'write'\] \| None  
Was this a cache read or write.

`call` [ModelCall](inspect_ai.model.qmd#modelcall) \| None  
Raw call made to model API.

`completed` UtcDatetime \| None  
Time that model call completed (see `timestamp` for started)

`working_time` float \| None  
working time for model call that succeeded (i.e. was not retried).

### ToolEvent

Call to a tool.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_tool.py#L13)

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

`result` [ToolResult](inspect_ai.tool.qmd#toolresult)  
Function return value.

`truncated` tuple\[int, int\] \| None  
Bytes truncated (from,to) if truncation occurred

`error` [ToolCallError](inspect_ai.tool.qmd#toolcallerror) \| None  
Error that occurred during tool call.

`completed` UtcDatetime \| None  
Time that tool call completed (see `timestamp` for started)

`working_time` float \| None  
Working time for tool call (i.e. time not spent waiting on semaphores).

`agent` str \| None  
Name of agent if the tool call was an agent handoff.

`failed` bool \| None  
Did the tool call fail with a hard error?.

`message_id` str \| None  
Id of ChatMessageTool associated with this event.

`cancelled` bool  
Was the task cancelled?

### CompactionEvent

Compaction of conversation history.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_compaction.py#L8)

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

`tokens_before` int \| None  
Tokens before compaction.

`tokens_after` int \| None  
Tokens after compaction.

`source` str \| None  
Compaction source (e.g. ‘inspect’, ‘claude_code’, etc.)

### ApprovalEvent

Tool approval.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_approval.py#L9)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_sandbox.py#L10)

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
Options (for exec)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_info.py#L8)

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

Can be the final score for a `Sample`, or can be an intermediate score
resulting from a call to `score`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_score.py#L10)

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

`score` [Score](inspect_ai.scorer.qmd#score)  
Score value.

`target` str \| list\[str\] \| None  
“Sample target.

`intermediate` bool  
Was this an intermediate scoring?

`model_usage` dict\[str, [ModelUsage](inspect_ai.model.qmd#modelusage)\] \| None  
Cumulative model usage at the time of this score.

`role_usage` dict\[str, [ModelUsage](inspect_ai.model.qmd#modelusage)\] \| None  
Cumulative model usage by role at the time of this score.

### LoggerEvent

Log message recorded with Python logger.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_logger.py#L77)

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

`message` [LoggingMessage](inspect_ai.event.qmd#loggingmessage)  
Logging message

### ErrorEvent

Event with sample error.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_error.py#L9)

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

`error` [EvalError](inspect_ai.log.qmd#evalerror)  
Sample error

### SpanBeginEvent

Mark the beginning of a transcript span.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_span.py#L8)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_span.py#L27)

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

## Event Tree

### event_tree

Build a tree representation of a sequence of events.

Organize events heirarchially into event spans.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_tree.py#L43)

``` python
def event_tree(events: Sequence[Event]) -> EventTree
```

`events` Sequence\[Event\]  
Sequence of `Event`.

### event_sequence

Flatten a span forest back into a properly ordered seqeunce.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_tree.py#L94)

``` python
def event_sequence(tree: EventTree) -> Iterable[Event]
```

`tree` [EventTree](inspect_ai.event.qmd#eventtree)  
Event tree

### EventTree

Tree of events (has invividual events and event spans).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_tree.py#L13)

``` python
EventTree: TypeAlias = list[EventTreeNode]
```

### EventTreeSpan

Event tree node representing a span of events.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_tree.py#L17)

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

`begin` [SpanBeginEvent](inspect_ai.event.qmd#spanbeginevent)  
Span begin event.

`end` [SpanEndEvent](inspect_ai.event.qmd#spanendevent) \| None  
Span end event (if any).

`children` list\[[EventTreeNode](inspect_ai.event.qmd#eventtreenode)\]  
Children in the span.

### EventTreeNode

Node in an event tree.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_tree.py#L10)

``` python
EventTreeNode: TypeAlias = Union["EventTreeSpan", Event]
```

## Timeline

### timeline_build

Build a Timeline from a flat event list.

Transforms a flat event stream into a hierarchical `Timeline` tree with
agent-centric interpretation. The pipeline has two phases:

**Phase 1 — Structure extraction:**

Uses `event_tree()` to parse span_begin/span_end events into a tree,
then looks for top-level phase spans (“init”, “solvers”, “scorers”):

- If present, partitions events into init (setup), agent (solvers), and
  scoring sections.
- If absent, treats the entire event stream as the agent.

**Phase 2 — Agent classification:**

Within the agent section, spans are classified as agents or unrolled:

============================== =======================================
Span type Result ==============================
======================================= `type="agent"`
`TimelineSpan(span_type="agent")` `type="solver"`
`TimelineSpan(span_type="agent")` `type="tool"` + ModelEvents
`TimelineSpan(span_type="agent")` ToolEvent with `agent` field
`TimelineSpan(span_type="agent")` `type="tool"` (no models) Unrolled
into parent Any other span type Unrolled into parent
============================== =======================================

“Unrolled” means the span wrapper is removed and its child events
dissolve into the parent’s content list.

**Phase 3 — Post-processing passes:**

- Auto-branch detection (re-rolled ModelEvents with identical inputs)
- Utility agent classification (single-turn agents with different system
  prompts)
- Recursive branch classification

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_timeline.py#L385)

``` python
def timeline_build(events: list[Event]) -> Timeline
```

`events` list\[Event\]  
Flat list of Events from a transcript.

### timeline_dump

Serialize a Timeline to a JSON-compatible dict.

Converts a Timeline into a plain dictionary suitable for JSON
serialization. Event objects within the timeline are replaced by their
UUIDs, keeping the serialized form compact and self-referencing.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_timeline.py#L344)

``` python
def timeline_dump(timeline: Timeline) -> dict[str, Any]
```

`timeline` [Timeline](inspect_ai.event.qmd#timeline)  
The Timeline to serialize.

### timeline_filter

Return a new timeline with only spans matching the predicate.

Recursively walks the span tree, keeping `TimelineSpan` items where
`predicate(span)` returns `True`. Non-matching spans and their entire
subtrees are pruned. `TimelineEvent` items are always kept (they belong
to the parent span).

Use this to pre-filter a timeline before passing it to
`timeline_messages()`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_timeline.py#L1281)

``` python
def timeline_filter(
    timeline: Timeline,
    predicate: Callable[[TimelineSpan], bool],
) -> Timeline
```

`timeline` [Timeline](inspect_ai.event.qmd#timeline)  
The timeline to filter.

`predicate` Callable\[\[[TimelineSpan](inspect_ai.event.qmd#timelinespan)\], bool\]  
Function that receives a `TimelineSpan` and returns `True` to keep it
(and its subtree), `False` to prune it.

### timeline_load

Deserialize a Timeline from a dict produced by `timeline_dump`.

Reconstructs a full Timeline by resolving the UUID strings stored in
`data` back to their corresponding Event objects from `events`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_timeline.py#L362)

``` python
def timeline_load(data: dict[str, Any], events: list[Event]) -> Timeline
```

`data` dict\[str, Any\]  
A dict previously produced by `timeline_dump`.

`events` list\[Event\]  
The flat list of Event objects whose UUIDs appear in `data`. Events
without a UUID are ignored.

### Timeline

A named timeline view over a transcript.

Multiple timelines allow different interpretations of the same event
stream — e.g. a default agent-centric view alongside an alternative
grouping or filtered view.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_timeline.py#L310)

``` python
class Timeline(BaseModel)
```

#### Methods

render  
Render an ASCII swimlane diagram of the timeline.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_timeline.py#L325)

``` python
def render(self, width: int | None = None) -> str
```

`width` int \| None  
Total width of the output in characters. Defaults to 120.

### TimelineBranch

A discarded alternative path from a branch point.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_timeline.py#L269)

``` python
class TimelineBranch(BaseModel)
```

#### Attributes

`start_time` datetime  
Earliest start time among content.

`end_time` datetime  
Latest end time among content.

`total_tokens` int  
Sum of tokens from all content.

`idle_time` float  
Seconds of idle time within this branch.

### TimelineEvent

Wraps a single Event.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_timeline.py#L94)

``` python
class TimelineEvent(BaseModel)
```

#### Attributes

`start_time` datetime  
Event timestamp (required field on all events).

`end_time` datetime  
Event completion time if available, else timestamp.

`total_tokens` int  
Tokens from this event (ModelEvent only).

Includes input_tokens_cache_read and input_tokens_cache_write in the
total, as these represent actual token consumption for any LLM system
using prompt caching. The sum of all token fields provides an accurate
measure of total context window usage across all sources.

`idle_time` float  
Seconds of idle time (always 0 for a single event).

### TimelineSpan

A span of execution — agent, scorer, tool, or root.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_timeline.py#L221)

``` python
class TimelineSpan(BaseModel)
```

#### Attributes

`start_time` datetime  
Earliest start time among content and branches.

`end_time` datetime  
Latest end time among content and branches.

`total_tokens` int  
Sum of tokens from all content and branches.

`idle_time` float  
Seconds of idle time within this span.

### Outline

Hierarchical outline of events for an agent.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_timeline.py#L304)

``` python
class Outline(BaseModel)
```

### OutlineNode

A node in an agent’s outline, referencing an event by UUID.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_timeline.py#L297)

``` python
class OutlineNode(BaseModel)
```

## Eval Events

### SampleInitEvent

Beginning of processing a Sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_sample_init.py#L9)

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

`sample` [Sample](inspect_ai.dataset.qmd#sample)  
Sample.

`state` JsonValue  
Initial state.

### SampleLimitEvent

The sample was unable to finish processing due to a limit

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_sample_limit.py#L8)

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

`type` Literal\['message', 'time', 'working', 'token', 'cost', 'operator', 'custom'\]  
Type of limit that halted processing

`message` str  
A message associated with this limit

`limit` float \| None  
The limit value (if any)

### StateEvent

Change to the current `TaskState`

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_state.py#L9)

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
List of changes to the `TaskState`

### StoreEvent

Change to data within the current `Store`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_store.py#L10)

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
List of changes to the `Store`.

### InputEvent

Input screen interaction.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_input.py#L8)

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

### ScoreEditEvent

Event recorded when a score is edited.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_score_edit.py#L9)

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

## Types

### LoggingLevel

Logging level.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_logger.py#L9)

``` python
LoggingLevel = Literal[
    "debug", "trace", "http", "sandbox", "info", "warning", "error", "critical"
]
```

### LoggingMessage

Message written to Python log.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/924aa90c5192c485836cfb9005373c21d76702f8/src/inspect_ai/event/_logger.py#L15)

``` python
class LoggingMessage(BaseModel)
```

#### Attributes

`name` str \| None  
Logger name (e.g. ‘httpx’)

`level` [LoggingLevel](inspect_ai.event.qmd#logginglevel)  
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
