# Record bridged host tool executions as `ToolEvent`s

Status: proposed, 2026-09-15. Issue: none (task from Ransom). Author: agent
(Claude), reviewed by Codex; see the PR.

All `path:line` references are to `main` at `ba590d512` unless a different
tree is named. Viewer references are to the `ts-mono` submodule at the commit
that tree pins (`02f2c5ad`), under `src/inspect_ai/_view/ts-mono/`.

## Why

`sandbox_agent_bridge(bridged_tools=...)` exposes host-side Inspect tools to
a sandboxed scaffold as MCP servers on the in-container model proxy. A
`tools/call` from the scaffold becomes a `call_tool` request in the bridge's
sandbox service, and the host runs the tool function in the Inspect process
(`src/inspect_ai/agent/_bridge/sandbox/service.py:219-265`). Since #4944,
when an approval policy is active the call must consume a one-shot execution
grant minted from an approved generation
(`src/inspect_ai/agent/_bridge/sandbox/types.py:91-159`).

Nothing on this path writes a transcript event. The only trace of a host
tool execution is the `ModelEvent` of the generation that proposed it, if
one did; a denied call leaves a `warn_once` in the Python log and nothing in
the transcript (`service.py:237-244`). `in_bridge_model_generate()`
documents that bridged scaffolds emit no `ToolEvent` because they run their
own tools (`src/inspect_ai/agent/_bridge/util.py:365-369`). That reasoning
does not cover a tool Inspect itself executes on the host.

Host tool executions are actions Inspect takes on the sample's behalf. The
native path records every executed call, including rejected and failed
ones, as a `ToolEvent` (`src/inspect_ai/model/_call_tools.py:334-343`,
`:424-430`). The bridge path should record the same, so that the eval log,
the viewer, ACP clients, dataframes and scanners see what the host did and
when.

## Goals and non-goals

Goals:

- Every `call_tool` request produces exactly one `ToolEvent` in the sample
  transcript: executed, denied, or rejected (unknown server or tool, bad
  arguments).
- An executed call carries the function name as the model saw it, the
  bridged server and tool, the arguments as executed, the result as
  delivered to the scaffold (or the error), start and completion times,
  working time, and a marker that it ran on the host through the bridge.
- An executed call that matches a recorded model proposal carries the
  proposing `ToolCall.id`, so consumers pair it with the proposal the way
  they pair native `ToolEvent`s. A denied or unproposed call gets a fresh id
  and an error.
- The event behaves like a native `ToolEvent` for live surfaces: pending
  while running, cancellable by the operator, visible to the execution
  observer.
- No change to what the scaffold receives (results, error text, denial
  behaviour) and no change to the approval or grant decision.

Non-goals:

- Recording the scaffold's own tool executions (Bash, Read, Edit run inside
  the sandbox). Those remain visible only through `ModelEvent` inputs.
- Making execution grants unconditional (denying unproposed calls without an
  approval policy). See "Not this design".
- Argument validation, dataclass coercion, `max_tool_output` truncation, or
  `ToolDef.viewer` support for bridged host tools. The bridge path calls
  `tool_fn(**arguments)` directly today and keeps doing so.
- A new event type or a new `ToolEvent` field.

## Current behaviour

### The call path

- The scaffold's MCP client posts `tools/call` to the in-container proxy,
  which forwards `server`, `tool` and `arguments` to the host service
  (`src/inspect_sandbox_tools/src/inspect_sandbox_tools/_agent_bridge/proxy.py:2170-2183`).
  MCP `tools/call` carries no model tool-call id, so the host cannot learn
  the proposing call's id from the request; pairing has to come from state
  the host recorded when it handed the proposal to the scaffold.
- The sandbox service runs each request in its own task
  (`src/inspect_ai/util/_sandbox/service.py:397`). That task inherits a copy
  of the context the bridge's task group was started in
  (`src/inspect_ai/agent/_bridge/sandbox/bridge.py:205-213`): the sample
  transcript, the active sample, the sample timing object, and the span
  current when the bridge was entered (the agent span, or the checkpointer's
  shared `_SpanCell`). Verified by a spike that spawned a task inside a span
  and emitted a `ToolEvent` from it: the task's `current_span_id()` was the
  agent span and `in_bridge_model_generate()` was `False` there.
- `call_tool` (`service.py:219-265`) checks the server (`:227`) and tool
  (`:231`), then denies unless no approval is active or a grant matches
  (`:234-244`), raising `PermissionError("... was not approved for
  execution")`. It then awaits `tool_fn(**arguments)` (`:247`) and returns a
  plain string verbatim, MCP content blocks for image results, or
  `to_json_str_safe(result)` otherwise (`:253-263`).
- Any exception becomes an RPC error string `Error calling method call_tool:
  <message>` (`util/_sandbox/service.py:562-581`; tracebacks are deliberately
  kept host-side), which the proxy returns as JSON-RPC error `-32603`
  (`proxy.py:2192-2195`). `LimitExceededError` is special-cased: the service
  calls `active.limit_exceeded(ex)` and answers an error
  (`util/_sandbox/service.py:552-560`).

### Grants

- `_ToolExecutionGrant(server, tool, arguments)` (`types.py:201-211`) is
  minted per approved call in `register_tool_execution_grants`
  (`types.py:91-139`), called from `bridge_generate` after approval and
  before the response is returned to the scaffold (`util.py:600-604`). The
  method returns early when no approval policy is active (`types.py:107`),
  so with the default configuration nothing is recorded about proposals.
- `consume_tool_execution_grant` returns a `bool` (`types.py:141-159`).
- The grant deque is bounded at 1024 entries (`types.py:33`, `:76-78`) and
  is not registered with the checkpointer, so grants do not survive a
  checkpoint restore.

### Native `ToolEvent` mechanics the design mirrors

- Two-phase emission: a pending event is created per call
  (`_call_tools.py:424-430`), recorded inside `span(name=call.function,
  type="tool")` (`:789-790`; denials at `:728-731`), then finalised with
  `_set_result` and `transcript()._event_updated(event)` (`:504-518`).
- `ToolEvent._set_result` computes `completed` and `working_time = wall −
  waiting_time` (`src/inspect_ai/event/_tool.py:70-115`); the caller
  measures waiting time from `sample_waiting_time()` before and after
  (`_call_tools.py:423`, `:503`).
- Exceptions from the tool body map to `ToolCallError` types
  (`_call_tools.py:220-284`): timeout, unicode_decode, parsing (embedded
  null byte), sandbox_unavailable, permission, file_not_found,
  is_a_directory, limit, parsing, approval, unknown (`ToolError`). Anything
  else sets `failed=True` and propagates.
- A per-call cancel scope is exposed through `event._set_cancel_fn`
  (`:492`); operator cancel records `ToolCallError("timeout", "Command
  timed out before completing.")` (`:549-556`).
- The execution observer is told about the in-flight call
  (`:201`, `:359`), which is how ACP's turn cancel finds and marks it.
- `BaseEvent` supplies `uuid`, `span_id` (from `current_span_id()` at
  construction), `timestamp`, `working_start` and a free-form `metadata`
  dict (`src/inspect_ai/event/_base.py:20-48`).

### Consumers that today assume "bridged means no `ToolEvent`"

- ACP live mapping synthesises tool cards from bridged `ModelEvent`s, gated
  on `in_bridge_model_generate()`
  (`src/inspect_ai/agent/_acp/event_mapping.py:560-562`, `:715`), remembers
  them in `_BridgeToolState.pending` (`:109-135`, `:978-979`) and settles
  them from `ChatMessageTool`s in a later input (`:891-930`). A real
  `ToolEvent` whose id was already seen is mapped as an update, not a new
  card (`:817-856`); the synthesised start is marked non-cancelable
  (`:956`). Replay pre-scans the snapshot and never synthesises a call that
  has a real `ToolEvent` (`:137-165`, `:1019`).
- `ModelEventSink` (`src/inspect_ai/model/_model.py:2860-2898`) lets a
  caller take over `ModelEvent` emission (`:1976-1980`, `:2033`). ACP does
  not install one: it subscribes to the transcript
  (`event_mapping.py:294`). The only implementer in the Inspect ecosystem is
  inspect_swe's claude_code `LiveConsumer`
  (`src/inspect_swe/_claude_code/_events/live_consumer.py:89`, inspect_swe
  `b2c1bf0`), which stamps `event.span_id` at `on_pending` to attribute
  sub-agent generations to `agent-<tool_use_id>` spans and emits the event
  itself. It does not emit `ToolEvent`s during a live run (the JSONL
  `ToolEvent` builder in `_events/events.py` is not called from
  `claude_code.py`).
- The viewer decides per model event whether to render the assistant's tool
  calls inline (`packages/inspect-components/src/transcript/TranscriptVirtualList.tsx:127`:
  omit them when the next node is a tool event) and whether tool-role input
  messages are shown under the model call
  (`transcript/recentInputMessages.ts:39`) or collapsed
  (`transcript/ModelEventView.tsx:217`, `:273`), keyed on
  `hasToolEvents`, a per-depth backward scan for any tool event
  (`transcript/hasToolEventsAtDepth.ts:25`). Approvals pair to tool events by
  `call.id == ToolEvent.id` (`transcript/transform/toolApprovals.ts:44`);
  today a non-auto approval of a bridged call renders as a flat row because
  no tool event carries that id. `ToolEventView` hides `error.type ==
  "approval"` (`transcript/ToolEventView.tsx:106`) on the assumption that
  the paired approval panel explains it, and shows a running indicator while
  `pending` (`:179`).
- Pending `ToolEvent`s drive the textual TUI's "Executing…" state and
  timeout button (`src/inspect_ai/_display/textual/widgets/samples.py:1086`),
  the control server's sample activity (`src/inspect_ai/_control/state.py:1213`)
  and `sample cancel-tool-call`, which errors when a pending match has no
  cancel hook (`src/inspect_ai/_control/cancel.py:1002`, `:1074`).
- Hooks receive non-pending events only (`src/inspect_ai/hooks/_hooks.py:757`).
- Dataframes: `events_df` exposes `ToolEventColumns` and `EventTiming`
  (`src/inspect_ai/analysis/_dataframe/events/columns.py:54-60`, `:79-87`).
  Bridged samples currently yield no `tool` rows.
- Condensation walks `ToolEvent.arguments` and nested `events` but not
  `result` (`src/inspect_ai/log/_condense.py:936-944`); text over 100
  characters in walked fields becomes an attachment (`:434`). Verified by
  running `condense_sample` on a `ToolEvent` with a 5000-character argument
  and result: the argument became an attachment, the result (string, and a
  list with a `ContentImage`) stayed inline.

## Design

### Overview

`call_tool` keeps its contract with the proxy (same results, same error
strings, same denial) and gains one responsibility: record a `ToolEvent` for
the request. The event is emitted directly to the sample transcript from the
service task, inside a `tool` span, using the native two-phase pattern.
Pairing with the proposing model call comes from the grant record, which is
extended to hold the proposing `ToolCall` and is now written whether or not
an approval policy is active (the denial decision is unchanged).

```
scaffold ──tools/call──▶ proxy ──call_tool RPC──▶ service task
                                                  │ resolve server/tool, check arguments
                                                  │ record = consume_tool_execution_grant(...)
                                                  │ deny if approval active and record is None
                                                  │ ToolEvent(id = record.call.id | fresh, pending)
                                                  │   span(type="tool") ─▶ transcript()._event
                                                  │   CancelScope + observer.track_tool_call
                                                  │   result = await tool_fn(**arguments)
                                                  │ event._set_result(...); _event_updated
                                                  ▼ return serialized result / raise as today
```

### Grant record carries the proposal

`src/inspect_ai/agent/_bridge/sandbox/types.py`:

```python
class _ToolExecutionGrant(NamedTuple):
    server: str
    tool: str
    arguments: dict[str, Any]
    call: ToolCall
    """The proposing model tool call (id, function as the model saw it, view)."""
```

- `register_tool_execution_grants(calls)` drops the early return at
  `types.py:107` and records a grant for every approved (or, without a
  policy, every returned) call that resolves to exactly one bridged tool.
  The record is what lets an execution be attributed to its proposal; the
  denial decision stays where it is (below). The ambiguity and eviction
  warnings (`types.py:114-123`, `:124-131`) are reworded so they do not say
  "the call will be denied" when no policy is active ("no execution grant
  registered; under an approval policy the call is denied, otherwise it
  executes unpaired").
- `consume_tool_execution_grant(server, tool, arguments) ->
  _ToolExecutionGrant | None` returns the matched record instead of `bool`.
  Matching is unchanged (`_json_equal`, one-shot, oldest first).
- The deque stays bounded at `_MAX_TOOL_EXECUTION_GRANTS`. Without a policy
  the deque now fills for every host-tool proposal, so the eviction warning
  will fire for long runs whose scaffold proposes host calls it never
  executes; that is the existing bound doing its job.

Why record unconditionally: the default bridge configuration has no approval
policy. If pairing were available only under approval, the common case would
produce an unpaired event for every host call, and ACP live mode would show
two cards per call (the synthesised one from the `ModelEvent` and a fresh
one from the real event) with no id to reconcile them. Recording the
proposal costs one bounded deque entry and is exactly the substrate the
"unconditional grants" follow-up needs (see "Not this design").

### `call_tool` records one event per request

New module `src/inspect_ai/agent/_bridge/sandbox/host_tool.py`; `call_tool`
in `service.py` becomes a thin wrapper that delegates to it, so the RPC
method table (`service.py:107`) and the existing tests' import
(`tests/agent/test_bridge_approval.py:24`) are unchanged.

```python
async def execute_host_tool(
    bridge: SandboxAgentBridge,
    server: str,
    tool: str,
    arguments: dict[str, JsonValue],
) -> JsonValue:
```

Control flow, in order:

1. **Resolve.** Unknown server or tool: record a completed event with
   `error=ToolCallError("parsing", "Unknown tool '<tool>' in server
   '<server>'")` (the current `ValueError` text), fresh id,
   `function=tool`, then raise the same `ValueError` as today. This mirrors
   the native "Tool X not found" parsing error (`_call_tools.py:750`).
2. **Check arguments.** `arguments` must be a JSON object and must pass
   `_exceeds_max_depth` (`_call_tools.py:1364`, applied to provider-parsed
   arguments at `:742`). Otherwise record a `parsing` event with
   `arguments={}` and raise `ValueError`. Today such a call reaches
   `tool_fn(**arguments)` and fails with a `TypeError` or executes; the
   design bounds what enters the log rather than what the tool accepts.
3. **Match the proposal.** `grant = bridge.consume_tool_execution_grant(server,
   tool, arguments)`.
4. **Deny.** If `bridge.tool_approval_required()` and `grant is None`:
   record a completed event with fresh id, `function=tool`,
   `error=ToolCallError("permission", "Host tool call '<server>/<tool>' was
   not approved for execution")`, `failed=None`, and raise the same
   `PermissionError` as today (`service.py:242-244`), keeping the `warn_once`.
   `permission` is the type the native path assigns to a `PermissionError`
   raised by a tool body (`_call_tools.py:248-250`) and it renders in the
   viewer, which suppresses `approval`-typed errors expecting a paired
   `ApprovalEvent` that a denial does not have (no approver ran).
5. **Execute.** Build the pending event and run the tool:

   ```python
   event = ToolEvent(
       id=grant.call.id if grant else uuid(),          # shortuuid, as for event uuids
       function=grant.call.function if grant else tool,
       arguments=arguments,                            # as executed
       view=grant.call.view if grant else None,
       pending=True,
       metadata={"bridge": {...}},                     # see below
   )
   waiting_start = sample_waiting_time()
   async with span(name=event.function, type="tool"):
       transcript()._event(event)
       with observer.track_tool_call(event.id, event):
           with anyio.CancelScope() as scope:
               event._set_cancel_fn(scope.cancel)
               try:
                   result = await tool_fn(**arguments)
               except LimitExceededError: ...          # record "limit", re-raise
               except anyio.get_cancelled_exc_class(): ...  # record "cancelled", re-raise
               except Exception as ex: ...             # native mapping, see below
       if scope.cancel_called: ...                     # operator cancel: "timeout"
   ```

   `observer` is `sample_active().execution_observer` or the null observer,
   as in `_call_tools.py:189-196`.
6. **Finalise.** `event._set_result(result=<recorded result>, truncated=None,
   error=<mapped error>, waiting_time=sample_waiting_time() - waiting_start,
   agent=None, failed=<see below>, message_id=None,
   agent_span_id=getattr(tool_fn, "agent_span_id", None))` then
   `transcript()._event_updated(event)`. Then return the serialized result
   exactly as `service.py:253-263` does today, or re-raise.

Single-shot events (steps 1, 2, 4) are constructed with `pending=None`,
finalised with `_set_result(..., waiting_time=0.0)` and recorded once with
`transcript()._event(event)` inside their own `tool` span, so every host tool
event, like every native one, sits in a `tool` span.

### The recorded result

`result` is the `ToolResult` the tool returned, massaged as the native path
does for the event (`_call_tools.py:284-333`): a `str` verbatim; a
`ContentImage`, or a list of `Content`, as the list; anything else as
`to_json_str_safe(result)`, which is the string the scaffold receives
(`service.py:263`). No truncation is applied (`truncated=None`): the bridge
delivers the full result to the scaffold today and the event records what
was delivered. Image content stays as `ContentImage` in the list, matching
native tool events.

### Error mapping

The exception-to-`ToolCallError` mapping at `_call_tools.py:220-284` is
extracted into a helper in `src/inspect_ai/model/_call_tools.py`:

```python
class ToolCallFailure(NamedTuple):
    error: ToolCallError
    result: ToolResult
    """Partial output to record (a timeout's truncated output, else "")."""

def tool_call_failure(ex: Exception, function: str) -> ToolCallFailure | None:
    """The `ToolCallError` the native path records for `ex`; None when the
    exception is not a tool failure and must propagate."""
```

The native `call_tool_task` calls it (behaviour-preserving refactor; the
`ValueError` re-raise for anything but an embedded null byte and the
`failed=True` path for unmapped exceptions stay in the caller). The host
path uses it as follows:

- Mapped failure: `error=failure.error`, `result=failure.result`,
  `failed=None`; raise `ToolError(failure.error.message)` so the scaffold's
  MCP error text is the message the log shows.
- `LimitExceededError`: record `ToolCallError("limit", ...)` via the helper,
  then re-raise the original exception so `_handle_request` still calls
  `active.limit_exceeded(ex)` (`util/_sandbox/service.py:552-560`).
- Unmapped exception: `error=ToolCallError("unknown", str(ex))`,
  `failed=True`, re-raise. The native path leaves `error=None` here because
  the exception goes on to fail the sample; over the bridge it does not (the
  service converts it to an RPC error, unchanged by this design), so the
  message is recorded on the event instead.
- Operator cancel (`scope.cancel_called`): `error=ToolCallError("timeout",
  "Command timed out before completing.")`, `failed=None`, the contract at
  `_call_tools.py:549-556`; raise `ToolError` with that message so the
  scaffold gets an MCP error rather than a hung request.
- Outer cancellation (bridge teardown, sample limit): record
  `ToolCallError("cancelled", "Host tool call was cancelled before
  completing.")`, `failed=None`, `_event_updated`, re-raise. `_set_result`
  and `_event_updated` are synchronous, so this runs safely inside the
  cancellation handler without shielding. Without it a bridge torn down
  mid-call would leave a forever-pending host event in the log.

### The host marker

No new field. `BaseEvent.metadata` (`_base.py:29`) carries:

```json
"metadata": {
  "bridge": {
    "server": "calc",
    "tool": "calculator_add",
    "proposed": true,
    "approval": "granted"
  }
}
```

- `server`, `tool`: the `BridgedToolsSpec` name and the tool name within it.
- `proposed`: whether a recorded model proposal matched (and so whether `id`
  is the proposing call's id).
- `approval`: `"granted"` (policy active, grant consumed), `"denied"`
  (policy active, no grant), `"not_required"` (no policy), or `null` for
  events recorded before the grant check (unknown tool, bad arguments).

`metadata` is already in the log schema and the generated TypeScript types
(`metadata?: {[key: string]: unknown} | null`), so no type generation is
needed (see `design/type-generation-pipeline.md`). The key is documented in
the `ToolEvent` docstring and in `docs/agent-bridge.qmd`.

### Where the event lands: span and sink

The event is emitted directly to the transcript from the service task, not
through `ModelEventSink`:

- Without a sink (every bridge except inspect_swe's claude_code), the
  bridge's `ModelEvent`s are also emitted from service tasks with the same
  inherited context, so the host `tool` span's parent is the same span the
  proposing `ModelEvent` has: the agent span, or the checkpointer's current
  `checkpoint N` span via the shared `_SpanCell`
  (`src/inspect_ai/util/_span.py:135-152`,
  `src/inspect_ai/util/_checkpoint/checkpointer_impl.py:293`).
- With claude_code's `LiveConsumer`, a sub-agent's `ModelEvent` is
  re-attributed to `agent-<tool_use_id>`, but the service task cannot know
  which sub-agent issued a `tools/call`, so a host tool event proposed by a
  sub-agent sits in the outer span while its `ModelEvent` sits in the
  sub-agent span. Pairing is by id, which every consumer uses, so approvals,
  ACP cards and message navigation still connect; only the swimlane
  placement differs. The sink stays a `ModelEvent`-only protocol. Widening
  it is listed under "Not this design" with what it would take.
- `use_model_event_sink` is not active in the `call_tool` task, so a host
  tool that itself calls a model records its `ModelEvent` directly under the
  tool span, which is where a native tool's nested generation goes.

### Nested events

A host tool that uses `sandbox()` produces `SandboxEvent`s from the same
task; their `span_id` is taken from `current_span_id()` at construction
(`_base.py:35-48`), which inside the `async with span(...)` block is the
host tool's span. They nest under the host tool event exactly as under a
native tool event. The viewer's timeline turns a `tool` span that contains
model events into a tool-spawned agent (`transcript/timeline/core.ts:989`),
the same classification a native tool that generates gets.

### Message linkage

`ToolEvent.message_id` is the id of the `ChatMessageTool` the model saw
(`_call_tools.py:512`). For a host call the scaffold builds that message
itself and sends it back in a later request, where `apply_message_ids`
assigns an id by content hash (`util.py:894-902`,
`src/inspect_ai/agent/_bridge/types.py:250-274`). That id does not exist
when the event is finalised, so `message_id` is `None`. Consumers cope: the
viewer's tool label lookup falls back to the tool id
(`transcript/ToolEventView.tsx:94-98`), and messages-tab navigation from a
tool-role message resolves through `tool_call_id`, not `message_id`
(`transcript/resolveMessageToEvent.ts:310-333`), so a paired host event is
now the navigation target. Back-filling `message_id` when the message
arrives would need a second `_event_updated` on a completed event, which
re-delivers it to hooks; that is left out (see "Not this design").

`agent` is `None` (bridged tools are not handoffs). `agent_span_id` mirrors
`_call_tools.py:794`.

### Working time and limits

- Sample-level `working_time` is `total_time − sample_waiting_time()`
  (`src/inspect_ai/_eval/task/run.py:3357`) and `working_limit` polls
  `sample_working_time()` (`src/inspect_ai/util/_limit.py:904-940`). Neither
  reads events. Host tool execution is wall-clock time not spent waiting on
  a semaphore, so it already counts as working time today. This design
  changes nothing at the sample level and `working_limit` behaviour does
  not shift.
- The `SampleTiming` object is set once per sample
  (`src/inspect_ai/_util/working.py:19-25`, `run.py:2625`) and shared by
  reference into every spawned task, so `working_start`, the waiting-time
  baseline and `working_time` measured in the service task are consistent
  with the sample's.
- What is new is per-call `working_time` and `completed` on host tool
  events, which `EventTiming` columns and the viewer's `Tool:` title expose.

### Concurrency and cancellation

- Each `tools/call` runs in its own service task and records its own event.
  Grant consumption mutates a deque on the single event loop thread with no
  `await` between match and delete (`types.py:151-158`); no lock is needed
  (the "no speculative locks" rule).
- `event._set_cancel_fn(scope.cancel)` makes the pending event cancellable
  from the TUI timeout button, `sample cancel-tool-call`, and ACP's
  `inspect/cancel_tool_call`, with the native timeout contract. Without it
  the control server would answer "no cancel hook is installed"
  (`_control/cancel.py:1074`) for a pending host call.
- `observer.track_tool_call(event.id, event)` registers the call with ACP's
  turn-cancel bookkeeping, so `cancel_current_turn` stamps the host event
  cancelled and records `interrupted_tool_call_id`
  (`src/inspect_ai/agent/_acp/transport_live.py:350-363`, `:1503-1536`).

### Configuration surface

None. Recording is unconditional: the purpose is a complete record of host
actions, and the native path has no switch either.

### ACP mapping changes

`src/inspect_ai/agent/_acp/event_mapping.py`:

- `_map_tool_event` takes the `_BridgeToolState` and calls
  `bridge.pending.pop(event.id, None)`. A paired host event always follows
  the proposing `ModelEvent` (grants are registered before `bridge_generate`
  returns the response, `util.py:600-604`), so the synthesised in-progress
  card already exists and the real event maps to an update carrying the
  real result. Popping it stops `_map_bridge_tool_completions` from
  settling the same card a second time when the scaffold's `ChatMessageTool`
  arrives in the next input. Today the ordering would be: synth start,
  update (real event pending), update (real event completed), update
  (message settle); after the change the last update is gone.
- Unpaired host events (fresh id) map as their own start and update. If the
  call was model-proposed but unmatched (ambiguous name, or arguments the
  scaffold altered), the synthesised card for the proposal remains and
  settles from the `ChatMessageTool` as today, so that case shows two cards.
  Accepted: the pairing covers every call the grant machinery can match.
- Replay needs no change: `_scan_bridge_tool_facts` already excludes ids
  that have a real `ToolEvent` from synthesis (`:1019`), and the host event
  replays as one completed start through `_map_tool_event`.
- The synthesised start is marked non-cancelable (`:956`) before the router
  can know the call will be executed on the host; the real pending event is
  in fact cancellable. The TUI will not offer the per-tool cancel for that
  card. Left as is (see "Not this design").
- The sub-agent depth filter classifies by span begin/end order in the
  stream, not by `span_id`. A host event emitted while a sub-agent span is
  open is filtered as sub-agent content. The bridge's own `ModelEvent`s
  emitted concurrently are treated the same way today; not new.
- `in_bridge_model_generate`'s docstring (`util.py:365-369`) and
  `_BridgeToolState`'s (`event_mapping.py:109-135`) are updated to say that
  scaffold-run tools emit no `ToolEvent` but host-executed bridged tools do,
  paired by id.

### Viewer

The viewer needs no change to render a host tool event: `ToolEventView`
shows a `Tool: <name>` panel with the function-call rendering of
`arguments`, the result, an error unless its type is `approval`, the
working time, a running indicator while pending, and any `ApprovalEvent`
whose `call.id` matches (`transcript/ToolEventView.tsx:67`, `:106`, `:179`;
`transform/toolApprovals.ts:44`). Approvals of paired host calls therefore
move from flat rows into the tool panel. Denials render as a failed tool
panel with the permission message.

Two rules regress for a bridged turn that mixes host and scaffold-run tool
calls, because both are keyed on "is there any tool event here" rather than
on tool-call ids:

- `showToolCalls={next?.event.event !== "tool"}`
  (`transcript/TranscriptVirtualList.tsx:127`): when the node after a model
  event is a host tool event, the assistant message's tool calls are
  omitted from the model panel, including the scaffold-run calls in that
  same response, which have no tool panel to take over.
- `hasToolEvents` (`transcript/hasToolEventsAtDepth.ts:25`) becomes true at
  that depth from the first host tool event on, so tool-role input messages
  stop being surfaced under the following model calls
  (`transcript/recentInputMessages.ts:39`) and are collapsed in the message
  lists (`transcript/ModelEventView.tsx:217`, `:273`). Scaffold-run results
  remain reachable through "Show all messages" and the Messages tab, but
  disappear from the transcript flow.

The companion ts-mono change keys both rules on coverage: collect the
`ToolEvent.id`s at the depth (the same walk `pairToolApprovals` does), omit
an assistant tool call from the model panel only when a tool event with its
id exists, and hide or collapse a tool-role message only when its
`tool_call_id` has one. Native transcripts are unaffected (every call has a
tool event). Until it lands, mixed bridged turns show the regression above;
bridged turns without host calls are unchanged.

### Denials, summarised

| Outcome | `id` | `function` | `error` | `failed` | RPC/MCP result to scaffold |
|---|---|---|---|---|---|
| Executed, proposal matched | proposing `ToolCall.id` | as the model saw it | mapped failure or `None` | `True` only for an unmapped exception | unchanged |
| Executed, no proposal (no policy) | fresh | MCP tool name | as above | as above | unchanged |
| Denied (policy active, no grant) | fresh | MCP tool name | `permission` | `None` | unchanged (`PermissionError` text) |
| Unknown server or tool, bad arguments | fresh | MCP tool name as sent | `parsing` | `None` | unchanged (`ValueError` text) |
| Operator cancel | as executed | as executed | `timeout` | `None` | MCP error "Command timed out before completing." |
| Bridge teardown mid-call | as executed | as executed | `cancelled` | `None` | none (request abandoned, as today) |

In ACP a denial is a failed card whose content is the input view plus the
error message (`src/inspect_ai/agent/_acp/tool_content.py:532-534`); in the
viewer it is a failed tool panel; in `events_df` it is a row with
`tool_event_error_type == "permission"`.

## Alternatives considered

- **A new event type (`HostToolEvent`).** Every consumer (viewer, ACP,
  textual TUI, control server, dataframe columns, hooks, inspect_scout
  scanners) would need new handling and the type pipeline a new member, and
  none of them could pair it with approvals or proposals the way they pair
  `ToolEvent`. The whole point is that host executions are tool calls.
- **Recording on the `ModelEvent` only** (annotating the proposing call
  with execution facts). No record for unproposed or denied calls, no
  timing or pending state, nothing for the viewer to render, and mutating a
  completed `ModelEvent` needs a second `_event_updated`, which re-delivers
  it to hooks.
- **Emitting through `ModelEventSink`.** Would let claude_code's
  `LiveConsumer` place a sub-agent's host tool event in the sub-agent span.
  The sink is a `ModelEvent`-only protocol with one implementer outside this
  repo; widening it (an `on_tool_event(event, proposal)` hook with a default
  that emits to the transcript) forces an inspect_swe change for a
  placement nicety, while direct emission works identically with and
  without a sink. Deferred.
- **Pair only under an approval policy** (the literal reading of "extend
  the grant record"). Simplest change to `types.py`, but the default
  configuration would then never pair, giving two ACP cards per host call
  and unpaired approvals in the viewer for most users. Recording proposals
  unconditionally is the smaller total change once consumers are counted.
- **Synthesising the event in `bridge_generate` when the `ChatMessageTool`
  comes back**, as ACP does live. Covers only proposed calls whose result
  returns, records the scaffold's rendering of the result rather than the
  execution, has no timing, and misses denials entirely.

## Compatibility and migration

- **Eval log format.** No schema change: `ToolEvent` and `BaseEvent.metadata`
  already exist. Old logs are unaffected. New logs from bridged evals that
  execute host tools gain `tool` events (one per `call_tool` request) and
  `span_begin`/`span_end` pairs of type `tool` around them.
- **Generated TypeScript types.** None to regenerate; `metadata` is already
  typed as an open object.
- **Public API and CLI.** `SandboxAgentBridge.consume_tool_execution_grant`
  returns the record instead of `bool` and `register_tool_execution_grants`
  records without a policy; both are private in practice (underscore-free
  but only called from `service.py` and tests). `call_tool`'s signature and
  wire behaviour are unchanged. No CLI change.
- **Hooks.** `on_sample_event` receives a new event type for bridged
  samples, once per host call, at completion.
- **Dataframes.** `events_df` gains `tool` rows for bridged samples. A count
  of tool events per sample now includes host calls but still not
  scaffold-run calls; documented in `docs/agent-bridge.qmd`.
- **inspect_scout.** Scanners that read eval-log `ToolEvent`s (the grep
  scanner, `src/inspect_scout/_grep_scanner/_event.py`) will see host tool
  events in bridged transcripts; intended.
- **Checkpointing.** Events are restored by `_extend_restored_events`
  (`src/inspect_ai/util/_checkpoint/hydrate.py:657`) like any other. A
  checkpoint taken while a host call is pending persists a pending event
  that resume never completes (the scaffold re-drives the call), as for a
  native tool mid-checkpoint. Grants remain untracked, so a proposal
  recorded before a checkpoint does not pair (and under a policy is denied)
  after resume, as today.
- **Viewer.** Old logs render as before. New mixed bridged turns show the
  two regressions above until the ts-mono companion lands.
- **Existing tests.** `test_host_tool_grants_are_not_stored_without_approval_policy`
  (`tests/agent/test_bridge_approval.py:828`) asserts the opposite of the
  new recording rule and is rewritten to assert attribution without denial;
  `test_scaffold_local_tool_calls_are_not_stored` (`:678`) still holds. The
  Docker approval tests (`tests/tools/test_tools_bridge.py:620`, `:656`)
  keep passing because RPC behaviour is unchanged.
- **CHANGELOG.** One `## Unreleased` line: host tools executed through
  `sandbox_agent_bridge(bridged_tools=...)` are now recorded as tool events
  in the transcript, including denied calls.

## Security

Untrusted input reaching the new code is the scaffold's `tools/call`:
`server`, `tool` and `arguments`, all sandbox-controlled.

- `server` and `tool` are matched against the host registry before use; for
  unknown names the string as sent is recorded in `function` and in the
  error message, as it already is in the RPC error text.
- `arguments` are recorded as executed. Size is bounded by the service
  request read limit (`util/_sandbox/service.py:69`, 150 MiB), which also
  bounds what the scaffold can already push into `ModelEvent` inputs, so
  this is not a new class of log-size exposure; the depth guard (step 2)
  prevents deeply nested JSON from entering the log, the guard the native
  path applies to model-provided arguments. Long argument strings are
  condensed into attachments (`_condense.py:434`).
- `result` comes from the host tool (trusted code) and is recorded inline,
  as native tool results are. Error messages recorded on the event are the
  same strings the scaffold already receives; tracebacks stay out of both,
  as today.
- Nothing in the event flows back to the sandbox: the RPC response is built
  from the same values as before.
- The denial decision, its inputs, and the grant matching rules are
  unchanged. Recording happens after the decision and cannot influence it.

## Testing

Unit tests, `tests/agent/test_bridge_approval.py` (existing helpers
`sandbox_bridge_with_tool` at `:534`, `run_bridge` at `:132`, `call_host_tool`
at `:24`; install a fresh `Transcript` via `_transcript.set` as the ACP
tests do):

- Approved and executed: the event has the proposing call's id and
  function, the executed arguments (key order as sent), the result, `metadata.bridge`
  with `proposed=True`, `approval="granted"`, `completed` and `working_time`
  set, `pending is None`, and sits in a `tool` span whose parent is the
  enclosing span.
- Executed without a policy: paired id, `approval="not_required"`.
- Denied: fresh id, `function` is the MCP tool name, `error.type ==
  "permission"`, `proposed=False`, `approval="denied"`, tool not awaited,
  `PermissionError` still raised.
- Unknown tool and non-object or too-deep arguments: `parsing` event,
  `ValueError` still raised.
- Tool raises `ToolError`, `PermissionError`, `TimeoutError`, an unmapped
  exception, and `LimitExceededError`: the mapped `error`, `failed` as
  specified, and the exception re-raised where the design says so.
- Operator cancel: call `event._cancel()` from a sibling task while the tool
  awaits an `anyio.Event`; assert `error.type == "timeout"` and the RPC
  raises. Outer cancel: cancel the task group mid-await; assert the event is
  not pending and carries `cancelled`.
- Observer: a recording `ExecutionObserver` on `sample_active()` sees the
  call id and event.
- Run the new async tests with `--runtrio` as well as the default backend.

Native refactor, `tests/tools/test_call_tools.py` (which covers the
`execute_tools` error mapping today): the extracted helper returns the same
`ToolCallError` for each exception type; the existing tests cover the call
site.

ACP, `tests/agent/test_acp/test_router_bridge_tools.py` (helpers
`_tool_call_event` at `:79`, `_result_event` at `:94`):

- Live: synth start, then a pending and a completed real `ToolEvent` with
  the same id, then a `ModelEvent` whose input carries the
  `ChatMessageTool`: exactly one start and no completion update after the
  real event's.
- Live, unpaired: a real `ToolEvent` with a fresh id and `metadata.bridge`
  produces its own start and update alongside the synthesised card.
- Replay: existing `test_replay_does_not_synthesize_when_tool_event_present`
  (`:525`) plus a case where the real event carries `metadata.bridge`.

Docker (slow), `tests/tools/test_tools_bridge.py`; these run in PR CI's
`slow-tool-tests` job because the PR touches `tests/tools/**`
(`.github/workflows/build.yml:377-384`, `:521`):

- Extend `test_sandbox_bridge_executes_approved_host_tool_call_once`
  (`:656`): the log has two `tool` events, one with `id == "approved"`,
  `function == "calculator_add"`, `arguments == {"y": 3, "x": 5}`, result
  `"8"`, and one denied with a fresh id and `permission` error.
- Extend `test_single_tool_call_returns_correct_result` (`:199`): one `tool`
  event with a fresh id, `approval == "not_required"`, `proposed is False`,
  nested inside a `tool` span under the agent span.
- Extend `test_sandbox_bridge_rejects_forged_host_tool_call` (`:620`): one
  denied event, no executed event.

Viewer, ts-mono: vitest cases for the coverage-keyed `showToolCalls` and
`recentInputMessages` rules over a fixture with a bridged turn that mixes a
paired host tool event and a scaffold-run call; a native fixture proves no
change.

## Implementation plan

1. **Grant record carries the proposal** (`src/inspect_ai/agent/_bridge/sandbox/types.py`,
   `tests/agent/test_bridge_approval.py`). Add `call` to
   `_ToolExecutionGrant`, return the record from
   `consume_tool_execution_grant`, drop the policy early-return in
   `register_tool_execution_grants`, reword the two warnings, update
   `service.py:234` to the new return type. Rewrite
   `test_host_tool_grants_are_not_stored_without_approval_policy`.
2. **Extract the native error mapping** (`src/inspect_ai/model/_call_tools.py`,
   `tests/tools/test_call_tools.py`). Add `ToolCallFailure` and `tool_call_failure`, switch
   `call_tool_task` to it with no behaviour change, add the mapping test.
3. **Record host tool events** (new
   `src/inspect_ai/agent/_bridge/sandbox/host_tool.py`; `service.py`
   delegates; `src/inspect_ai/event/_tool.py` docstring for
   `metadata.bridge`; `util.py:365-369` docstring). Unit tests from the
   Testing section, including cancellation and trio.
4. **ACP mapping** (`src/inspect_ai/agent/_acp/event_mapping.py`,
   `tests/agent/test_acp/test_router_bridge_tools.py`). Pop `pending` in
   `_map_tool_event`, update docstrings, add the three tests.
5. **Docker tests and docs** (`tests/tools/test_tools_bridge.py`,
   `docs/agent-bridge.qmd` Transcript section, `CHANGELOG.md`).
6. **Viewer companion** (ts-mono, separate PR): coverage-keyed
   `showToolCalls` and tool-message hiding, with tests; then the submodule
   pointer bump in inspect_ai per `.agents/skills/land-ts-mono/SKILL.md`.
   Independent of steps 1 to 5; preferably lands first so the first release
   with host tool events has no mixed-turn regression.

Steps 1 to 5 are one inspect_ai PR (each step a commit). Step 6 is its own
PR.

## Open questions

1. **Record proposals without an approval policy?** Recommendation: yes
   (attribution only; the scaffold sees no change). The strict alternative
   pairs only under a policy and leaves the default configuration with two
   ACP cards per host call.
2. **Denial error type.** Recommendation: `permission`, which renders today
   and matches how the native path types a `PermissionError`. `approval`
   would group denials with policy rejections in dataframes but is hidden by
   the viewer's tool panel unless a viewer change accompanies it.
3. **Sequencing with the viewer companion.** Recommendation: land the
   ts-mono change first; if the Python change ships alone, mixed bridged
   turns show the two rendering regressions described under Viewer until it
   does.

## Not this design

- **Unconditional execution grants.** Deny any host call that matches no
  recorded proposal even without an approval policy, with a per-spec opt-out
  (`BridgedToolsSpec(allow_unproposed=True)` or similar) for tools a
  scaffold legitimately calls outside a model turn. From this design it
  needs: proposals recorded regardless of policy (step 1), the `proposed`
  marker on the event, and the denial branch in `host_tool.py`, which it
  changes from `tool_approval_required() and grant is None` to `grant is
  None and not spec.allow_unproposed`. Nothing here precludes it; the
  proposal deque's bound and the ambiguity rule would need a second look
  because they would then deny rather than unpair.
- **Parity of the host path with native execution**: `validate_tool_input`,
  `tool_params` coercion, `max_tool_output` truncation, `ToolDef.viewer`
  for the event's `view`.
- **`ModelEventSink` hook for tool events**, so a sink that re-attributes
  sub-agent generations can place their host tool events in the same span.
- **Back-filling `ToolEvent.message_id`** when the scaffold's
  `ChatMessageTool` arrives, which needs a hooks-safe way to update a
  completed event.
- **Grants and proposals across checkpoint restore** (register the deque
  with the checkpointer).
- **ACP cancelable flag** for synthesised cards that turn out to be host
  executions; the router would need the bridge's registry to know at start
  time.
- **A viewer badge** rendering `metadata.bridge` (host execution, denied)
  on the tool panel.
- **Host tool exceptions do not fail the sample** (the service converts
  them to RPC errors); unchanged here, worth a deliberate decision.
- **Scaffold-run tool calls** remain without `ToolEvent`s; the
  `in_bridge_model_generate` synthesis in ACP stays for them.
