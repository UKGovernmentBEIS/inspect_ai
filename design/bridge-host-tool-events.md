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
  transcript: executed, denied, or rejected (unknown server or tool,
  arguments that are not a JSON object or nest too deeply).
- An executed call carries the function name as the model saw it, the
  bridged server and tool, the arguments as executed, the result as
  delivered to the scaffold (or the error), start and completion times,
  working time, and a marker that it ran on the host through the bridge.
- An executed call that matches a recorded model proposal carries the
  proposing `ToolCall.id` and is placed in the span of the proposing
  `ModelEvent`, so consumers pair it with the proposal the way they pair
  native `ToolEvent`s. A denied or rejected call gets a fresh id and an
  error. An executed call with no matching proposal gets a fresh id and
  `metadata.bridge.proposed = false`, with no `error` (see Open questions:
  the task text asked for an error here).
- The event behaves like a native `ToolEvent` for live surfaces: pending
  while running, cancellable by the operator, visible to the execution
  observer, finalised exactly once by the host runner.
- Recorded results follow the eval's image-logging policy, as message
  content does.
- No change to what the scaffold receives for calls that execute today,
  with two deliberate exceptions listed under Compatibility: arguments that
  are not a JSON object, and arguments nested deeper than the native bound,
  are now rejected before execution. The approval and grant decision is
  unchanged.

Non-goals:

- Recording the scaffold's own tool executions (Bash, Read, Edit run inside
  the sandbox). Those remain visible only through `ModelEvent` inputs.
- Making execution grants unconditional (denying unproposed calls without an
  approval policy). See "Not this design".
- Argument schema validation, dataclass coercion, `max_tool_output`
  truncation, or `ToolDef.viewer` support for bridged host tools. The
  bridge path calls `tool_fn(**arguments)` directly today and keeps doing so.
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
  shared `_SpanCell`). Verified by a spike that spawned a task inside a span:
  the task's `current_span_id()` was the agent span and
  `in_bridge_model_generate()` was `False` there.
- `call_tool` (`service.py:219-265`) checks the server (`:227`) and tool
  (`:231`), then denies unless no approval is active or a grant matches
  (`:234-244`), raising `PermissionError("... was not approved for
  execution")`. It then awaits `tool_fn(**arguments)` (`:247`) with the
  arguments exactly as the scaffold sent them (a non-object fails inside
  the call with a `TypeError`; nesting is unbounded) and returns a plain
  string verbatim, MCP content blocks for image results, or
  `to_json_str_safe(result)` otherwise (`:253-263`).
- Any exception becomes an RPC error string `Error calling method call_tool:
  <str(ex)>` (`util/_sandbox/service.py:562-581`; tracebacks are
  deliberately kept host-side), which the proxy returns as JSON-RPC error
  `-32603` (`proxy.py:2192-2195`). The message the scaffold sees is the
  exception's own text: a `TimeoutError("tool-specific timeout")` reaches
  it as that string. `LimitExceededError` is special-cased: the service
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

- Two-phase emission. The pending event is constructed per call before any
  tool span exists (`_call_tools.py:424-430`), so `BaseEvent.model_post_init`
  stamps it with the enclosing span (`src/inspect_ai/event/_base.py:35-48`).
  It is then emitted inside `span(name=call.function, type="tool")`
  (`:789-790`; denials at `:728-731`), and finalised with `_set_result` and
  `transcript()._event_updated(event)` (`:504-518`). The resulting shape,
  verified by running a mockllm eval whose tool called
  `transcript().info()`: the stream is `span_begin(tool)`, `tool`, nested
  events, `span_end`; the `ToolEvent.span_id` equals the tool span's
  `parent_id`, not the tool span's id; the nested `InfoEvent.span_id`
  equals the tool span's id. In the viewer this layout renders as a tool
  panel with an empty child list plus a sibling `tool` span node holding
  the nested events: `elevateChildNode` only lifts a `ToolEvent` that is a
  child of its span, and keeps the span as its own node when, as here, the
  event is a sibling
  (`packages/inspect-components/src/transcript/transform/transform.ts:196-198`).
  That is how every native tool call with nested events renders today.
- `ToolEvent._set_result` computes `completed` and `working_time = wall −
  waiting_time` (`src/inspect_ai/event/_tool.py:70-115`); the caller
  measures waiting time from `sample_waiting_time()` before and after
  (`_call_tools.py:423`, `:503`).
- Exceptions from the tool body map to `ToolCallError` types
  (`_call_tools.py:220-284`): timeout, unicode_decode, parsing (embedded
  null byte), sandbox_unavailable, permission, file_not_found,
  is_a_directory, limit, parsing, approval, unknown (`ToolError`). The
  mapping rewrites messages (a `TimeoutError` becomes "Command timed out
  before completing."). Anything else sets `failed=True` and propagates.
- A per-call cancel scope is exposed through `event._set_cancel_fn`
  (`:492`); operator cancel records `ToolCallError("timeout", "Command
  timed out before completing.")` (`:549-556`).
- The execution observer is told about the in-flight call
  (`:201`, `:359`), which is how ACP's turn cancel finds and marks it.
- Model-provided arguments are bounded to `MAX_TOOL_CALL_ARGUMENTS_DEPTH`
  (100) before execution (`_call_tools.py:742`, `:1348-1360`) because
  pydantic-core and log condensation only tolerate bounded nesting;
  unbounded depth "would crash sample logging rather than the sample
  itself".
- `BaseEvent` supplies `uuid`, `span_id`, `timestamp`, `working_start` and
  a free-form `metadata` dict (`_base.py:20-48`).

### Condensation of tool events

`walk_tool_event` walks `arguments` and nested `events` but not `result`
(`src/inspect_ai/log/_condense.py:936-944`). Consequences, verified by
running `condense_sample` on a sample holding a `ToolEvent` whose result is
`[ContentText, ContentImage]` and a `ChatMessageTool` with the same image:
with `log_images=True` the message image became an attachment and the event
image stayed inline; with `log_images=False` the message image was replaced
by `<base64-data-removed>` and the event image stayed inline. Text over 100
characters in walked fields becomes an attachment (`:434`). So today the
image-logging policy does not reach native tool results either; this design
adds a second copy of host tool results and has to close that gap rather
than widen it (see "The recorded result").

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
  `b2c1bf0`), which stamps `event.span_id` at `on_pending` to attribute a
  sub-agent's generations to an `agent-<tool_use_id>` span it opened, and
  emits the event itself. It does not emit `ToolEvent`s during a live run
  (the JSONL `ToolEvent` builder in `_events/events.py` is not called from
  `claude_code.py`). Installing a sink also disables partial-output
  publishing (`_model.py:1394-1401`).
- The viewer decides per model event whether to render the assistant's tool
  calls inline (`transcript/TranscriptVirtualList.tsx:127`: omit them when
  the next node is a tool event) and whether tool-role input messages are
  shown under the model call (`transcript/recentInputMessages.ts:39`) or
  collapsed (`transcript/ModelEventView.tsx:217`, `:273`), keyed on
  `hasToolEvents`, a per-depth backward scan for any tool event
  (`transcript/hasToolEventsAtDepth.ts:25`). Approvals pair to tool events
  by `call.id == ToolEvent.id` (`transcript/transform/toolApprovals.ts:44`);
  today a non-auto approval of a bridged call renders as a flat row because
  no tool event carries that id. Messages-tab navigation from a tool-role
  message resolves through a per-level map of `ToolEvent.id`s
  (`transcript/resolveMessageToEvent.ts:223-236`, `:310-333`): the tool
  event must sit at the same timeline level as the `ModelEvent` whose input
  carries the message. `ToolEventView` hides `error.type == "approval"`
  (`transcript/ToolEventView.tsx:106`) on the assumption that the paired
  approval panel explains it, and shows a running indicator while `pending`
  (`:179`). The viewer substitutes `attachment://` references across the
  fetched sample before rendering
  (`apps/inspect/src/log_data/chunkedAttachments.ts:23`).
- Pending `ToolEvent`s drive the textual TUI's "Executing…" state and
  timeout button (`src/inspect_ai/_display/textual/widgets/samples.py:1086`),
  the control server's sample activity (`src/inspect_ai/_control/state.py:1213`)
  and `sample cancel-tool-call`, which errors when a pending match has no
  cancel hook (`src/inspect_ai/_control/cancel.py:1002`, `:1074`).
- Hooks receive every non-pending emission (`src/inspect_ai/hooks/_hooks.py:757`),
  so two terminal updates of one event reach a hook twice.
- Dataframes: `events_df` exposes `ToolEventColumns` and `EventTiming`
  (`src/inspect_ai/analysis/_dataframe/events/columns.py:54-60`, `:79-87`).
  Bridged samples currently yield no `tool` rows.

## Design

### Overview

`call_tool` keeps its contract with the proxy (same results, same error
strings, same denial) for every call that executes today, and gains one
responsibility: record a `ToolEvent` for the request. The event is emitted
directly to the sample transcript from the service task, in the native
shape (event stamped with its parent span, emitted inside a `tool` span,
nested events inside that span, which the viewer shows as a sibling span
node beside the tool panel), placed under the span of the proposing
`ModelEvent`. Pairing and placement come from the grant record, which is
extended to hold the proposing `ToolCall` and that event's span, and is now
written whether or not an approval policy is active (the denial decision is
unchanged).

```
scaffold ──tools/call──▶ proxy ──call_tool RPC──▶ service task
                                                  │ resolve server/tool; arguments must be an object within the depth bound
                                                  │ grant = consume_tool_execution_grant(...)
                                                  │ deny if approval active and grant is None
                                                  │ under parent_span(grant.span_id):
                                                  │   ToolEvent(id = grant.call.id | fresh, pending)   ← stamped with the parent
                                                  │   span(type="tool"): transcript()._event(event)
                                                  │     observer.track_tool_call + CancelScope
                                                  │     result = await tool_fn(**arguments)          ← nested events inside the tool span
                                                  │ event._set_result(...); _event_updated (once)
                                                  ▼ return serialized result / raise the original exception
```

### Grant record carries the proposal and its span

`src/inspect_ai/agent/_bridge/sandbox/types.py`:

```python
class _ToolExecutionGrant(NamedTuple):
    server: str
    tool: str
    arguments: dict[str, Any]
    call: ToolCall
    """The proposing model tool call (id, function as the model saw it, view)."""
    span_id: str | None
    """Span to place the execution under when it differs from the span current
    at registration (a sink re-attributed the proposing ModelEvent); None
    means "the span current when the call executes"."""
```

- `register_tool_execution_grants(calls, *, span_id: str | None = None)`
  drops the early return at `types.py:107` and records a grant for every
  approved (or, without a policy, every returned) call that resolves to
  exactly one bridged tool. The base no-op hook on `AgentBridge`
  (`src/inspect_ai/agent/_bridge/types.py:202`) gains the same keyword,
  because `bridge_generate` is shared by in-process and sandbox bridges and
  calls the hook for every generation, including ones without tool calls
  (`util.py:602-604`); without the base change every in-process generation
  would raise `TypeError`. The record is what lets an execution be attributed to its
  proposal; the denial decision stays where it is (below). The ambiguity and
  eviction warnings (`types.py:114-123`, `:124-131`) are reworded so they do
  not say "the call will be denied" when no policy is active ("no execution
  grant registered; under an approval policy the call is denied, otherwise it
  executes unpaired").
- `consume_tool_execution_grant(server, tool, arguments) ->
  _ToolExecutionGrant | None` returns the matched record instead of `bool`.
  Matching is unchanged (`_json_equal`, one-shot, oldest first).
- The deque stays bounded at `_MAX_TOOL_EXECUTION_GRANTS`. Without a policy
  the deque now fills for every host-tool proposal, so the eviction warning
  will fire for long runs whose scaffold proposes host calls it never
  executes; that is the existing bound doing its job.

Capturing the proposing event's span, in `bridge_generate`
(`src/inspect_ai/agent/_bridge/util.py:562`):

- When the bridge has a `model_event_sink`, `bridge_generate` wraps it for
  the `model.generate()` call in a `_SpanCapturingSink` (private, in
  `util.py`) that forwards `on_pending` and `on_complete` to the inner sink
  and, after `on_complete`, remembers `event.span_id`. The sink protocol is
  not widened and the inner sink is unaware. When the bridge has no sink,
  nothing is installed (installing one would disable partial-output
  publishing, `_model.py:1394-1401`); the `ModelEvent` was stamped with
  `current_span_id()` in this same task.
- After approval, `register_tool_execution_grants(calls, span_id=captured)`
  where `captured` is the remembered span if it differs from
  `current_span_id()` at that moment, else `None`. Storing only a
  differing span keeps executions under the checkpointer's rotating
  `checkpoint N` span when no re-attribution happened: a stored checkpoint
  id would otherwise pin a later execution under a span that has since
  closed. With claude_code's `LiveConsumer`, main-agent proposals capture
  `None` (it attributes them to the current span) and sub-agent proposals
  capture `agent-<tool_use_id>`.

Why record unconditionally: the default bridge configuration has no approval
policy. If pairing were available only under approval, the common case would
produce an unpaired event for every host call, and ACP live mode would show
two cards per call (the synthesised one from the `ModelEvent` and a fresh
one from the real event) with no id to reconcile them. Recording the
proposal costs one bounded deque entry and is exactly the substrate the
"unconditional grants" follow-up needs (see "Not this design").

### A span parent helper

`src/inspect_ai/util/_span.py` gains a private context manager:

```python
@contextlib.contextmanager
def parent_span(parent_id: str | None) -> Iterator[None]:
    """Make `parent_id` the current span for the block (no-op when None)."""
```

It sets `_current_span_id` to the given id and resets the token on exit,
the same set/reset pair `span()` uses (`_span.py:86-109`). Inside the block
a constructed event is stamped with `parent_id` and a `span()` opened there
gets `parent_id` as its parent. Resetting restores whatever was current,
including the checkpointer's `_SpanCell`.

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
    arguments: JsonValue,
) -> JsonValue:
```

Control flow, in order:

1. **Resolve.** Unknown server or tool: record a completed event with
   `error=ToolCallError("parsing", "Unknown tool '<tool>' in server
   '<server>'")` (the current `ValueError` text), fresh id,
   `function=tool`, then raise the same `ValueError` as today. This mirrors
   the native "Tool X not found" parsing error (`_call_tools.py:750`).
2. **Check arguments.** `arguments` must be a JSON object and must pass
   `_exceeds_max_depth` (`_call_tools.py:1364`). Otherwise record a
   `parsing` event with `arguments={}` and the offending shape described in
   the error message, and raise `ValueError` with that message. **This is a
   behaviour change**: today a non-object fails inside `tool_fn(**arguments)`
   with a `TypeError` whose text reaches the scaffold, and a deeper-than-100
   object executes. The bound is the one native applies to model-provided
   arguments for the same reason (`_call_tools.py:1348-1360`): the recorded
   arguments enter the log, and unbounded nesting crashes sample logging.
   Listed under Compatibility and Open questions.
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
5. **Execute.**

   ```python
   with parent_span(grant.span_id if grant else None):
       event = ToolEvent(                                  # stamped with the parent span
           id=grant.call.id if grant else uuid(),          # shortuuid, as for event uuids
           function=grant.call.function if grant else tool,
           arguments=arguments,                            # as executed
           view=grant.call.view if grant else None,
           pending=True,
           metadata={"bridge": {...}},                     # see below
       )
       waiting_start = sample_waiting_time()
       async with span(name=event.function, type="tool"):  # parent = the event's span
           transcript()._event(event)
           with observer.track_tool_call(event.id, event):
               try:
                   with anyio.CancelScope() as scope:
                       event._set_cancel_fn(scope.cancel)
                       result = await tool_fn(**arguments)
               except anyio.get_cancelled_exc_class():
                   finalise(error=ToolCallError("cancelled", ...)); raise   # outer cancel only
               except LimitExceededError as ex:
                   finalise(error=ToolCallError("limit", ...)); raise
               except Exception as ex:
                   finalise(*mapped(ex)); raise                            # original exception
           if scope.cancel_called:
               finalise(error=ToolCallError("timeout", ...))
               raise ToolError("Command timed out before completing.")
           finalise(result=result)
   ```

   `observer` is `sample_active().execution_observer` or the null observer,
   as in `_call_tools.py:189-196`. `finalise` is
   `event._set_result(result=..., truncated=None, error=..., waiting_time=
   sample_waiting_time() - waiting_start, agent=None, failed=..., message_id=
   None, agent_span_id=getattr(tool_fn, "agent_span_id", None))` followed by
   `transcript()._event_updated(event)`; it runs exactly once per event.
   The per-call scope's own cancellation is swallowed at the `with
   CancelScope` exit and never reaches the `except`, so the operator-cancel
   path publishes a single `timeout` update; an outer cancellation (bridge
   teardown, sample limit) propagates through the scope to the `except` and
   publishes a single `cancelled` update.
6. **Return** the serialized result exactly as `service.py:253-263` does
   today.

Single-shot events (steps 1, 2, 4) have no proposal, so they are
constructed under the span current in the service task, given
`pending=None`, finalised with `_set_result(..., waiting_time=0.0)` and
recorded once with `transcript()._event(event)` inside their own `tool`
span, the shape the native denial path produces (`_call_tools.py:728-731`).

### The recorded result

`result` is the `ToolResult` the tool returned, massaged as the native path
does for the event (`_call_tools.py:284-333`): a `str` verbatim; a single
`Content` wrapped in a list; a list of `Content` as is; anything else as
`to_json_str_safe(result)`, which is the string the scaffold receives
(`service.py:263`). No truncation is applied (`truncated=None`): the bridge
delivers the full result to the scaffold today and the event records what
was delivered.

Media in the recorded result follow the eval's logging policy. `walk_tool_event`
(`_condense.py:936-944`) gains `result=walk_tool_result(event.result,
content_fn, context)`, where `walk_tool_result` applies `content_fn` to the
media fields of `ContentImage`, `ContentAudio`, `ContentVideo` and
`ContentDocument` items of a list result (the same fields `walk_content`
handles, `_condense.py:1205-1240`) and leaves `ContentText` and `str`
results untouched. Because `walk_tool_event` serves both directions, the
effect is:

- `condense_sample(log_images=True)`: an image in a tool result becomes an
  `attachment://` reference, as an image in a message does.
- `condense_sample(log_images=False)`: it becomes `<base64-data-removed>`,
  closing the gap shown above for native tool events too.
- `resolve_sample_attachments` (`_condense.py:725`) restores it through the
  same walker; the viewer substitutes references client-side
  (`chunkedAttachments.ts:23`); the bounded transcript's reference tracking
  is a generic object walk and needs no change.
- Text results stay byte-identical to today, so no existing log with text
  tool results changes shape.

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
path uses the mapping **for the event only** and always re-raises the
original exception, so the RPC error text the scaffold receives is
unchanged for every failure that exists today:

- Mapped failure: `error=failure.error`, `result=failure.result`,
  `failed=None`; re-raise `ex`. The event shows the native wording ("Command
  timed out before completing.") while the scaffold still sees
  `str(ex)`; the two are deliberately not unified, because changing the
  wire text is out of scope.
- `LimitExceededError`: record `ToolCallError("limit", ...)`, re-raise `ex`
  so `_handle_request` still calls `active.limit_exceeded(ex)`
  (`util/_sandbox/service.py:552-560`).
- Unmapped exception: `error=ToolCallError("unknown", str(ex))`,
  `failed=True`; re-raise `ex`. The native path leaves `error=None` here
  because the exception goes on to fail the sample; over the bridge it does
  not (the service converts it to an RPC error, unchanged by this design),
  so the message is recorded on the event instead.
- Operator cancel (`scope.cancel_called`): `error=ToolCallError("timeout",
  "Command timed out before completing.")`, `failed=None`, the contract at
  `_call_tools.py:549-556`; raise `ToolError` with that message. This path
  does not exist today (there is nothing to cancel), so the message is new
  rather than changed.
- Outer cancellation: `error=ToolCallError("cancelled", "Host tool call was
  cancelled before completing.")`, `failed=None`; re-raise. `_set_result`
  and `_event_updated` are synchronous, so this runs inside the
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
  is the proposing call's id and the event sits in that proposal's span).
- `approval`: `"granted"` (policy active, grant consumed), `"denied"`
  (policy active, no grant), `"not_required"` (no policy), or `null` for
  events recorded before the grant check (unknown tool, bad arguments).

`metadata` is already in the log schema and the generated TypeScript types
(`metadata?: {[key: string]: unknown} | null`), so no type generation is
needed (see `design/type-generation-pipeline.md`). The key is documented in
the `ToolEvent` docstring and in `docs/agent-bridge.qmd`.

### Where the event lands: span and sink

- A paired execution is placed under the span the proposing `ModelEvent`
  was recorded in, whether that span was the task's current span (no sink,
  or a sink that attributed to the current span) or one a sink assigned
  (claude_code sub-agents). The `ToolEvent` therefore sits at the same
  timeline level as the `ModelEvent` that proposed it and as the later
  `ModelEvent` whose input carries its result, which is what the viewer's
  per-level pairing (`resolveMessageToEvent.ts:223-236`) and the
  coverage-keyed rules below require.
- Unpaired and single-shot events are placed under the span current in the
  service task: the agent span, or the checkpointer's current
  `checkpoint N` span via the shared `_SpanCell`
  (`src/inspect_ai/util/_span.py:135-152`,
  `src/inspect_ai/util/_checkpoint/checkpointer_impl.py:293`).
- `ModelEventSink` is not widened. The bridge's private wrapper reads the
  span the sink assigned; the sink neither sees tool events nor needs to.
- `use_model_event_sink` is not active in the `call_tool` task, so a host
  tool that itself calls a model records its `ModelEvent` directly under the
  tool span, which is where a native tool's nested generation goes.
- Placement is not stored across a checkpoint restore (grants are not
  tracked); a proposal recorded before a checkpoint pairs with nothing after
  resume, as today.

### Nested events

A host tool that uses `sandbox()` produces `SandboxEvent`s from the same
task; their `span_id` is taken from `current_span_id()` at construction
(`_base.py:35-48`), which inside the `async with span(...)` block is the
host tool's span. The `ToolEvent` itself carries the tool span's parent.
That is the native shape verified above, and it renders as native tool
calls do: the tool panel, then a sibling `tool` span node containing the
nested events (`transform/transform.ts:196-198`), not as children of the
panel. The timeline turns a `tool` span that contains model events into a
tool-spawned agent (`transcript/timeline/core.ts:989`), the same
classification a native tool that generates gets.

### Message linkage

`ToolEvent.message_id` is the id of the `ChatMessageTool` the model saw
(`_call_tools.py:512`). For a host call the scaffold builds that message
itself and sends it back in a later request, where `apply_message_ids`
assigns an id by content hash (`util.py:894-902`,
`src/inspect_ai/agent/_bridge/types.py:250-274`). That id does not exist
when the event is finalised, so `message_id` is `None`. Consumers cope: the
viewer's tool label lookup falls back to the tool id
(`transcript/ToolEventView.tsx:94-98`), and messages-tab navigation from a
tool-role message resolves through `tool_call_id` at the same level
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
- The host runner finalises each event exactly once, on every path
  (success, mapped failure, unmapped failure, limit, operator cancel, outer
  cancel). That is not the only update a consumer can see: ACP's
  `cancel_current_turn` clears `pending`, stamps
  `ToolCallError("cancelled")` and `failed=True` on every tool event the
  observer tracked, and publishes them with `_event_updated`
  (`transport_live.py:1451`, `:450-455`, `:1485`), then interrupts the
  agent's turn scope through the channel; it does not fire the per-call
  cancel scope, so the host tool keeps running. When it later finishes, the
  runner's finalisation records the result and timing while `_set_result`
  keeps the sticky cancel marker (`_tool.py:96-115`). Hooks (`_hooks.py:757`)
  and ACP therefore see two non-pending updates for an ACP-cancelled host
  call, the same sequence a native tool produces under
  `cancel_current_turn`.

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
whose `call.id` matches; nested events appear in the sibling `tool` span
node
(`transcript/ToolEventView.tsx:67`, `:106`, `:179`;
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

The companion ts-mono change keys both rules on coverage at the timeline
level: collect the `ToolEvent.id`s at that level (the same per-level map
`resolveMessageToEvent.ts:223-236` builds), omit an assistant tool call
from the model panel only when a tool event with its id exists there, and
hide or collapse a tool-role message only when its `tool_call_id` has one.
Native transcripts are unaffected (every call has a tool event at its
level). Placing paired host events in the proposing event's span is what
makes a per-level rule sufficient: a host event in an outer span while the
proposal and its result sit in a sub-agent span would pair with neither,
which is why span attribution is part of this design rather than a
cosmetic choice. Until the companion lands, mixed bridged turns show the
regression above; bridged turns without host calls are unchanged.

### Outcomes, summarised

| Outcome | `id` | `function` | `error` | `failed` | `metadata.bridge.proposed` | RPC/MCP result to scaffold |
|---|---|---|---|---|---|---|
| Executed, proposal matched | proposing `ToolCall.id` | as the model saw it | mapped failure or `None` | `True` only for an unmapped exception | `true` | unchanged; on failure the original exception text |
| Executed, no proposal matched (no policy) | fresh | MCP tool name | as above | as above | `false` | unchanged |
| Denied (policy active, no grant) | fresh | MCP tool name | `permission` | `None` | `false` | unchanged (`PermissionError` text) |
| Unknown server or tool | fresh | MCP tool name as sent | `parsing` | `None` | `false` | unchanged (`ValueError` text) |
| Arguments not an object, or nested over 100 deep | fresh | MCP tool name | `parsing` | `None` | `false` | **changed**: `ValueError` text instead of a `TypeError` text or execution |
| Tool raised `LimitExceededError` | as executed | as executed | `limit` | `None` | as executed | unchanged (limit handling and error text) |
| Operator cancel | as executed | as executed | `timeout` | `None` | as executed | new: MCP error "Command timed out before completing." |
| Bridge teardown mid-call | as executed | as executed | `cancelled` | `None` | as executed | none (request abandoned, as today) |

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
- **Emitting the tool event through `ModelEventSink`.** Would let a sink
  place the event itself, but widens a `ModelEvent`-only protocol whose one
  implementer lives outside this repo. Reading the span the sink assigned
  through a private wrapper gives the same placement without changing the
  protocol, so that is what the design does.
- **Placing every host event under the service task's current span.** Zero
  extra machinery, but a sub-agent's host call would sit one level above
  its proposal and result, where the viewer's per-level pairing and
  coverage rules cannot see it (the per-level map at
  `resolveMessageToEvent.ts:223-236`). Rejected.
- **Pair only under an approval policy** (the literal reading of "extend
  the grant record"). Simplest change to `types.py`, but the default
  configuration would then never pair, giving two ACP cards per host call
  and unpaired approvals in the viewer for most users. Recording proposals
  unconditionally is the smaller total change once consumers are counted.
- **Recording deep or non-object arguments and executing anyway.** Keeps
  the scaffold-facing behaviour byte-identical, but either records
  something other than what executed (a placeholder) or admits unbounded
  nesting into the log, which is what the native bound exists to prevent.
  Rejected in favour of an explicit, documented restriction.
- **Synthesising the event in `bridge_generate` when the `ChatMessageTool`
  comes back**, as ACP does live. Covers only proposed calls whose result
  returns, records the scaffold's rendering of the result rather than the
  execution, has no timing, and misses denials entirely.

## Compatibility and migration

- **Eval log format.** No schema change: `ToolEvent` and `BaseEvent.metadata`
  already exist. Old logs are unaffected. New logs from bridged evals that
  execute host tools gain `tool` events (one per `call_tool` request) and
  `span_begin`/`span_end` pairs of type `tool` around them.
- **Tool results with media, all tool events.** With the `walk_tool_result`
  change, any new log (native or bridged) stores images in tool results as
  attachments (`log_images=True`) or removes them (`log_images=False`),
  where today they are inline in both cases. Readers of this version resolve
  the references; an older inspect reading a newer log shows the
  `attachment://` string in that result. Text results are unchanged.
- **Scaffold-facing behaviour.** Two calls that behave differently:
  arguments that are not a JSON object (today: a `TypeError` from
  `tool_fn(**arguments)`; after: a `ValueError` before execution) and
  arguments nested deeper than 100 containers (today: executed; after:
  rejected with the native depth error). Both are MCP `-32603` errors either
  way; only the text and, for depth, the execution change. No known
  scaffold sends either.
- **Generated TypeScript types.** None to regenerate; `metadata` is already
  typed as an open object.
- **Public API and CLI.** `SandboxAgentBridge.consume_tool_execution_grant`
  returns the record instead of `bool`; `register_tool_execution_grants`
  gains a defaulted keyword on both `AgentBridge` and the sandbox override
  and records without a policy; all are only called from `service.py`,
  `util.py` and tests. A third-party `AgentBridge` subclass overriding the
  hook with the old signature would break at the shared call site; none is
  known. `call_tool`'s signature and wire
  behaviour are unchanged except as listed above. `util/_span.py` gains a
  private helper. No CLI change.
- **Hooks.** `on_sample_event` receives a new event type for bridged
  samples, once per host call at completion, plus ACP's early cancellation
  update when `cancel_current_turn` catches the call in flight (the same
  two deliveries a native tool produces in that case).
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
  keep passing because RPC behaviour for those calls is unchanged.
- **CHANGELOG.** Two `## Unreleased` lines: host tools executed through
  `sandbox_agent_bridge(bridged_tools=...)` are now recorded as tool events
  in the transcript, including denied calls; images in tool results now
  follow `log_images` like images in messages.

## Security

Untrusted input reaching the new code is the scaffold's `tools/call`:
`server`, `tool` and `arguments`, all sandbox-controlled.

- `server` and `tool` are matched against the host registry before use; for
  unknown names the string as sent is recorded in `function` and in the
  error message, as it already is in the RPC error text.
- `arguments` are recorded as executed. Size is bounded by the service
  request read limit (`util/_sandbox/service.py:69`, 150 MiB), which also
  bounds what the scaffold can already push into `ModelEvent` inputs, so
  this is not a new class of log-size exposure. Nesting is bounded by the
  depth check in step 2, which is the native bound applied to
  model-provided arguments for the same reason: a recorded value the log
  writer cannot serialize would fail sample logging. Long argument strings
  are condensed into attachments (`_condense.py:434`).
- `result` comes from the host tool (trusted code). Media in it follow the
  `log_images` policy through `walk_tool_result`. Error messages recorded
  on the event are the same strings the scaffold already receives;
  tracebacks stay out of both, as today.
- Nothing in the event flows back to the sandbox: the RPC response is built
  from the same values as before, and failures re-raise the original
  exception.
- The denial decision, its inputs, and the grant matching rules are
  unchanged. Recording happens after the decision and cannot influence it.

## Testing

Unit tests, `tests/agent/test_bridge_approval.py` (existing helpers
`sandbox_bridge_with_tool` at `:534`, `run_bridge` at `:132`, `call_host_tool`
at `:24`; install a fresh `Transcript` via `_transcript.set` as the ACP
tests do, and subscribe a recorder to count emissions):

- Approved and executed: the event has the proposing call's id and
  function, the executed arguments (key order as sent), the result,
  `metadata.bridge` with `proposed=True`, `approval="granted"`, `completed`
  and `working_time` set, `pending is None`.
- Event tree: run the call inside an outer `span()`; assert the stream is
  `span_begin(tool)`, `tool`, `info`, `span_end`; `ToolEvent.span_id`
  equals the outer span; the tool span's `parent_id` equals the outer span;
  the `InfoEvent` the tool emits carries the tool span's id. The same
  assertions for a denial (single-shot event inside its own tool span).
  This is the native layout, and the viewer fixture below asserts its
  native presentation (tool panel with no children, sibling span node
  holding the nested event).
- Span attribution: a stub `ModelEventSink` that stamps `event.span_id =
  "agent-sub"` in `on_pending`; run `bridge_generate`, then execute the
  matching host call; assert the grant stored `"agent-sub"`, the
  `ToolEvent.span_id` is `"agent-sub"` and the tool span's `parent_id` is
  `"agent-sub"`. A second case where the stub stamps the current span
  asserts the grant stored `None` and the event follows the span current at
  execution.
- Executed without a policy: paired id, `approval="not_required"`.
- Unproposed execution without a policy: fresh id, `error is None`,
  `proposed=False`.
- Denied: fresh id, `function` is the MCP tool name, `error.type ==
  "permission"`, `proposed=False`, `approval="denied"`, tool not awaited,
  `PermissionError` still raised with today's text.
- Unknown tool, non-object arguments, arguments nested 101 deep: `parsing`
  event, `ValueError` raised, tool not awaited; arguments nested 100 deep
  execute.
- Failure paths: tool raises `ToolError`, `PermissionError`,
  `TimeoutError("tool-specific timeout")`, an unmapped exception, and
  `LimitExceededError`. Assert the mapped `error` and `failed` on the
  event, and that the exception propagated to the caller is the original
  object with its original message (RPC text preservation).
- Cancellation: operator cancel via `event._cancel()` from a sibling task
  while the tool awaits an `anyio.Event`; assert `error.type == "timeout"`,
  the RPC raises `ToolError`, and the transcript recorder saw exactly one
  non-pending update for the event. Outer cancel: cancel the enclosing task
  group mid-await; assert `error.type == "cancelled"`, `pending is None`,
  and again exactly one non-pending update.
- ACP turn cancel (`tests/agent/test_acp/`, using the `_capture.py` helper
  that installs a `LiveAcpTransport` as the active sample's
  `execution_observer`, `:66`): start a host call whose tool awaits an
  `anyio.Event`, call `cancel_current_turn()`, assert the event immediately
  shows `error.type == "cancelled"`, `failed is True`, `pending is None`
  and the `InterruptEvent` names its id; then release the tool and assert
  the marker is retained, `result` and `completed` are recorded, and the
  recorder saw exactly two non-pending updates (ACP's, then the runner's).
- In-process regression: the existing in-process `bridge_generate` tests
  with and without tool calls (`tests/agent/test_bridge_approval.py:171`,
  `:191`) keep passing, proving the base hook accepts the `span_id` keyword.
- Observer: a recording `ExecutionObserver` on `sample_active()` sees the
  call id and event.
- Run the new async tests with `--runtrio` as well as the default backend.

Native refactor, `tests/tools/test_call_tools.py` (which covers the
`execute_tools` error mapping today): the extracted helper returns the same
`ToolCallError` for each exception type; the existing tests cover the call
site.

Condensation, `tests/log/test_log_attachments.py`: a sample with a
`ToolEvent` whose result is `[ContentText, ContentImage]`; with
`log_images=True`, `condense_sample` turns the image into an attachment and
`resolve_sample_attachments` restores it byte-identically, and the text is
untouched; with `log_images=False` the image is `<base64-data-removed>`.
A `str` result over 100 characters stays inline in both cases.

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
  `"8"`, and one denied with a fresh id and `permission` error; both sit in
  `tool` spans under the same parent as the `ModelEvent`.
- Extend `test_single_tool_call_returns_correct_result` (`:199`): one `tool`
  event with a fresh id, `approval == "not_required"`, `proposed is False`.
- Extend `test_sandbox_bridge_rejects_forged_host_tool_call` (`:620`): one
  denied event, no executed event, and the MCP error text unchanged.
- A tool that raises `TimeoutError("tool-specific timeout")`: the MCP error
  carries that text and the event carries the native timeout error.

Viewer, ts-mono: vitest cases for the coverage-keyed `showToolCalls` and
`recentInputMessages` rules over two fixtures: a bridged turn at the top
level mixing a paired host tool event and a scaffold-run call, and an
`agent` span containing the proposing `ModelEvent`, the host tool span and
event, and the next `ModelEvent` whose input carries the result message.
Assert: the scaffold-run call still renders inline, its result is still
surfaced, the host call is omitted inline and rendered once as a tool
panel with an empty child list followed by a sibling `tool` span node
holding its nested `SandboxEvent`, and navigation from the host result
message resolves to the host event inside the agent span. A native fixture
proves no change.

## Implementation plan

1. **Grant record carries the proposal and span**
   (`src/inspect_ai/agent/_bridge/types.py`,
   `src/inspect_ai/agent/_bridge/sandbox/types.py`,
   `src/inspect_ai/agent/_bridge/util.py`,
   `tests/agent/test_bridge_approval.py`). Add the `span_id: str | None =
   None` keyword to the base `AgentBridge.register_tool_execution_grants`
   hook and the sandbox override; add `call` and `span_id` to
   `_ToolExecutionGrant`, return the record from
   `consume_tool_execution_grant`, drop the policy early-return, reword
   the two warnings, add `_SpanCapturingSink` and the capture in
   `bridge_generate`, update `service.py:234` to the new return type.
   Rewrite `test_host_tool_grants_are_not_stored_without_approval_policy`;
   add the span-capture tests; confirm the in-process `bridge_generate`
   tests still pass.
2. **Span parent helper** (`src/inspect_ai/util/_span.py`, `tests/util/`):
   `parent_span()` with a test that a constructed event and a nested
   `span()` take the given parent and the previous value is restored.
3. **Extract the native error mapping** (`src/inspect_ai/model/_call_tools.py`,
   `tests/tools/test_call_tools.py`). Add `ToolCallFailure` and
   `tool_call_failure`, switch `call_tool_task` to it with no behaviour
   change, add the mapping test.
4. **Tool result media follow the logging policy**
   (`src/inspect_ai/log/_condense.py`, `tests/log/test_log_attachments.py`).
   Add `walk_tool_result`, call it from `walk_tool_event`, add the round-trip
   tests.
5. **Record host tool events** (new
   `src/inspect_ai/agent/_bridge/sandbox/host_tool.py`; `service.py`
   delegates; `src/inspect_ai/event/_tool.py` docstring for
   `metadata.bridge`; `util.py:365-369` docstring). Unit tests from the
   Testing section, including the event tree, cancellation counts (direct,
   outer, and ACP `cancel_current_turn`), RPC text preservation and trio.
6. **ACP mapping** (`src/inspect_ai/agent/_acp/event_mapping.py`,
   `tests/agent/test_acp/test_router_bridge_tools.py`). Pop `pending` in
   `_map_tool_event`, update docstrings, add the three tests.
7. **Docker tests and docs** (`tests/tools/test_tools_bridge.py`,
   `docs/agent-bridge.qmd` Transcript section and the bridged-tools section
   for the argument restriction, `CHANGELOG.md`).
8. **Viewer companion** (ts-mono, separate PR): coverage-keyed
   `showToolCalls` and tool-message hiding at the timeline level, with the
   two fixtures; then the submodule pointer bump in inspect_ai per
   `.agents/skills/land-ts-mono/SKILL.md`. Independent of steps 1 to 7;
   preferably lands first so the first release with host tool events has no
   mixed-turn regression.

Steps 1 to 7 are one inspect_ai PR (each step a commit). Step 8 is its own
PR.

## Open questions

1. **Error on an unproposed but executed call.** The task text says an
   unproposed call gets a fresh id and an error. Recommendation: no
   `error`; mark it with `metadata.bridge.proposed = false` only. `error`
   drives "failed" status in ACP, error styling in the viewer and
   `tool_event_error_type` in dataframes, all of which would then
   misreport a tool that ran and returned normally. If Ransom wants the
   anomaly louder, the alternative is a log-only
   `ToolCallError("unknown", "Host tool call matched no model tool call
   proposal")` with the successful result still recorded and returned.
2. **Record proposals without an approval policy?** Recommendation: yes
   (attribution and placement only; the scaffold sees no change). The
   strict alternative pairs only under a policy and leaves the default
   configuration with two ACP cards per host call.
3. **Reject non-object and over-deep arguments before execution.**
   Recommendation: yes, with the native bound and the native error text.
   The alternative (execute and record a placeholder) records something
   other than what ran. No known scaffold is affected.
4. **Denial error type.** Recommendation: `permission`, which renders today
   and matches how the native path types a `PermissionError`. `approval`
   would group denials with policy rejections in dataframes but is hidden by
   the viewer's tool panel unless a viewer change accompanies it.
5. **Sequencing with the viewer companion.** Recommendation: land the
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
- **Unifying the scaffold-facing error text with the native
  `ToolCallError` wording** (a `TimeoutError` reaches the scaffold as its
  own message today and keeps doing so).
- **Back-filling `ToolEvent.message_id`** when the scaffold's
  `ChatMessageTool` arrives, which needs a hooks-safe way to update a
  completed event.
- **Grants and proposals across checkpoint restore** (register the deque
  with the checkpointer).
- **ACP cancelable flag** for synthesised cards that turn out to be host
  executions; the router would need the bridge's registry to know at start
  time.
- **A viewer badge** rendering `metadata.bridge` (host execution, denied,
  unproposed) on the tool panel.
- **Host tool exceptions do not fail the sample** (the service converts
  them to RPC errors); unchanged here, worth a deliberate decision.
- **Scaffold-run tool calls** remain without `ToolEvent`s; the
  `in_bridge_model_generate` synthesis in ACP stays for them.
