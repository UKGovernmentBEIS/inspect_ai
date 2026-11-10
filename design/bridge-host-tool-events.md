# Bridged Host Tool Events

## Overview

`sandbox_agent_bridge(bridged_tools=...)` runs host-side Inspect tools for a
sandboxed agent: the agent's MCP `tools/call` reaches the bridge's sandbox
service, which runs the tool in the Inspect process. Every such request is
recorded in the sample transcript as one `ToolEvent`, in the same layout as a
native tool call: executed, denied, or rejected before execution.

A call proposed in a bridged generation takes the id of the proposing tool
call in the response handed to the agent and is recorded in the span of the
`ModelEvent` that generated it, so the viewer, ACP clients, dataframes and
scanners pair it with its proposal as they pair native tool events. The
pairing comes from the execution grant the bridge records for each proposed
call, which carries the proposing call and, when a `ModelEventSink` placed the
generation in another span, that span. When a bridge filter edits or
replaces the response, the proposal is the call the agent received, which
the logged `ModelEvent` may not contain.
`metadata["bridge"]` on the event names the bridged server and tool, the name
the model called it by, the proposing call and whether a proposal matched.
While it runs the event is pending and the operator can cancel it. Errors
and limits are classified, and text results truncated, as for a native tool
call.

The code is [`host_tool.py`](../src/inspect_ai/agent/_bridge/sandbox/host_tool.py)
(`execute_host_tool()`), the grant record in
[`sandbox/types.py`](../src/inspect_ai/agent/_bridge/sandbox/types.py)
(`_Proposal`, `_ToolExecutionGrant`), and the span capture in
`bridge_generate()` in [`util.py`](../src/inspect_ai/agent/_bridge/util.py)
(`_SpanCapturingSink`, `_StartingSpanCapturingSink`).

## Scope

- Which host tool calls run (one execution per proposed call, the
  `require_proposal=False` opt-out, how a proposal is matched to a bridged
  tool) is the bridge's execution contract, described in the user docs:
  [Execution Contract](../docs/agent-bridge.qmd#bridged-tools-execution) and
  [Matching a Proposal](../docs/agent-bridge.qmd#bridged-tools-matching).
  Recording follows that decision and never changes it.
- What `metadata["bridge"]` means to a reader of the log is in the user docs'
  [Transcript](../docs/agent-bridge.qmd#transcript) section and the
  `ToolEvent` docstring.
- Tools the agent runs itself (its own shell or file tools) have no
  `ToolEvent`; they live only in the `ModelEvent`s, and ACP synthesizes cards
  for them.
- No new event type or `ToolEvent` field: the host marker is
  `BaseEvent.metadata`.

## How a request is recorded

The sandbox service runs each `call_tool` request in its own task, which
inherits the context the bridge's task group started in: the sample
transcript, the active sample, its timing, and the span current when the
bridge was entered. `call_tool` delegates to `execute_host_tool(bridge,
server, tool, arguments)`, which decides and records the request in this
order:

1. **Resolve.** An unknown server, then an unknown tool on a known server, is
   recorded as a `parsing` error and raised as `ValueError("Unknown bridged
   tools server: <server>")` or `ValueError("Unknown tool '<tool>' in server
   '<server>'")`. The name as sent is recorded as the event's `function`.
2. **Depth.** Arguments nested deeper than `MAX_TOOL_CALL_ARGUMENTS_DEPTH`
   (100), the bound native execution applies to model arguments, are recorded
   as a `parsing` error with the native depth message and raised as
   `ToolParsingError`. The recorded arguments enter the log, and the log's
   writer, readers and condensation handle only bounded nesting.
3. **Grant.** For object arguments, `consume_tool_execution_grant(server,
   tool, arguments)` consumes a matching grant (its selection order is that
   helper's). If none matches and the
   server requires proposals, the request is denied: recorded as a
   `permission` error, raised as `PermissionError` with the denial message,
   and logged once with the `require_proposal=False` guidance. Arguments that
   are not an object never match a grant, so they are denied unless the
   server is exempt.
4. **Schema.** The arguments are validated against the tool's parameters
   (`validate_tool_input()`), as a native call is. A failure is recorded as a
   `parsing` error and raised as `ToolParsingError`. This runs after the grant
   check: an unproposed call with invalid arguments is denied, and a proposed
   one consumes its grant and is recorded under its proposal's span, taking
   the proposing id by the same rule as an execution (below).
   The arguments are otherwise forwarded as the agent sent them; they are not
   converted to the tool's parameter types.
5. **Execute** under the proposal's span (below): construct a pending
   `ToolEvent`, open a `tool` span, emit the event, register it with the
   sample's execution observer, and await the tool inside a per-call cancel
   scope, under `sentinel_scope("tool")` and `known_work()` as a native call
   is. The event is finalised exactly once, on every path, with the result or
   error, `completed` and `working_time` (sample working time over the call,
   `sample_working_time_since()`), then published with `_event_updated()`.
6. **Reply** with the result as recorded, or raise.

Requests that do not execute (steps 1 to 4) are recorded as single completed
events (`pending` unset, `working_time` 0) inside their own `tool` span, the
shape a native denial has. Where the recorded arguments must be an object, a
non-object or over-deep value is recorded as `{}`; the message the agent
receives does not change.

The service dispatcher turns an exception that leaves `call_tool` into an RPC
error reply, which the in-sandbox proxy returns as a JSON-RPC `-32603` error:

- an ordinary exception becomes `Error calling method call_tool: <message>`,
  with the traceback kept on the host; a teardown the exception triggers (an
  unexpected exception failing the sample) may pre-empt the reply;
- an exception with a `TerminateSampleError` anywhere in its history (group
  leaves, causes or context, as `find_control_flow()` searches) gets a bounded
  attempt at the reply `Terminating: <termination>`, after which the
  dispatcher raises the termination out of the service task, ending the
  sample;
- a cancellation sends no reply: the request is abandoned.

### Event layout

The layout is the native one. The event is constructed before the `tool`
span opens, so `BaseEvent` stamps it with the enclosing span; the span is the
event's sibling, and events the tool emits (a `SandboxEvent`, a nested
`ModelEvent`) carry the tool span's id. The stream is `span_begin(tool)`,
`tool`, nested events, `span_end`. The viewer renders the `ToolEvent` as a
tool panel beside its `tool` span node, which holds the nested events, and
omits the span node when it is empty. A host tool that calls a model records its
`ModelEvent` under the tool span, where a native tool's nested generation
goes: no bridge sink is active in the service task.

A span-ID provider (`span_id_provider()`) can suspend while `span()` allocates
the tool span. If the request is cancelled there, or the provider fails, the
event is still recorded (`cancelled`, the rejection it was, or `failed`), and
a provider failure fails the sample through `bridge.request_fail()`. A grant
consumed before that point is not restored.

## Pairing with the proposal

`bridge_generate()` calls `register_tool_execution_grants(calls, tools, *,
span_id=None)` with the calls in each response handed to the agent, after
approval, and the declarations that generation used (the attempt's tools,
which a filter may have rewritten, plus tools declared in the input, such as
Responses `tool_search` results). The keyword is on the base `AgentBridge`
hook as well as the sandbox override, since `bridge_generate()` serves
in-process bridges too and passes it for every generation.

The sandbox override resolves each call to the bridged tools it denotes and
builds one `_Proposal` per call, shared by every grant that call mints (one
per denoted tool):

```python
class _Proposal:
    call: ToolCall        # the proposing call: id, model-facing function, view
    span_id: str | None   # span to record executions under, or None (below)
    paired: bool          # whether an execution has taken call.id

    def take_id(self) -> str: ...  # call.id the first time, a fresh id after

class _ToolExecutionGrant(NamedTuple):
    server: str
    tool: str
    arguments: dict[str, Any]   # as approved, JSON-normalized
    proposal: _Proposal
```

`consume_tool_execution_grant()` returns the matched grant (or `None`), and
the event takes `proposal.take_id()` as its id and the proposal's
`call.view`, and records its model-facing function name in
`metadata.bridge.function` (`ToolEvent.function` stays the bridged tool
name). A call that denotes several indistinguishable
bridged tools has a grant for each, so it can run more than once; one of
those events takes the proposing id and the rest get fresh ids, since
`ToolEvent.id` is what ACP cards, the viewer's approval and navigation maps,
`sample cancel-tool-call` and `InterruptEvent` key on. Every event that
consumed a grant records the proposing id in `metadata.bridge.proposal_id`,
which is the field to join on; which request takes the id is
`_execute_granted()`'s order.

A `_Proposal` is referenced only by its grants, so pairing state lives in the
bounded grant store (1024 entries) and is dropped with the last of its grants,
consumed or evicted. A later proposal that reuses a call id is a new
`_Proposal`. Grants, and so pairings, are not carried across a checkpoint
restore.

Grants are stored for servers registered with `require_proposal=False` too,
only so that a proposed call on them pairs; their calls execute with or
without one (decision: Ransom, 2026-09-15). They share the store, and the
eviction warning says what an evicted grant loses: for an exempt server the
pairing, for any other the right to execute. Either way the evicted grant's
reply no longer links any of its calls (see `message_id` below). An unproposed call on an
exempt server with the same arguments as a pending proposal takes that
proposal's grant and id, and the proposed call then runs with a fresh id and
`grant: "exempt"`. Execution is unaffected; the user docs state this
limitation (decision: Ransom, 2026-10-14).

The proposal is the call in the response handed to the agent. When a
bridge `filter` or `response_filter` edits or replaces that response, the
logged `ModelEvent` may not hold the call, or there may be none; the host
event still carries the id the agent saw, and consumers that pair by id find
no proposal for it. Filters own that divergence; the bridge records what the
agent ran. Which filter paths log a `ModelEvent` is `bridge_generate()`'s.

Pairing inherits the grant matching, so it is exact for every agent whose
proposals match at all. Two proposals in flight for the same tool with the
same arguments are consumed oldest first, so if the agent runs them in the
other order their ids are swapped between two otherwise identical events.

### `metadata["bridge"]`

```json
"metadata": {
  "bridge": {
    "server": "calc",
    "tool": "calculator_add",
    "function": "mcp__calc__calculator_add",
    "proposal_id": "toolu_01",
    "grant": "consumed"
  }
}
```

- `server`, `tool`: the `BridgedToolsSpec` name and the tool name within it.
  `ToolEvent.function` is always the tool name, so a scanner or dataframe sees
  one spelling per host tool.
- `function`: the name the proposing call used, which agents rewrite
  (`mcp__calc__calculator_add`, `calc_calculator_add`, Antigravity's
  dispatcher `call_mcp_tool`); `null` without a proposal. For a dispatcher
  call the event's `arguments` are the inner arguments that ran, which is
  what the grant binds.
- `proposal_id`: the proposing call's id on every consumed grant, else `null`.
- `grant`: `"consumed"`, `"denied"`, `"exempt"` (an exempt server ran it
  without a matching proposal), or `null` for a request rejected before the
  grant check (unknown server or tool, arguments too deep).

`metadata` is an open object in the log schema and the generated TypeScript
types, so the key needs no type generation.

## Placement

A paired execution is recorded under the span captured for its proposal
(see Capture), or else under the span current in the service task. In the
ordinary case that is the span of the `ModelEvent` that proposed the call,
so the host
`ToolEvent` sits at the same level as that event and as the later
`ModelEvent` whose input carries its result. The viewer's per-level rules
(below) and Messages-tab navigation depend on this; a host event one level
above a sub-agent's proposal and result would pair with neither, and ACP
filters a sub-agent's cards by the host event's span.

Capture covers only the bridge's default generation, so when a filter
supplies or replaces the response, the host event can sit at a different
level from the `ModelEvent` that generated its calls (see
`bridge_generate()`).

- **Capture.** When the bridge has a `ModelEventSink`, `bridge_generate()`
  wraps it around the default generation in `_SpanCapturingSink` (or
  `_StartingSpanCapturingSink` for a sink with `on_start`), which captures
  the span the sink recorded the `ModelEvent` in when the sink moved it to
  another span, and `None` when it did not; the exact comparison is in those
  classes. Without a sink nothing is wrapped (installing a sink disables
  partial-output publishing), and the `ModelEvent` is in the current span.
- **Apply.** `execute_host_tool()` runs the execution under
  `parent_span(proposal.span_id)` (`util/_span.py`), which sets the current
  span id for the block without emitting span events, so the event and its
  `tool` span take that parent. With `None` the event follows the span
  current in the service task: the agent span, or the checkpointer's current
  `checkpoint N` span. Storing only a span a sink chose keeps executions under
  the rotating checkpoint span when no sink moved the generation.
- **Unpaired requests, and requests rejected before a grant is consumed**
  (unknown server or tool, arguments too deep, denials), are recorded under
  the span current in the service task. A proposed call whose arguments then
  fail the schema is recorded under its proposal's span, and takes the
  proposing id by the same rule as an execution.
- **Sinks.** The sink protocol is not widened; the wrapper reads the span the
  sink assigned, so a sink must assign it by the time `on_complete` returns.
  The two known sinks (inspect_swe's Claude Code and Codex CLI event
  consumers) stamp sub-agent spans in `on_pending` and close them after the
  sub-agent has finished, so a sub-agent's host calls run while its span is
  open. A call that runs after the span closed is still recorded with that
  span's id; the Python and viewer event trees nest by `span_id`, so it lands
  in its proposal's span node, and only the stream order shows it after the
  `span_end`.

## Outcomes

| Request | `id` | `grant` | Event `error` / `failed` | Agent receives |
|---|---|---|---|---|
| Unknown server or tool | fresh | `null` | `parsing` | the `ValueError` text |
| Arguments over 100 levels deep | fresh | `null` | `parsing` (native depth message) | `ToolParsingError` |
| No matching proposal, server requires one | fresh | `denied` | `permission` | `PermissionError` |
| Proposed; arguments fail the schema | proposing, or fresh (see Pairing) | `consumed` | `parsing` | `ToolParsingError` |
| Exempt, unproposed; arguments fail the schema | fresh | `exempt` | `parsing` | `ToolParsingError` |
| Executed | proposing, or fresh (see Pairing), or fresh on an exempt server | `consumed` / `exempt` | none | the result, truncated as native |
| Tool raised an error a native call maps (`tool_call_error()`) | as executed | as executed | the mapped error; its result truncated | the original exception's text |
| Tool raised `LimitExceededError` | as executed | as executed | `limit` | `ToolError` with the mapped message |
| Decisive exception is a termination (bare or a group leaf), or unmapped with a termination in its history | as executed | as executed | `failed` | `Terminating: ...`; the sample ends |
| Decisive exception is mapped (an error or a limit), with a termination in its cause or context | as executed | as executed | the mapped error | `Terminating: ...`; the sample ends |
| Tool raised an unexpected exception | as executed | as executed | `failed` | the original text; the sample fails |
| Operator cancel | as executed | as executed | `timeout` | `ToolError("Command timed out before completing.")` |
| Outer cancellation (bridge teardown, sample limit) that escapes the tool | as executed | as executed | `cancelled` | nothing (the request is abandoned) |
| Outer cancellation the tool catches | as executed | as executed | as for what the tool then returns or raises | the reply, if teardown lets it go out |

The `permission` type is the one the native path gives a `PermissionError`
from a tool, and it renders in the viewer, which hides `approval` errors on
the assumption that a paired `ApprovalEvent` explains them; a denial has
none. It is also accurate: the agent has no permission to run a call the
model did not make (decision: Ransom, 2026-09-15).

## Errors, limits and cancellation

An exception from the tool, or from building the reply, is reduced to its
decisive leaf (`decisive_tool_exception()`) and classified with
`tool_call_error()`, the definitions `execute_tools()` uses:

- **Mapped error** (one the model would see natively as a `ToolCallError`):
  the event records the mapped error and its result (a timeout's partial
  output, truncated like any result). The original exception propagates, so
  the agent reads its own text: a `TimeoutError("tool-specific timeout")`
  reaches it as that string while the event shows the native "Command timed
  out before completing." (A termination in its history changes the reply;
  see Termination.)
- **Limit.** A `LimitExceededError` that decides the outcome, bare or as a
  group's decisive leaf, is recorded as the mapped `limit` error and raised as
  a `ToolError` with the same message (chained from the original). It does not
  reach the service dispatcher's limit branch, which would end the sample, so
  the agent's model reads it as a tool error and the agent continues, as
  natively. A sample-level limit is then enforced at the agent's next bridged
  generation, which records it for `sandbox_agent_bridge()` to raise once the
  agent has unwound. A limit with a termination in its history propagates
  unchanged, as a termination (below) (decision: Ransom, with Charles,
  2026-10-27).
- **Termination.** The event and the propagation are decided separately.
  The event is classified by the decisive leaf alone, which looks at group
  leaves, not causes or context. A termination that is the exception itself or
  a group leaf is unmapped, and so is an unexpected exception raised from one;
  either is recorded as `failed=True` with no error and is not passed to
  `bridge.request_fail()`. A mapped exception (a `ToolError`, a
  limit) whose cause or context holds a termination keeps its mapped event.
  Propagation is sticky unless the operator cancelled the call (whose
  timeout takes precedence; see Cancellation): whenever `find_control_flow()` finds a
  termination
  anywhere in the exception's history, the original exception propagates
  unchanged (a limit is not replaced by a `ToolError`), and the dispatcher
  replies `Terminating: ...` and raises the termination out of the service
  task, which ends the sample.
- **Unexpected exception** (unmapped, and no termination in its history):
  recorded as `failed=True` with no error, the native shape, and the decisive exception is passed to
  `bridge.request_fail()`, whose monitor task raises it in the bridge's task
  group so the sample fails as it would natively. The original still
  propagates so the RPC unwinds; the teardown may pre-empt the reply. The
  message reaches the log as the sample error, not on the event.

Cancellation:

- **Operator cancel.** `event._set_cancel_fn(scope.cancel)` makes the pending
  event cancellable from the TUI, `sample cancel-tool-call` and ACP's
  `inspect/cancel_tool_call`. A cancelled call is recorded as the native
  `timeout` error and the agent receives `ToolError` with the native
  message, whatever the tool did after the cancel.
- **Outer cancellation** (bridge teardown, a sample limit) that escapes the
  tool is recorded as `cancelled` ("Host tool call was cancelled before
  completing.") and propagates; the request gets no reply. A tool that
  catches it is recorded by what it then does (`_execute_granted()`).
- **ACP turn cancel.** The event is registered with the execution observer
  (`track_tool_call`), so `cancel_current_turn` marks it cancelled and failed
  and records an `InterruptEvent`; `_set_result()` keeps that marker
  when the call later finalises. It does not fire the per-call scope: the
  tool runs on unless ACP's interrupt of a bound agent channel cancels a turn
  scope that encloses the bridge. Hooks and ACP see two non-pending updates,
  as for a native tool.

Grant consumption mutates the store on the event-loop thread with no `await`
between match and delete, so concurrent requests need no lock.

## Results

The result is recorded as content
(`ContentText`, `ContentImage` and the other content types, or a list of
them) as a list; anything else as text, a `str` verbatim and other values as
`to_json_str_safe()`. Text is truncated by `truncate_tool_output()` at the
tool's `ToolDef.max_output`, else the eval's `max_tool_output`, else 16 KiB,
with the native wrapper text and `truncated=(raw_bytes, limit)`; content is
not truncated. The agent receives exactly the recorded text. A single image,
or a list of only text and images that holds an image, is sent as MCP content
blocks: an image given as a data URI becomes an image block, an image given as
a URL or file path becomes a text block holding that source, and text stays
text. Any other content (text alone, or a list that also holds audio, video or
documents) is sent as its JSON serialization in text.

Output truncation follows the native limit, including its 16 KiB default
(confirmed by Ransom, 2026-10-07). This replaces the 2026-09-15 decision to
apply only explicitly configured limits.

Log condensation walks a tool event's arguments (long strings become
attachments) and the media in its result (`walk_tool_result()`), so
data-URI images in a transcript tool event's result, native or host, follow
`log_images` as message images do; results of legacy nested events
(`ToolEvent.events`) stay inline. Text results stay inline: the same text is already inline in the tool
message the model sees next.

`message_id` is the id of the tool message holding the result when the link
is exact, and `None` otherwise. The agent builds that `ChatMessageTool` itself
and sends it in a later request, so its id does not exist when the event is
finalised. The bridge waits for it (`_await_result_message()`) and sets
`message_id` when the request arrives (`_link_result_messages()`), updating
the completed event through the transcript's event-update path
(`_event_updated()`), as for a pending event. Transcript subscribers see the
event completed with `message_id=None` and then updated; a log read back has
it set.

The link is exact when all of these hold:

- The reply holding the call is placed under the id the bridge handed it
  with (`_align_with_tracked()`), and no message the bridge could not place
  took that id first.
- The bridge has complete evidence of the reply's executions: it handed the
  reply out once, and it neither dropped the reply's awaited calls (it tracks
  at most 256, dropping the oldest replies' first) nor evicted one of its
  grants. A reply handed out again (a cached generation or retry, also after
  a checkpoint resume, since the checkpoint keeps the ids the bridge knows)
  may have its calls run once per hand-out, and executions the bridge no
  longer tracks can't be told apart from the one it does. The bridge records
  each such reply's id in `_unlinked_replies` (ids only, for the rest of the
  sample; `_unlink()`, or directly when it drops awaited calls), and none of
  the reply's calls links again, including one first executed after the
  drop.
- The grant it consumed is not for a server registered with
  `require_proposal=False`: there an unproposed call with a pending
  proposal's arguments takes that proposal's grant, so the grant does not
  show which call ran.
- The call ran once, its id is unique in the reply, and no other call in the
  reply has its function and arguments.
- Its execution matched no other reply's pending grant, exactly or once
  undeclared arguments are dropped. `consume_tool_execution_grant()` marks
  every proposal the execution could belong to `ambiguous` and unlinks its
  reply, so none of them links, including an execution of theirs that
  completed before the ambiguity was found.
- No other request may have repeated the call while its answer was
  outstanding. A client that lost a response sends the call again, and the
  agent may send that attempt's result as the call's answer. Calls are
  compared by (server, tool) and arguments, as grants compare them (also
  projected onto a closed schema's declared keys). The check runs when an
  execution consumes a grant (`_record_execution()`), before it starts, and
  when a request is denied:
  - The proposal's second execution (one call granted for several tools)
    unlinks its reply.
  - An execution of a call whose earlier execution under another reply is
    still running or awaiting its answer may be that call's retry, taking
    the later reply's identical grant: both replies are unlinked. An earlier
    execution already settled (its answer linked, or left unlinked) is final,
    so ordinary repeated calls whose answers arrived in between keep their
    links.
  - A grant is one-shot, so a retry with no other grant to take is denied,
    and the agent may send the denial as the answer. `unlink_denied_call()`
    unlinks the reply of every recorded or pending call it may repeat, or of
    every call of the tool when the arguments can't be read (not an object,
    or nested too deep). A request naming no bridged tool repeats no
    proposal.

  The record holds reply ids, positions and argument hashes only, and each
  entry is dropped once it is scanned or unlinked, so the work is amortized
  constant per execution.
- Exactly one tool message answers it, by call id, before the next assistant
  message with tool calls, and that message is new in the request: one sent
  before, or equal to one sent before, may hold another result.

Otherwise `message_id` stays `None`. This includes a Google result whose call
id the dialect inferred from order (a call sharing its function with another),
a call of a reply whose awaited calls were dropped, and a call proposed before
a checkpoint resume.

Lost-grant cross-proposal limitation. Once a reply's grant is evicted (1024
unconsumed grants), matching no longer knows that reply. If a later reply
proposes the identical call, an execution of the first reply's call takes the
later reply's grant without ambiguity, so its event pairs with the later
proposal (`proposal_id`, id and span) although it ran the earlier call. The
link is still left unset when the later reply's own call is sent: it is
denied, which unlinks the later reply, or it takes another identical grant
while the execution paired with the later reply awaits its answer, which
unlinks both. A wrong link would need the agent to answer the later call
without sending it to the bridge (reusing the earlier result, say). Not
handled further: it needs 1024 unconsumed grants and an identical later
proposal, and fixing the pairing would mean keeping evicted grants.

`agent` is `None`; `agent_span_id` is the tool's, as natively.

## Consumers

- **ACP.** `_map_tool_event()` pops the call from `_BridgeToolState.pending`,
  so the card synthesized for the proposal is updated with the real result
  and is not settled again from the agent's `ChatMessageTool`; the update
  also marks the card cancelable. An event of a multi-target proposal that
  did not take the proposing id, and an unpaired call on an exempt server,
  carry fresh ids and map as their own cards. Replay synthesizes no card for an id that has a real
  `ToolEvent`. The sub-agent filter places an event by its `span_id` as well
  as by span order, so a host call recorded in a sub-agent span that has
  already closed stays filtered, live and on replay.
- **Viewer.** A host event renders as a native tool panel, with any
  `ApprovalEvent` whose `call.id` matches. The model-event rules that hide
  tool calls and tool-role messages a tool event already shows are keyed per
  call id at the event's level (`computeToolEventIdsAtLevel()`): an assistant
  tool call is left out of the model panel, and a tool-role message hidden,
  only when a tool event with that id is a sibling. In a bridged turn mixing
  host and agent-run calls, the agent-run calls and their results still show.
  Native transcripts are unaffected, since every native call has its tool
  event at that level.
- **Approval.** Approval runs at proposal time in `bridge_generate()`, before
  grants are minted, and reviews each call under the bridged tool it denotes,
  whatever name the agent declared, through the same resolution the grants
  use (`reviewed_calls()`); a call denoting several bridged tools is approved
  separately for each, and the resulting `ApprovalEvent`s carry the proposing
  id. See
  [Bridged Agents](../docs/approval.qmd#bridged-agents).
- **Sentinel.** The host executor runs no sentinel tool stage, so sentinel
  replay rebuilds none for a `ToolEvent` with `metadata["bridge"]`.
- **Hooks, control server, TUI, dataframes.** Pending host events drive the
  TUI's running state and the control server's activity and cancellation like
  native ones. Hooks receive each non-pending update. `events_df()` has `tool`
  rows for host calls, but not for the agent's own tools.

## Decisions

- 2026-09-15: arguments that are not an object or nest deeper than the native
  bound never execute: over-deep ones are rejected before the grant check, so
  unbounded nesting cannot reach the log (decision: Ransom, 2026-09-15).
- 2026-09-15: a denial is recorded as `ToolCallError("permission", ...)`
  (decision: Ransom, 2026-09-15).
- 2026-09-15: grants are stored for `require_proposal=False` servers, so their
  proposed calls still pair (decision: Ransom, 2026-09-15).
- 2026-10-07: host tool results follow the native output limit, including its
  16 KiB default; schema validation runs after the grant check, so an
  unproposed call with invalid arguments is denied and a proposed one pairs
  with its proposal; ACP's sub-agent filter also places events by `span_id`
  (confirmed: Ransom, 2026-10-07).
- 2026-10-14: on an exempt server, pairing is first come, first served; the
  limitation is documented and the matching is unchanged (decision: Ransom,
  2026-10-14).
- 2026-10-27: a limit raised in a host tool is a tool error, as natively, and
  does not end the sample; a termination in its history still does
  (decision: Ransom, with Charles, 2026-10-27).

## Alternatives considered

- **A new event type.** Every consumer (viewer, ACP, TUI, control server,
  dataframes, hooks, scanners) would need new handling, and none could pair
  it with proposals and approvals the way they pair `ToolEvent`s.
- **Annotating the proposing `ModelEvent`.** No record for denied or
  unproposed calls, no timing or pending state, and a second update of a
  completed event re-delivers it to hooks.
- **Emitting the event through `ModelEventSink`.** Widens a protocol whose
  implementers live outside this repo; reading the span the sink assigned
  through a private wrapper gives the same placement.
- **Recording every event under the service task's span.** No capture needed,
  but a sub-agent's host call would sit a level above its proposal and
  result, where the viewer's per-level rules cannot see it.
- **Synthesizing the event when the agent's tool result comes back**, as ACP
  does for agent-run tools. Covers only proposed calls whose result returns,
  records the agent's rendering of the result rather than the execution, and
  misses denials.
- **Recording deep arguments and executing anyway.** Either records something
  other than what ran or admits unbounded nesting into the log.

## Compatibility

- **Logs.** No schema change. Bridged samples that call host tools have
  `tool` events and `tool` spans. Data-URI images in a transcript tool
  event's result are stored as attachments (`log_images=True`) or removed (`log_images=False`);
  URL and file-path image sources stay inline. An older Inspect reading such
  a log shows the `attachment://` reference in the result.
- **Agent-facing behaviour.** Compared with a bridge that did not record
  events: arguments over 100 levels deep are rejected with the native depth
  error, text results are truncated at the native limit, and a limit raised
  in a host tool is a tool error rather than the end of the sample. Error
  text for other failures is unchanged.
- **API.** `register_tool_execution_grants()` takes a keyword `span_id` on the
  base `AgentBridge` hook, which `bridge_generate()` always passes, so an
  `AgentBridge` subclass overriding the hook must accept it.
  `consume_tool_execution_grant()` returns the grant or `None`.
- **Checkpointing.** Events are restored like any others. A checkpoint taken
  while a host call is pending keeps a pending event that resume never
  completes, as for a native tool. Grants are not restored, so a proposal
  made before a checkpoint does not pair after resume and, on a server that
  requires proposals, its call is denied. Its result is not linked
  (`message_id` stays `None`).

## Security

The untrusted input is the agent's `tools/call`: `server`, `tool` and
`arguments`, all controlled from the sandbox.

- `server` and `tool` are looked up in the host registry before use; an
  unknown name is recorded as sent, in `function` and in the error message,
  as it already appears in the RPC error.
- `arguments` are recorded as received. Size is bounded by the proxy's 50 MiB
  request body cap and the service's 150 MiB request read limit, the same
  bounds on what the agent can put in `ModelEvent` inputs; long strings are
  condensed into attachments. Nesting is bounded by the depth check, before
  anything else reads the arguments.
- `result` comes from the host tool (trusted code), bounded by the output
  limit for text and by `log_images` for media. Error messages on the event
  are the ones the agent already receives or the native mapped wording;
  tracebacks stay host-side.
- Nothing recorded flows back to the sandbox, and recording happens after the
  grant decision, so it cannot influence which calls run.

## Not this design

- **Tool result review for host tools.** `review` policies (`Task(review=)`,
  `eval(review=)`, `react(review=)`) run after a native tool and before the
  model sees its result; the bridge runs none, so host calls have no
  `ReviewEvent`. Covering them means running reviewers in
  `execute_host_tool()` before the reply and deciding what `terminate` and
  `escalate` mean over the RPC.
- **Parity with native argument handling**: `tool_params()` conversion of
  arguments and `ToolDef.viewer` for the event's `view` (the view is the
  proposing call's).
- **Native error wording on the wire.** A mapped exception reaches the agent
  as its own text, not the `ToolCallError` wording the event records.
- **Grants and proposals across checkpoint restore** (registering the grant
  store with the checkpointer).
- **A viewer badge** for `metadata.bridge` (host execution, denied, exempt) on
  the tool panel.
- **A closed-span fallback**: tracking `SpanEndEvent`s so an execution whose
  proposal's span has closed is placed under the current span instead. Not
  needed for the known sinks, and both event trees nest by `span_id`.
- **Agent-run tool calls** stay without `ToolEvent`s.
