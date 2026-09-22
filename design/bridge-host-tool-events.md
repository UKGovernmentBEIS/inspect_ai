# Record bridged host tool executions as `ToolEvent`s

Status: proposed, 2026-09-15. Issue: none (task from Ransom). Author: agent
(Claude), reviewed by Codex; see the PR.

All `path:line` references are to `main` at `472cf7dd2` (2026-09-22, which
includes #5464) unless a different tree is named. Viewer references are to
the `ts-mono` submodule at the commit that tree pins (`02f2c5ad`), under
`src/inspect_ai/_view/ts-mono/`. This design builds on PR #5428 (`bridge-host-tools-require-proposal`, head
`e5e3cab8f`, the head Ransom called stable on 2026-09-22), which makes
execution grants unconditional and resolves proposals against the tools the
scaffold declared by the content the bridge served for them; the grant
behaviour described here is #5428's at that head, cited by function name
rather than line.

## Why

`sandbox_agent_bridge(bridged_tools=...)` exposes host-side Inspect tools to
a sandboxed scaffold as MCP servers on the in-container model proxy. A
`tools/call` from the scaffold becomes a `call_tool` request in the bridge's
sandbox service, and the host runs the tool function in the Inspect process
(`src/inspect_ai/agent/_bridge/sandbox/service.py:225-292`). #4944 added
one-shot execution grants minted from an approved generation
(`src/inspect_ai/agent/_bridge/sandbox/types.py:91-163`); on `main` the
execution-edge check is disabled pending #5428 (`service.py:254-257`),
because scaffolds present bridged tools to the model under names the grant
resolution did not recognise, and #5428 re-enables it for every call, with
or without a policy, resolving proposals against the tools the scaffold
declared by the description the bridge served, unless the
server's `BridgedToolsSpec` sets `require_proposal=False`. #5464 (merged 2026-09-21) made the host call
validate arguments and classify exceptions as a native call does, failing
the sample on an unexpected one.

Nothing on this path writes a transcript event. The only trace of a host
tool execution is the `ModelEvent` of the generation that proposed it, if
one did; a denial (once #5428 lands) leaves a `warn_once` in the Python log
and nothing in the transcript. `in_bridge_model_generate()`
documents that bridged scaffolds emit no `ToolEvent` because they run their
own tools (`src/inspect_ai/agent/_bridge/util.py:365-369`). That reasoning
does not cover a tool Inspect itself executes on the host.

Host tool executions are actions Inspect takes on the sample's behalf. The
native path records every executed call, including rejected and failed
ones, as a `ToolEvent` (`src/inspect_ai/model/_call_tools.py:383-392`,
`:424-430`). The bridge path should record the same, so that the eval log,
the viewer, ACP clients, dataframes and scanners see what the host did and
when.

## Goals and non-goals

Goals:

- Every `call_tool` request produces exactly one `ToolEvent` in the sample
  transcript: executed, denied, or rejected (unknown server or tool,
  arguments that are not a JSON object or nest too deeply).
- An executed call carries the bridged server and tool (the tool name is
  the event's `function`), the function name as the model saw it (in
  `metadata.bridge.function`), the arguments as executed, the result as
  delivered to the scaffold (or the error), start and completion times,
  working time, and a marker that it ran on the host through the bridge.
- An executed call that consumed a grant carries the proposing
  `ToolCall.id` and is placed in the span of the proposing `ModelEvent`, so
  consumers pair it with the proposal the way they pair native
  `ToolEvent`s. A denied or rejected call gets a fresh id and an error.
  With #5428 the only unproposed call that executes is one on a server the
  eval opted out with `require_proposal=False`; it gets a fresh id and
  `metadata.bridge.grant = "exempt"`, with no `error`, since executing it
  is the eval author's stated intent.
- The event behaves like a native `ToolEvent` for live surfaces: pending
  while running, cancellable by the operator, visible to the execution
  observer, finalised exactly once by the host runner.
- Recorded results follow the eval's image-logging policy, as message
  content does, and string results are bounded by the eval's
  `max_tool_output` or the tool's own `ToolDef.max_output` when either is
  explicitly set; the native implicit 16 KiB default is not applied.
- No change to what the scaffold receives for calls that execute today,
  with two deliberate exceptions listed under Compatibility: arguments
  nested deeper than the native bound are rejected before execution (a
  non-object already fails #5464's schema validation), and a string result
  over an explicitly configured output limit is delivered truncated with
  the native wrapper text. The approval and grant decision, #5464's
  argument validation and its sample failure on an unexpected exception
  are unchanged.

Non-goals:

- Recording the scaffold's own tool executions (Bash, Read, Edit run inside
  the sandbox). Those remain visible only through `ModelEvent` inputs.
- The execution contract itself (which calls run): that is #5428. This
  design records what that contract decided.
- Dataclass and pydantic coercion of arguments (`tool_params`), or
  `ToolDef.viewer` support, for bridged host tools. #5464 validates the
  arguments against the tool's schema and then forwards them as sent; this
  design keeps that.
- Tool result review for host tools. Native `execute_tools` runs the
  `review` policies after a tool executes and before the model sees the
  result; the bridge path runs none, and this design does not change that
  (see "Not this design").
- A new event type or a new `ToolEvent` field.

## Current behaviour

### The call path

- The scaffold's MCP client posts `tools/call` to the in-container proxy,
  which forwards `server`, `tool` and `arguments` to the host service
  (`src/inspect_sandbox_tools/src/inspect_sandbox_tools/_agent_bridge/proxy.py:2207-2220`).
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
- `call_tool` (`service.py:225-292`) checks the server (`:247-248`) and tool
  (`:251-252`). The execution-grant check is disabled pending #5428
  (`:254-257`), so no call is denied on `main` today. It validates
  `arguments` against the tool's declared schema with `validate_tool_input`
  and raises `ToolParsingError` on a failure (`:260-264`), which covers a
  non-object, a missing or extra property and a wrong type; it then awaits
  `tool_fn(**arguments)` with the arguments as the scaffold sent them
  (`:265`; nesting is not bounded) and returns a plain string verbatim, MCP
  content blocks for image results, or `to_json_str_safe(result)` otherwise
  (`:280-290`). Nothing bounds the size of that result: the eval's
  `max_tool_output` and a tool's own `ToolDef.max_output` are not consulted,
  so a bridged `bash()` delivers its whole output where the native path
  would have truncated it.
- Exceptions (#5464). `call_tool` unwraps any task-group `ExceptionGroup`
  with `inner_exception` and classifies the result with `tool_call_error`
  (`:271-274`), the same function `execute_tools` uses. A mapped exception
  (one the model would see as a `ToolCallError` natively) simply propagates.
  An unmapped one is a bug in the eval's tool: `bridge.request_fail(inner_ex)`
  is called, so the bridge's monitor task raises it in the bridge task group
  (`bridge.py:283-294`) and the sample fails at once, as it does natively,
  subject to `fail_on_error` and retries; the original exception still
  propagates so the RPC unwinds. In both cases the exception that leaves
  `call_tool` is the original object.
- Any exception becomes an RPC error string `Error calling method call_tool:
  <str(ex)>` (`util/_sandbox/service.py:562-581`; tracebacks are
  deliberately kept host-side), which the proxy returns as JSON-RPC error
  `-32603` (`proxy.py:2229-2232`). The message the scaffold sees is the
  exception's own text: a `TimeoutError("tool-specific timeout")` reaches
  it as that string. `LimitExceededError` is special-cased: the service
  calls `active.limit_exceeded(ex)` and answers an error
  (`util/_sandbox/service.py:552-560`). For an unmapped exception the
  teardown #5464 triggers may pre-empt delivery of the reply; the scaffold's
  turn is over either way.

### Grants

On `main` (`472cf7dd2`):

- `_ToolExecutionGrant(server, tool, arguments)` (`types.py:206-216`) is
  minted per approved call in `register_tool_execution_grants`
  (`types.py:91-139`), called from `bridge_generate` after approval and
  before the response is returned to the scaffold (`util.py:600-604`). The
  method returns early when no approval policy is active (`types.py:107`).
- `consume_tool_execution_grant` returns a `bool` (`types.py:141-163`) and
  is not called: `call_tool`'s grant check is commented out pending #5428
  (`service.py:254-257`), so approved and unapproved calls both execute.
- The grant deque is bounded at 1024 entries (`types.py:33`, `:76-78`) and
  is not registered with the checkpointer, so grants do not survive a
  checkpoint restore.

After #5428 (the tree this design targets, head `e5e3cab8f`):

- `AgentBridge.register_tool_execution_grants(calls, tools)` is the hook,
  with `tools` the declarations the scaffold made to the model in the
  request that produced the response. `bridge_generate` builds that list
  from two sources: the attempt's `tools` as generated with (a filter may
  have rewritten them), plus `declared_in_input(input_messages)`, the tools
  a Responses scaffold declared inside the conversation rather than the
  request's tools array (tools discovered through `tool_search`, which the
  model sees in a `tool_search_output` result), extracted from the input the
  model actually generated from. It passes `[*tools, *declared_in_input(...)]`
  as one sequence; the in-input declarations take part only in resolving
  grants and are never sent to the model. The base is a no-op and
  `AgentBridge.grants_tool_execution` is `False`; `SandboxAgentBridge` sets
  it `True` and overrides the hook.
- The override records grants for every bridged-tool call in every response
  handed to the scaffold, whether or not a policy is active, except for
  servers in `SandboxAgentBridge.proposal_exempt_servers` (those registered
  with `BridgedToolsSpec(require_proposal=False)`, called "exempt servers"
  below), for which no grant is stored. A "server" throughout is one
  `BridgedToolsSpec`: the named MCP server the in-container proxy exposes at
  `/mcp/<spec.name>` for that spec's tools (`bridge.py:271-280`), not the
  model or the sandbox.
- Resolution is by served content (`_proposed_call`,
  `_resolve_by_served_content`, against `SandboxAgentBridge.served_tools`,
  the `ToolInfo` the bridge served per bridged tool in `tools/list`): the
  called name is ignored, because every scaffold renames MCP tools under its
  own scheme. The call's declaration (looked up by name among the
  declarations; a call to a name the scaffold never declared denotes
  nothing) is matched to a bridged tool by the served description alone:
  equality after trimming whitespace (an empty description matches every
  bridged tool served without one), or failing an exact match, a truncation
  (`_is_truncation_of`: the declared and served texts share a common prefix
  of at least 64 characters and whatever the declared text carries beyond
  it, an ellipsis or a `[truncated]` marker, is at most 24 characters). An
  exact match wins even when that description is a prefix of another
  bridged tool's; a truncated declaration that could refer to several tools
  denotes all of them. Schemas are not consulted, because scaffolds rewrite
  them, so two tools with the same description and different schemas are
  indistinguishable. Failing a content match, the call may be a dispatcher
  call (`_dispatched_call`): recognised
  by its function name first, `call_mcp_tool`, and only then by its argument
  shape (string `ServerName` and `ToolName` naming a registered bridged tool
  and an object `Arguments`), denoting that tool with the inner `Arguments`.
  The name gate is what stops an ordinary call whose arguments happen to
  carry those fields from minting a grant for, or borrowing the approval
  policy of, a bridged tool; approval and grant resolution share the one
  function so they cannot disagree. Tools that cannot be told apart (a
  shared description, whatever their schemas; `warn_indistinct_tools` names
  them at setup) each get a grant bound to the call's arguments, so one
  proposal authorises one execution of each of them.
- This is scaffold-agnostic. #5428 verified that Claude Code, Codex CLI
  (both its naming forms, and tools it discovers through `tool_search`),
  Gemini CLI, OpenCode, Kimi Code and Antigravity forward the MCP
  description to their models unchanged (or truncated), so no per-scaffold
  name reproduction lives in core any more; a scaffold that rewrote
  descriptions beyond truncation would have its proposals unrecognised and
  its host calls denied.
- Pinned by #5428's tests in `tests/agent/test_bridge_approval.py`, which
  PR C carries forward unchanged: `test_tool_discovered_through_tool_search_is_granted`
  (an in-input declaration mints a grant),
  `test_ordinary_call_with_dispatcher_shaped_arguments_mints_no_grant` and
  `test_dispatcher_shaped_arguments_do_not_borrow_another_tools_policy` (the
  name gate), `test_dispatcher_call_grants_the_named_target_with_its_arguments`,
  the resolver tests `test_declared_schema_does_not_affect_matching`,
  `test_same_description_and_schema_grants_each_once`,
  `test_exact_match_wins_over_a_prefix_match`,
  `test_truncation_matching_two_tools_grants_both` and
  `test_served_description_that_prefixes_another_grants_both_when_truncated`
  (PR C must not narrow the population any of these grant), and
  `test_opted_out_server_stores_no_grants` (which this design inverts, see
  below).
- `call_tool` denies unless the server is exempt or a grant is consumed;
  `tool_approval_required()` is removed. The denial is still a
  `PermissionError`, now reading "Host tool call '<server>/<tool>' was not
  proposed by the model in a bridged generation (a bridged host tool runs
  once per proposed call)".
- The grant record (`server`, `tool`, `arguments`), `consume`'s `bool`
  return, the one-shot oldest-first matching and the bounded store are
  unchanged.

### Native `ToolEvent` mechanics the design mirrors

- Two-phase emission. The pending event is constructed per call before any
  tool span exists (`_call_tools.py:473-479`), so `BaseEvent.model_post_init`
  stamps it with the enclosing span (`src/inspect_ai/event/_base.py:35-48`).
  It is then emitted inside `span(name=call.function, type="tool")`
  (`:838-839`; denials at `:728-731`), and finalised with `_set_result` and
  `transcript()._event_updated(event)` (`:552-567`). The resulting shape,
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
  (`_call_tools.py:472`, `:503`).
- Exceptions from the tool body map to `ToolCallError` types
  (`_call_tools.py:107-190`): timeout, unicode_decode, parsing (embedded
  null byte), sandbox_unavailable, permission, file_not_found,
  is_a_directory, limit, parsing, approval, unknown (`ToolError`). The
  mapping rewrites messages (a `TimeoutError` becomes "Command timed out
  before completing."). Anything else sets `failed=True` and propagates.
- A per-call cancel scope is exposed through `event._set_cancel_fn`
  (`:541`); operator cancel records `ToolCallError("timeout", "Command
  timed out before completing.")` (`:549-556`).
- The execution observer is told about the in-flight call
  (`:301`, `:408`), which is how ACP's turn cancel finds and marks it.
- After a successful execution the tool result reviewers run
  (`_apply_tool_review`, `:357-368`, `:798`): the `review` policies from
  `Task(review=)`, `eval(review=)` and `react(review=)` see the call and
  its result before the model does and can continue, terminate or
  escalate. Nothing on the bridge path calls them; `_bridge/_approval.py`
  applies approvers only.
- String results are truncated before they reach the model or the event:
  `truncate_tool_output` (`_call_tools.py:1358-1382`) applies the tool's
  `ToolDef.max_output` if declared, else `active_generate_config().max_tool_output`,
  else 16 KiB, replaces the text with a wrapper ("The output of your call
  to X was too long to be displayed. Here is a truncated version: …") and
  the event records `truncated=(raw_bytes, limit)` (`:363-375`). List
  results (`list[Content]`) are not truncated. `ToolDef(tool)` recovers a
  `max_output` declared on the tool (`src/inspect_ai/tool/_tool_def.py:97`).
- Model-provided arguments are bounded to `MAX_TOOL_CALL_ARGUMENTS_DEPTH`
  (100) before execution (`_call_tools.py:791`, `:1348-1360`) because
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
  (`event_mapping.py:294`). Two implementers exist in the Inspect
  ecosystem, both in inspect_swe (`b2c1bf0`), both stamping `event.span_id`
  in `on_pending` to attribute a sub-agent's generations to a span they
  opened, both resolving the outer span at emission time so it follows the
  checkpointer's rotating span, and neither emitting `ToolEvent`s:
  - claude_code's `LiveConsumer`
    (`src/inspect_swe/_claude_code/_events/live_consumer.py:89`) opens
    `agent-<tool_use_id>` in `on_complete` for each Task call, attributes a
    later call by matching its first user message against pending Task
    prompts, and closes the span when Claude Code's JSONL reports the Task's
    `tool_result` (`:282-301`); `reset()` closes any still-open spans
    between Claude Code attempts.
  - codex_cli's `CodexConsumer`
    (`src/inspect_swe/_codex_cli/_events/consumer.py:80`, installed at
    `codex_cli.py:361-387`) opens `agent-<spawn call_id>` in `on_complete`
    for each `spawn_agent` call, attributes a later call by its
    `agent_message` recipient (V2) or by spawn-prompt substring (V1), and
    closes the span in a later `on_pending` when that request's input shows
    the thread completed (a wait/close status or a `FINAL_ANSWER`), in
    `on_complete` for an explicit `close_agent`, or in `reset()` between
    Codex attempts.
  Installing a sink also disables partial-output publishing
  (`_model.py:1394-1401`).
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
`ModelEvent`. Pairing and placement come from the grant record, which #5428 already
writes for every proposal and which this design extends to hold the
proposing `ToolCall` and that event's span. The denial decision is #5428's
and is unchanged.

```
scaffold ──tools/call──▶ proxy ──call_tool RPC──▶ service task
                                                  │ resolve server/tool; arguments must be an object within the depth bound
                                                  │ grant = consume_tool_execution_grant(...)
                                                  │ deny if grant is None and the server requires a proposal (#5428)
                                                  │ under parent_span(grant.proposal.span_id):
                                                  │   ToolEvent(id = grant.proposal.take_id() | fresh, pending)   ← stamped with the parent
                                                  │   span(type="tool"): transcript()._event(event)
                                                  │     observer.track_tool_call + CancelScope
                                                  │     result = await tool_fn(**arguments)          ← nested events inside the tool span
                                                  │ event._set_result(...); _event_updated (once)
                                                  ▼ return serialized result / raise the original exception
```

### Grant record carries the proposal and its span

`src/inspect_ai/agent/_bridge/sandbox/types.py`, on top of #5428:

```python
class _Proposal:
    """One model tool call that minted grants; shared by every grant it minted."""
    __slots__ = ("call", "span_id", "paired")
    call: ToolCall          # id, function as the model saw it, view
    span_id: str | None     # span to place executions under when it differs from
                            # the span current at registration (a sink
                            # re-attributed the proposing ModelEvent); None means
                            # "the span current when the call executes"
    paired: bool            # whether an execution has already taken call.id

    def take_id(self) -> str:
        """The event id for the next execution of this proposal: call.id the
        first time, a fresh shortuuid after."""

class _ToolExecutionGrant(NamedTuple):
    server: str
    tool: str
    arguments: dict[str, Any]
    proposal: _Proposal
```

- `register_tool_execution_grants(calls, tools, *, span_id: str | None =
  None)` keeps #5428's two positional parameters and adds the keyword, on
  both the base `AgentBridge` hook (`src/inspect_ai/agent/_bridge/types.py`)
  and the sandbox override; `bridge_generate` passes the same declarations
  list it builds today (the attempt's filtered `tools` plus
  `declared_in_input(input_messages)`) and the captured span, so a tool
  discovered through `tool_search` still mints a grant and the dispatcher
  name gate is untouched. The base change is required
  because `bridge_generate` is shared by in-process and sandbox bridges and
  calls the hook for every generation, including ones without tool calls; a
  keyword only the override accepted would raise `TypeError` on every
  in-process generation. The override builds one `_Proposal` per call it
  resolves and stores a reference to it on every grant that call mints
  (one for a normal call, several for indistinguishable targets), so the
  proposal record lives exactly as long as its grants: it is dropped with
  the last grant consumed or evicted, and no state outside the bounded
  deque grows with the number of host calls. Registration policy
  (served-content resolution, unconditional, one grant per indistinct
  target, bounded store) is #5428's and is not changed here. For Antigravity the stored
  `call` is the `call_mcp_tool` dispatcher call, so `metadata.bridge.function`
  reads `call_mcp_tool` and `view` is the dispatcher's; `arguments` on the
  event are the inner `Arguments` as executed, which is what the grant
  binds.
- One proposal, several grants. When #5428 registers a grant for each of
  several indistinguishable targets, every one of those records carries the
  same proposing `call`, and if the scaffold executes more than one of them
  the events must not share an id: `ToolEvent.id` is what ACP's card state,
  the viewer's approval and navigation maps, the control server's
  cancellation and `InterruptEvent` cross-references key on. The "first
  execution takes the proposing id" state is the `paired` flag on the
  `_Proposal` those grants share: on consumption, if `grant.proposal.paired`
  is `False`, the event takes `proposal.call.id` and the flag is set;
  otherwise the event gets a fresh id. Nothing is kept once the proposal's
  last grant is gone, so a long eval retains no pairing state per call, and
  a later proposal that happens to reuse an earlier call id is a new
  `_Proposal` with its own flag. `metadata.bridge.proposal_id` carries
  `proposal.call.id` on every consumed grant, so the second and later
  executions still name the proposal they came from, and placement under
  the proposal's span applies to all of them. Like the grants, the flag is
  not tracked across a checkpoint restore. This case is expected to be
  rare: one proposal names one function, and it arises only when an eval
  bridges two servers whose tools share a description and the scaffold
  executes on both.
- `consume_tool_execution_grant(server, tool, arguments) ->
  _ToolExecutionGrant | None` returns the matched record instead of `bool`.
  Matching is unchanged (`_json_equal`, one-shot, oldest first).
- Exempt servers. #5428 stores no grants for a `require_proposal=False`
  server, which means a model-proposed call on such a server could never
  pair with its proposal. This design therefore stores grants for exempt
  servers too, purely for attribution: `call_tool` consumes a match when
  there is one and executes regardless. The store stays bounded and every
  entry is still consumable; the only cost is that an exempt server's never-
  executed proposals occupy slots until evicted. #5428's
  `test_opted_out_server_stores_no_grants` inverts accordingly (decision:
  Ransom, 2026-09-15).
- Pairing limits. Attribution inherits #5428's matching, so it is exact for
  every scaffold that forwards the served description unchanged or
  truncated (the six #5428 verified: Claude Code, Codex CLI in both its
  naming forms, Gemini CLI, OpenCode, Kimi Code, and Antigravity through
  its dispatcher) and absent for a scaffold that rewrites descriptions (its
  calls are denied, or on an exempt server execute unpaired). One case can
  attach the wrong proposal's `id` and span to an event while `server`,
  `tool` and `arguments` stay exact: two proposals in flight for the same
  tool with identical arguments are consumed in proposal order rather than
  the scaffold's execution order, so their ids may be swapped between two
  otherwise identical events. A scaffold-local tool can only mint a grant
  for a bridged tool by carrying that tool's served description, which is
  not a naming collision but a duplicated tool; the bridged-tools docs ask
  for unique names and #5428's `warn_indistinct_tools` flags duplicated
  descriptions at setup.

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
- After approval, `register_tool_execution_grants(calls, declarations,
  span_id=captured)`, `declarations` being the `[*tools, *declared_in_input(...)]`
  list #5428 builds today, where `captured` is the remembered span if it
  differs
  from `current_span_id()` at that moment, else `None`. Storing only a
  differing span keeps executions under the checkpointer's rotating
  `checkpoint N` span when no re-attribution happened: a stored checkpoint
  id would otherwise pin a later execution under a span that has since
  closed. Both known sinks resolve their outer span from `current_span_id()`
  at emission time for the same reason, so a main-agent proposal captures
  `None` under either, and a sub-agent proposal captures `agent-<id>`.
- Lifetime of a captured span, per sink. `LiveConsumer` closes
  `agent-<tool_use_id>` when Claude Code reports the Task's `tool_result`
  (`live_consumer.py:282-301`), which Claude Code emits only after the
  sub-agent has finished, so a sub-agent's host calls execute while its
  span is open. `CodexConsumer` closes `agent-<spawn call_id>` in the
  `on_pending` of a later request whose input reports the thread complete
  (`consumer.py`, `_close_thread` from `on_pending`), in `on_complete` on an
  explicit `close_agent`, or in `reset()` between Codex attempts; a
  sub-agent's host calls precede the final answer that completes its
  thread, so again the span is open while they execute. The residual case
  under both is a call issued after the span closed: a retry of an
  already-executed proposal (denied by #5428 unless the server is exempt),
  or a stale proposal after `reset()` on an attempt restart. If it does
  happen, both event trees nest by `span_id` (viewer
  `transcript/transform/treeify.ts:231`, Python
  `src/inspect_ai/event/_tree.py:71-89`), so the event still lands in its
  proposal's span node; only the stream order shows it after the
  `span_end`. The ACP sub-agent filter classifies by stream order in every
  case (below), so the stored id does not change what ACP does. A
  closed-span fallback would need the bridge to track `SpanEndEvent`s
  through a transcript subscription; not added (see "Not this design").

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
method table (`service.py:113`) and the existing tests' import
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

1. **Resolve.** Two distinct rejections, each keeping today's `ValueError`
   text (`service.py:247-252`). Unknown server: record a completed event
   with `error=ToolCallError("parsing", "Unknown bridged tools server:
   <server>")`, fresh id, `function=tool`, `metadata.bridge.server` the
   name as sent, then raise `ValueError` with that same message. Unknown
   tool on a known server: the same with `error=ToolCallError("parsing",
   "Unknown tool '<tool>' in server '<server>'")`. Both mirror the native
   "Tool X not found" parsing error (`_call_tools.py:799`); the messages
   the scaffold receives are byte-identical to today's. Resolution runs
   before any look at `arguments`, so on a request that is invalid in both
   ways the resolution error wins; `ToolEvent.arguments` requires a dict, so
   when `arguments` is not one the event records `{}` and the error message
   is unchanged (the shape is not described, to keep the wire text
   byte-identical).
2. **Check arguments.** Two checks, both recorded as a completed `parsing`
   event with a fresh id and raised as `ToolParsingError` so the scaffold
   receives the same model-facing RPC error #5464 produces today. First the
   depth bound: `arguments` must pass `_exceeds_max_depth`
   (`_call_tools.py:1413`), else the event has `arguments={}` and the
   native depth message (`_max_depth_parse_error`), and the call is rejected
   before validation. **This is the one behaviour change here**: today a
   deeper-than-100 object is validated and executed. The bound is the one
   native applies to model-provided arguments for the same reason
   (`_call_tools.py:1397-1409`): the recorded arguments enter the log, and
   unbounded nesting crashes sample logging (decision: Ransom, 2026-09-15).
   Then #5464's schema validation, unchanged: `validate_tool_input` against
   `ToolDef(tool_fn).parameters` (`service.py:260-264`); a failure records
   the validation message on the event and raises as today. `ToolEvent.arguments`
   is a dict, so an object-shaped failure (a missing or extra property, a
   wrong type) records the arguments as sent, and a non-object (a list, a
   string) records `{}`; the message the scaffold receives is unchanged
   either way.
3. **Match the proposal.** `grant = bridge.consume_tool_execution_grant(server,
   tool, arguments)`.
4. **Deny.** If the server is not in `bridge.proposal_exempt_servers` and
   `grant is None` (#5428's condition): record a completed event with fresh
   id, `function=tool`, `error=ToolCallError("permission", <#5428's message:
   "Host tool call '<server>/<tool>' was not proposed by the model in a
   bridged generation (a bridged host tool runs once per proposed call)">)`,
   `failed=None`, and raise the same `PermissionError` #5428 raises, keeping
   its `warn_once`. `permission` is the type the native path assigns to a
   `PermissionError` raised by a tool body (`_call_tools.py:165-169`) and it
   renders in the viewer, which suppresses `approval`-typed errors expecting
   a paired `ApprovalEvent` that a denial does not have (no approver ran).
   The type is also the accurate one: the agent has no permission to run a
   host tool the model did not call; approval was never in question
   (decision: Ransom, 2026-09-15).
5. **Execute.**

   ```python
   with parent_span(grant.proposal.span_id if grant else None):
       event = ToolEvent(                                  # stamped with the parent span
           id=grant.proposal.take_id() if grant else uuid(),  # proposing id once per proposal, else fresh
           function=tool,                                  # the registered ToolDef name, always
           arguments=arguments,                            # as executed
           view=grant.proposal.call.view if grant else None,
           pending=True,
           metadata={"bridge": {..., "function": grant.proposal.call.function if grant else None,
                                "proposal_id": grant.proposal.call.id if grant else None}},
       )
       waiting_start = sample_waiting_time()
       async with span(name=tool, type="tool"):            # parent = the event's span
           transcript()._event(event)
           with observer.track_tool_call(event.id, event):
               try:
                   with anyio.CancelScope() as scope:
                       event._set_cancel_fn(scope.cancel)
                       result = await tool_fn(**arguments)
               except anyio.get_cancelled_exc_class():
                   finalise(error=ToolCallError("cancelled", ...)); raise   # outer cancel only
               except Exception as ex:
                   inner_ex = inner_exception(ex)                          # as #5464
                   mapped = tool_call_error(inner_ex, tool)
                   if mapped is None:
                       finalise(failed=True)                                # native shape
                       bridge.request_fail(inner_ex)                        # as #5464
                   else:
                       finalise(error=mapped.error, result=mapped.result)
                   raise                                                    # the original
           if scope.cancel_called:
               finalise(error=ToolCallError("timeout", ...))
               raise ToolError("Command timed out before completing.")
           finalise(result=result)
   ```

   `observer` is `sample_active().execution_observer` or the null observer,
   as in `_call_tools.py:289-296`. `finalise` is
   `event._set_result(result=..., truncated=None, error=..., waiting_time=
   sample_waiting_time() - waiting_start, agent=None, failed=..., message_id=
   None, agent_span_id=getattr(tool_fn, "agent_span_id", None))` followed by
   `transcript()._event_updated(event)`; it runs exactly once per event.
   The per-call scope's own cancellation is swallowed at the `with
   CancelScope` exit and never reaches the `except`, so the operator-cancel
   path publishes a single `timeout` update; an outer cancellation (bridge
   teardown, sample limit) propagates through the scope to the `except` and
   publishes a single `cancelled` update.
6. **Return** the serialized result as `service.py:280-290` does today,
   except that a string result over the output limit is the truncated
   wrapper text recorded on the event.

Single-shot events (steps 1, 2, 4) have no proposal, so they are
constructed under the span current in the service task, given
`pending=None`, finalised with `_set_result(..., waiting_time=0.0)` and
recorded once with `transcript()._event(event)` inside their own `tool`
span, the shape the native denial path produces (`_call_tools.py:777-780`).

### The recorded result

`result` is the `ToolResult` the tool returned, massaged as the native path
does for the event (`_call_tools.py:333-382`): a `str` verbatim; a single
`Content` wrapped in a list; a list of `Content` as is; anything else as
`to_json_str_safe(result)`, the string the bridge sends today
(`service.py:290`).

A string result is then bounded as native bounds it, but only when a limit
was configured: `limit = ToolDef(tool_fn).max_output` if declared, else
`active_generate_config().max_tool_output` if set (the service task inherits
the eval's config; the `ToolDef` lookup is the one `list_tools` already
performs per request, `service.py:186`). When `limit` is `None` nothing is
truncated, so an eval that never set a limit delivers and records the whole
result exactly as today; the native path's implicit 16 KiB fallback is
deliberately not applied to bridged tools, because it would silently change
trajectories for existing bridged evals with large-output tools (decision:
Ransom, 2026-09-15). When a limit applies,
`truncate_tool_output(event.function, content, limit)` produces the wrapper
text, which is both what the scaffold receives over MCP and what the event
records, with `truncated=(raw_bytes, limit)`; otherwise `truncated=None`.
Delivered and recorded results are always the same bytes. List results are
not truncated, as native. This is the second scaffold-facing change (see
Compatibility); for evals that configure a limit it also bounds the inline
copy of the result in the log, which `walk_tool_event` never condenses into
an attachment.

Condensing long text results into attachments would not bound the log
instead: attachments are stored in the same log file, and the scaffold's own
copy of the result, the `ChatMessageTool` it sends back in the next request,
stays inline text in the message pool (`messages_attachment_fn` handles
images only, `_condense.py:442-458`), so nothing would deduplicate. The size
bound for a bridged tool's output is a configured `max_tool_output` or
`ToolDef.max_output`; without one the event holds one more copy of a result
the log already carries.

### Error mapping

The exception-to-`ToolCallError` mapping is `tool_call_error` in
`src/inspect_ai/model/_call_tools.py:107-117`, landed by #5464 (merged
2026-09-21, `d109dc168`), which factored it out of the `except` chain in
`call_tool_task` so that `execute_tools` (`:320-331`) and the bridge's
`call_tool` (`service.py:271-274`) classify with one definition:

```python
class MappedToolCallError(NamedTuple):
    error: ToolCallError      # the error reported in the tool message
    result: ToolResult | None # output the model still receives (e.g. truncated
                              # output), or None to leave the result as is

def tool_call_error(ex: Exception, function: str) -> MappedToolCallError | None:
    ...  # None: the exception is the eval's fault and the sample fails
```

#5464 also settled what happens over the bridge: a mapped exception
propagates as the RPC error the scaffold reads as tool output, an unmapped
one is signalled through `bridge.request_fail(inner_ex)` so the sample fails
as it would natively, and in every case the original exception is what
leaves `call_tool`, so the sandbox service dispatcher sees what it saw
before (a bare `LimitExceededError` still reaches its limit branch,
`util/_sandbox/service.py:552-560`). This design keeps all of that and adds
the event:

- Mapped exception: `error=mapped.error`, `result=mapped.result` when it is
  not `None` (a timeout's or output-limit's truncated output), else the
  result stays `""`; `failed=None`; re-raise the original. The event shows
  the native wording ("Command timed out before completing.") while the
  scaffold still sees `str(ex)`, as today; the two are deliberately not
  unified, because changing the wire text is out of scope.
- `LimitExceededError`: mapped to `limit` by `tool_call_error`; re-raise the
  original so the dispatcher still calls `active.limit_exceeded(ex)` for a
  bare one.
- Unmapped exception: `failed=True`, `error=None`, the native shape
  (`_call_tools.py:326-331`), then `bridge.request_fail(inner_ex)` exactly
  where #5464 calls it (after the event is finalised, before the re-raise),
  and re-raise the original. The sample fails through `_monitor_failure`
  (`bridge.py:283-294`); the message reaches the log as the sample error,
  so it is not duplicated onto the event.
- Operator cancel (`scope.cancel_called`): `error=ToolCallError("timeout",
  "Command timed out before completing.")`, `failed=None`, the contract at
  `_call_tools.py:598-605`; raise `ToolError` with that message. This path
  does not exist today (there is nothing to cancel), so the message is new
  rather than changed; `ToolError` is mapped, so it does not fail the sample.
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
    "function": "mcp__calc__calculator_add",
    "proposal_id": "toolu_01",
    "grant": "consumed"
  }
}
```

- `server`, `tool`: the `BridgedToolsSpec` name and the tool name within it.
  `ToolEvent.function` is always `tool`, the registered `ToolDef` name, for
  every outcome (executed, denied, rejected), so a scanner or dataframe
  grouping by `function` sees one spelling per host tool, and ACP's
  kind mapping (`_tool_kind_for(event.function)`) sees the bare name.
- `function`: the model-facing name the proposing call used, which
  scaffolds rewrite (Claude Code's `mcp__calc__calculator_add`, OpenCode's
  `calc_calculator_add`, Antigravity's `call_mcp_tool`, and so on); `null`
  when no proposal matched. This is "the function name as the model saw
  it", kept out of `ToolEvent.function` so the same tool is not recorded
  under two spellings in one transcript.
- `proposal_id`: the proposing `ToolCall.id` on every consumed grant. It
  equals `ToolEvent.id` except for the second and later executions of a
  proposal that #5428 granted to several indistinguishable targets, which
  get a fresh `id`; `null` when no proposal matched.
- `grant`: `"consumed"` (a proposal matched: the event sits in that
  proposal's span, `proposal_id` names it, and `id` is the proposing call's
  id for the first execution of that proposal), `"denied"` (server requires
  a proposal and none matched), `"exempt"` (server registered with
  `require_proposal=False`, no proposal matched, executed anyway), or
  `null` for events recorded before the grant check (unknown tool, bad
  arguments). Approval decisions are not repeated here; they are already
  `ApprovalEvent`s paired by call id.

`metadata` is already in the log schema and the generated TypeScript types
(`metadata?: {[key: string]: unknown} | null`), so no type generation is
needed (see `design/type-generation-pipeline.md`). The key is documented in
the `ToolEvent` docstring and in `docs/agent-bridge.qmd`.

### Where the event lands: span and sink

- A paired execution is placed under the span the proposing `ModelEvent`
  was recorded in, whether that span was the task's current span (no sink,
  or a sink that attributed to the current span) or one a sink assigned
  (claude_code and codex_cli sub-agents). The `ToolEvent` therefore sits at the same
  timeline level as the `ModelEvent` that proposed it and as the later
  `ModelEvent` whose input carries its result, which is what the viewer's
  per-level pairing (`resolveMessageToEvent.ts:223-236`) and the
  coverage-keyed rules below require.
- Both consumers that build a tree from the flat event list nest by
  `span_id` (`treeify.ts:231`, `_tree.py:71-89`), so the placement is
  what determines where the event appears, independent of where in the
  stream the service task happened to emit it.
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
panel. A host call with no nested events shows only the panel: the viewer
drops span nodes with no children (`transform/treeify.ts:344-353`), so no
extra span row appears for the common case. The timeline turns a `tool` span that contains model events into a
tool-spawned agent (`transcript/timeline/core.ts:989`), the same
classification a native tool that generates gets.

### Message linkage

`ToolEvent.message_id` is the id of the `ChatMessageTool` the model saw
(`_call_tools.py:561`). For a host call the scaffold builds that message
itself and sends it back in a later request, where `apply_message_ids`
assigns an id by content hash (`util.py:894-902`,
`src/inspect_ai/agent/_bridge/types.py:271-295`). That id does not exist
when the event is finalised, so `message_id` is `None`. Consumers cope: the
viewer's tool label lookup falls back to the tool id
(`transcript/ToolEventView.tsx:94-98`), and messages-tab navigation from a
tool-role message resolves through `tool_call_id` at the same level
(`transcript/resolveMessageToEvent.ts:310-333`), so a paired host event is
now the navigation target. Back-filling `message_id` when the message
arrives would need a second `_event_updated` on a completed event, which
re-delivers it to hooks; that is left out (see "Not this design").

`agent` is `None` (bridged tools are not handoffs). `agent_span_id` mirrors
`_call_tools.py:843`.

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
  arrives in the next input. The card keeps the title the synthesised start
  gave it from the model-facing name; the real event's `function` (the
  registered tool name) only feeds the update's content and kind. Today the ordering would be: synth start,
  update (real event pending), update (real event completed), update
  (message settle); after the change the last update is gone.
- A second execution of a multi-target proposal carries a fresh id, so it
  maps as its own start and update while the first execution updated the
  synthesised card; a client that reads `metadata.bridge.proposal_id` can
  group them, ACP itself does not. The same holds on replay.
- Unpaired host events (fresh id) map as their own start and update. With
  #5428 an unmatched call executes only on an exempt server; a proposal that
  failed to match there (ambiguous name, arguments the scaffold altered)
  keeps its synthesised card, which settles from the `ChatMessageTool` as
  today, so that case shows two cards. Accepted: exempt servers give up the
  correspondence guarantee by definition.
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
panel with the permission message. For a proposal that executed on several
indistinguishable targets, the approval pairs with and navigation from the
result message resolves to the first execution (the one carrying the
proposing id); later ones render as ordinary tool panels whose
`metadata.bridge.proposal_id` names the proposal.

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
cosmetic choice. The companion lands with the Python change, so no release
shows the regression above; bridged turns without host calls are unchanged
either way.

### Outcomes, summarised

| Outcome | `id` | `metadata.bridge.function` | `error` | `failed` | `metadata.bridge.grant` | RPC/MCP result to scaffold |
|---|---|---|---|---|---|---|
| Executed, grant consumed | proposing `ToolCall.id` (fresh, with `metadata.bridge.proposal_id`, for a second execution of the same proposal) | as the model saw it | mapped failure or `None` | `True` only for an unmapped exception (the sample then fails, #5464) | `consumed` | unchanged; on failure the original exception text |
| Executed on an exempt server, no grant | fresh | `null` | as above | as above | `exempt` | unchanged |
| Executed, string result over a configured output limit | as executed | as executed | `None` | `None` | as executed | **changed**: the native truncation wrapper text; event `truncated=(raw, limit)` |
| Denied (server requires a proposal, none matched) | fresh | `null` | `permission` | `None` | `denied` | unchanged from #5428 (`PermissionError` text) |
| Unknown server | fresh | `null` | `parsing` | `None` | `null` | unchanged ("Unknown bridged tools server: <server>") |
| Unknown tool on a known server | fresh | `null` | `parsing` | `None` | `null` | unchanged ("Unknown tool '<tool>' in server '<server>'") |
| Arguments fail #5464's schema validation | fresh | `null` | `parsing` | `None` | `null` | unchanged (`ToolParsingError` text) |
| Arguments nested over 100 deep | fresh | `null` | `parsing` | `None` | `null` | **changed**: the native depth `ToolParsingError` instead of execution |
| Tool raised `LimitExceededError` | as executed | as executed | `limit` | `None` | as executed | unchanged (limit handling and error text) |
| Operator cancel | as executed | as executed | `timeout` | `None` | as executed | new: MCP error "Command timed out before completing." |
| Bridge teardown mid-call | as executed | as executed | `cancelled` | `None` | as executed | none (request abandoned, as today) |

`ToolEvent.function` is the registered tool name in every row.

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
  place the event itself, but widens a `ModelEvent`-only protocol whose two
  implementers live outside this repo (inspect_swe's `LiveConsumer` and
  `CodexConsumer`). Reading the span the sink assigned
  through a private wrapper gives the same placement without changing the
  protocol, so that is what the design does.
- **Placing every host event under the service task's current span.** Zero
  extra machinery, but a sub-agent's host call would sit one level above
  its proposal and result, where the viewer's per-level pairing and
  coverage rules cannot see it (the per-level map at
  `resolveMessageToEvent.ts:223-236`). Rejected.
- **Delivering the full result and recording it truncated**, or the
  reverse. Either way the event would say something other than what the
  scaffold received, which defeats the record. Truncating at the execution
  edge keeps them identical and is what the eval's `max_tool_output` was
  set to do.
- **Not truncating at all** (round-1 text). Keeps the wire bytes identical
  for large results, but ignores limits the eval author set for these
  tools. Rejected.
- **Applying the native implicit 16 KiB default** as well as configured
  limits. Full parity with native, but a silent change to the trajectories
  of every existing bridged eval whose tools return more than 16 KiB and
  whose author never set `max_tool_output` because it did not apply to
  them. Rejected in favour of honouring only explicit limits (decision:
  Ransom, 2026-09-15).
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
- **Scaffold-facing behaviour.** Two cases behave differently: arguments
  nested deeper than 100 containers (today: validated and executed; after:
  rejected with the native depth `ToolParsingError`, an MCP `-32603` error
  no known scaffold triggers), and a string result larger than an
  explicitly configured limit (today: delivered whole; after: the native
  truncation wrapper when the eval set `max_tool_output` or the tool
  declares `ToolDef.max_output`; no implicit default). The second only
  affects evals that configured a limit, which now applies to their bridged
  tools as it already applies to their native ones; an eval that never set
  one sees no change. #5464's behaviour (schema validation, unmapped
  exceptions fail the sample) is unchanged.
- **Generated TypeScript types.** None to regenerate; `metadata` is already
  typed as an open object.
- **Public API and CLI.** `SandboxAgentBridge.consume_tool_execution_grant`
  returns the record instead of `bool`; `register_tool_execution_grants`
  gains a defaulted keyword on both `AgentBridge` and the sandbox override
  and now stores grants for exempt servers; all are only called from
  `service.py`, `util.py` and tests. A third-party `AgentBridge` subclass overriding the
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
- **Viewer.** Old logs render as before. The coverage-keyed rules land
  with the Python change, so new mixed bridged turns render scaffold-run
  calls and results as they do today, plus a panel per host call.
- **Existing tests (as renamed by #5428).** `test_opted_out_server_stores_no_grants`
  in `tests/agent/test_bridge_approval.py` inverts (grants are stored for
  exempt servers, for attribution); `test_opted_out_server_executes_without_a_proposal`
  and `test_scaffold_local_tool_calls_are_not_stored` still hold. The Docker
  tests `test_sandbox_bridge_denies_unproposed_host_tool_call` and
  `test_sandbox_bridge_executes_proposed_host_tool_call_once` in
  `tests/tools/test_tools_bridge.py` keep passing because RPC behaviour for
  those calls is unchanged; the transport-level tests #5428 opted out with
  `require_proposal=False` now also see an `exempt` event each.
- **CHANGELOG.** Three `## Unreleased` lines: host tools executed through
  `sandbox_agent_bridge(bridged_tools=...)` are now recorded as tool events
  in the transcript, including denied calls; an explicitly configured
  `max_tool_output` or a tool's `max_output` now applies to their results
  as it does to native tool results;
  images in tool results now follow `log_images` like images in messages.

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
- `result` comes from the host tool (trusted code). String results are
  bounded before recording when the eval or tool configured a limit; media
  in list results follow the `log_images` policy through
  `walk_tool_result`. Error messages recorded
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

- Proposed and executed (with and without an approval policy, as #5428's
  parametrised tests do): the event has the proposing call's id,
  `function` equal to the registered tool name, `metadata.bridge.function`
  equal to the model-facing name the proposal used (a `mcp__host__read_file`
  case proves the two differ), the executed arguments (key order as sent),
  the result, `metadata.bridge.grant == "consumed"`, `completed` and
  `working_time` set, `pending is None`.
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
  execution. A third case models `CodexConsumer`'s lifecycle: the stub opens
  the span in `on_complete` of the proposing generation and closes it
  (emits `SpanEndEvent`) in `on_pending` of the next generation, and the
  host call executes after that close; assert the event still carries
  `"agent-sub"` and nests under that span node in `event_tree`, with the
  `span_end` earlier in the stream. Both known sinks stamp in `on_pending`
  and open in `on_complete`, so the first case covers their attribution
  path and the third the only lifecycle they differ on (when the span
  closes).
- Exempt server (`require_proposal=False`): a proposed call pairs
  (`grant == "consumed"`); an unproposed call executes with a fresh id,
  `error is None`, `grant == "exempt"`.
- Output limit: with nothing configured, a tool returning 20 KiB is
  delivered and recorded whole with `truncated is None` (the native 16 KiB
  default does not apply); with `GenerateConfig(max_tool_output=1024)`
  active, the caller receives the native wrapper text and the event records
  the same text with `truncated == (20480, 1024)`; a tool registered as
  `ToolDef(tool, max_output=64).as_tool()` truncates at 64 bytes with no
  eval config; a tool returning `[ContentText(<20 KiB>)]` is never
  truncated.
- Denied: fresh id, `function` is the MCP tool name, `error.type ==
  "permission"`, `grant == "denied"`, tool not awaited, `PermissionError`
  still raised with #5428's text.
- Unknown server: `parsing` event with the server name as sent, and the
  `ValueError` raised carries exactly "Unknown bridged tools server:
  <server>". Unknown tool on a known server: `parsing` event and exactly
  "Unknown tool '<tool>' in server '<server>'". Arguments nested 101 deep:
  `parsing` event with the native depth message, `ToolParsingError` raised,
  tool not awaited; arguments nested 100 deep execute. Arguments that fail
  #5464's schema validation: an object-shaped failure (a missing property)
  records the validation message and the arguments as sent, a non-object
  (a list) records the message and `arguments == {}` (the combined-invalid
  case below); `ToolParsingError` raised as today.
- Two identical proposals in flight (same tool, same arguments, ids `a`
  then `b`): the first execution pairs with `a` and the second with `b`,
  deterministically, so a later change to the grant store cannot silently
  alter the documented oldest-first pairing.
- One proposal, two indistinguishable targets (two servers serving a tool
  with the same description and deliberately different schemas, since
  #5428 does not consult schemas; it registers two grants for one call
  `p`): executing both yields a first event with `id == "p"` and a
  second with a fresh id, both with `metadata.bridge.proposal_id == "p"`,
  `grant == "consumed"`, and both under the proposal's span. ACP: exactly
  one update to the synthesised card plus one separate start and update.
  The viewer fixture below adds this case.
- A proposal declared in the input (a Responses `tool_search` discovery,
  the shape `test_tool_discovered_through_tool_search_is_granted` builds)
  pairs like any other: the event carries the discovered call's id and
  `metadata.bridge.function` its model-facing name. An ordinary call whose
  arguments carry `ServerName`/`ToolName`/`Arguments` mints no grant, so
  the host call it names is denied and recorded `denied`.
- Pairing state does not grow: register and consume 1,100 one-target
  proposals in sequence (more than `_MAX_TOOL_EXECUTION_GRANTS`); after
  each, the deque is empty and the bridge holds no other per-proposal
  state (assert by `gc.get_referrers` on a sample `_Proposal`, or by
  `sys.getsizeof`-independent attribute inspection: the bridge has no
  attribute whose length grows); a later proposal reusing an earlier
  call id pairs normally.
- Combined-invalid requests: an unknown server with `arguments` that is a
  list, and a known tool with a list: the first records the unknown-server
  `parsing` event with `arguments == {}` and raises the unknown-server
  `ValueError`; the second records the schema-validation message with
  `arguments == {}` and raises `ToolParsingError`. Neither awaits the tool.
- Large arguments on a denied call: a 1 MiB string argument is recorded on
  the event as sent and `condense_sample` turns it into an attachment;
  there is no cap beyond the service's request read limit, by decision
  (the same input already reaches `ModelEvent` inputs unbounded). A
  `@pytest.mark.slow` Docker case sends a 120 MiB argument through the
  proxy (near the 150 MiB read limit), asserts the sample completes with
  the event recorded and condensed, and fails if peak RSS growth over the
  baseline exceeds four times the argument size (the request read, the
  parsed JSON, the event's reference and the condensation copy); the
  deliberate exposure is one extra in-memory copy of the arguments for the
  event's lifetime, and the bound turns that claim into a check.
- Failure paths: tool raises `ToolError`, `PermissionError`,
  `TimeoutError("tool-specific timeout")`, a `SandboxTimeoutError` with
  truncated output, an unmapped exception, and `LimitExceededError`. Assert
  the mapped `error` and `result` on the event, `failed is True` and
  `error is None` for the unmapped one with `bridge.request_fail` called
  with the unwrapped exception (and not called for the mapped ones), and
  that the exception propagated to the caller is the original object with
  its original message (RPC text preservation). A `ToolError` raised inside
  an `anyio` task group in the tool is classified from the unwrapped
  exception and does not fail the sample.
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

- Extend `test_sandbox_bridge_executes_proposed_host_tool_call_once`: the
  log has two `tool` events, one with `id == "approved"`, `function ==
  "calculator_add"`, `metadata.bridge.function == "calculator_add"`,
  `arguments == {"y": 3, "x": 5}`, result `"8"`, `grant == "consumed"`, and
  one denied with a fresh id, `function == "calculator_add"` and a
  `permission` error; both sit in `tool` spans under the same parent as the
  `ModelEvent`.
- Extend `test_single_tool_call_returns_correct_result` (an exempt server):
  one `tool` event with a fresh id and `grant == "exempt"`.
- Extend `test_sandbox_bridge_denies_unproposed_host_tool_call` (both
  parametrisations): one denied event, no executed event, and the MCP error
  text unchanged.
- A tool that raises `TimeoutError("tool-specific timeout")`: the MCP error
  carries that text and the event carries the native timeout error.
- `eval(..., max_tool_output=1024)` with a tool returning 4 KiB: the MCP
  `text` block is the wrapper containing a 1 KiB excerpt and the event has
  `truncated == (4096, 1024)`; the same tool under an eval with no limit
  returns all 4 KiB.

Viewer, ts-mono: vitest cases for the coverage-keyed `showToolCalls` and
`recentInputMessages` rules over three fixtures: a bridged turn at the top
level mixing a paired host tool event and a scaffold-run call; an
`agent` span containing the proposing `ModelEvent`, the host tool span and
event, and the next `ModelEvent` whose input carries the result message;
and a proposal executed on two indistinguishable targets (one event with
the proposing id, one with a fresh id and `proposal_id`).
Assert: the scaffold-run call still renders inline, its result is still
surfaced, the host call is omitted inline and rendered once as a tool
panel with an empty child list followed by a sibling `tool` span node
holding its nested `SandboxEvent` (and, for a second host call with no
nested events, a panel and no span row), and navigation from the host
result message resolves to the host event inside the agent span. A native
fixture proves no change.

## Implementation plan

Two inspect_ai PRs plus the ts-mono companion. The first is a standalone,
behaviour-preserving change to shared log code that reviews more easily on
its own; the second is the design proper and depends on it and on #5428.
The extraction of the native error mapping that an earlier revision listed
as PR A landed independently in #5464 (`tool_call_error`,
`MappedToolCallError`, 2026-09-21) together with the bridge classifying host
tool exceptions and validating arguments; this design builds on it and adds
nothing to it.

**PR B: tool result media follow the logging policy**
(`src/inspect_ai/log/_condense.py`, `tests/log/test_log_attachments.py`,
`CHANGELOG.md`). Add `walk_tool_result`, call it from `walk_tool_event`,
add the round-trip tests. Fixes the existing `log_images=False` gap for
native tool events on its own.

**PR C: record host tool events** (after #5428 and PR B):

1. **Grant record carries the proposal and span**
   (`src/inspect_ai/agent/_bridge/types.py`,
   `src/inspect_ai/agent/_bridge/sandbox/types.py`,
   `src/inspect_ai/agent/_bridge/util.py`,
   `tests/agent/test_bridge_approval.py`). Add the `span_id: str | None =
   None` keyword to the base `AgentBridge.register_tool_execution_grants`
   hook and the sandbox override, after #5428's `(calls, tools)`
   parameters, and pass it from `bridge_generate` alongside the
   `[*tools, *declared_in_input(...)]` list it already builds; add
   `_Proposal` (call, span_id, paired, `take_id()`) and replace nothing else
   on `_ToolExecutionGrant` but add the `proposal` reference shared by a
   call's grants; return the record from `consume_tool_execution_grant`;
   store grants for exempt servers; add `_SpanCapturingSink` and the
   capture in `bridge_generate`; update the grant check in `call_tool` to
   the new return type. Leave `_proposed_call`, `_dispatched_call` and its
   `call_mcp_tool` name gate untouched. Re-check #5428's landed head first:
   this step is written against `e5e3cab8f`, the head Ransom called stable
   on 2026-09-22, and #5428 was still behind its base then, so re-check
   after its base update too. Invert `test_opted_out_server_stores_no_grants`;
   keep `test_tool_discovered_through_tool_search_is_granted`, the
   dispatcher name-gate tests and the resolver tests listed under Grants
   passing; add the span-capture tests; confirm the in-process
   `bridge_generate` tests still pass.
2. **Span parent helper** (`src/inspect_ai/util/_span.py`, `tests/util/`):
   `parent_span()` with a test that a constructed event and a nested
   `span()` take the given parent and the previous value is restored.
3. **Record host tool events** (new
   `src/inspect_ai/agent/_bridge/sandbox/host_tool.py`; `service.py`
   delegates; `src/inspect_ai/event/_tool.py` docstring for
   `metadata.bridge`; `util.py:365-369` docstring). Includes the depth check
   ahead of #5464's schema validation and the output truncation under an
   explicit limit. Unit tests
   from the Testing section, including the event tree, cancellation counts
   (direct, outer, and ACP `cancel_current_turn`), RPC text preservation,
   truncation and trio.
4. **ACP mapping** (`src/inspect_ai/agent/_acp/event_mapping.py`,
   `tests/agent/test_acp/test_router_bridge_tools.py`). Pop `pending` in
   `_map_tool_event`, update docstrings, add the three tests.
5. **Docker tests and docs** (`tests/tools/test_tools_bridge.py`,
   `docs/agent-bridge.qmd` Transcript section and the bridged-tools section
   for the argument checks and output limit, `CHANGELOG.md`).
6. **Viewer companion** (ts-mono PR): coverage-keyed `showToolCalls` and
   tool-message hiding at the timeline level, with the three fixtures. Lands
   together with PR C through the submodule pointer bump, per
   `.agents/skills/land-ts-mono/SKILL.md` (decision: Ransom, 2026-09-15), so
   no release carries host tool events without the viewer rules.

## Open questions

None outstanding.

Decided (Ransom, 2026-09-15): arguments that are not a JSON object or nest
deeper than the native bound are rejected before execution; a denial is
recorded as `ToolCallError("permission", ...)`; string results are
truncated only when `max_tool_output` or `ToolDef.max_output` is explicitly
set, never by the native 16 KiB default; grants are stored for exempt
servers so their proposed calls still pair; the viewer companion lands
together with the Python change, as cross-repo PRs normally do.

## Not this design

- **The execution contract** (a host tool runs once per call the model
  proposed, with a per-spec opt-out) is #5428, in review alongside this
  design. This design assumes it and adds only the `ToolCall` and span to
  its grant record.
- **Parity of the host path with native execution** beyond what #5464
  landed: `tool_params` coercion of arguments, `ToolDef.viewer` for the
  event's `view`.
- **Tool result review for host tools.** A `review` policy
  (`Task(review=)`, `eval(review=)`, `react(review=)`) does not cover a
  bridged host tool today: native `execute_tools` runs `_apply_tool_review`
  after execution and before the model sees the result
  (`_call_tools.py:406-417`), the bridge path never does, and `ReviewEvent`s
  are therefore absent for host calls. Covering them means running the
  reviewer at the execution edge in `host_tool.py`, before the result is
  returned to the scaffold, and deciding what `terminate` (the sample ends
  through `bridge.request_fail`, as approval termination does) and
  `escalate` mean over the RPC. This design gives it the `ToolEvent` a
  `ReviewEvent` pairs with; it is a natural companion to the
  unconditional-grants follow-up.
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
  exempt) on the tool panel.
- **Unmapped host tool exceptions failing the sample** was
  meridianlabs-ai/inspect_ai#500, fixed by #5464 (merged 2026-09-21):
  `call_tool` now signals an unmapped exception through
  `bridge.request_fail` so the sample ends as it would natively. This
  design keeps that behaviour and only adds the event alongside it.
- **A closed-span fallback for captured spans**: tracking `SpanEndEvent`s
  through a bridge-side transcript subscription so an execution whose
  proposal's span has since closed is placed under the current span
  instead. Not needed for either known sink (their sub-agent spans outlive
  the sub-agent's calls) and both trees nest by `span_id` regardless.
- **Scaffold-run tool calls** remain without `ToolEvent`s; the
  `in_bridge_model_generate` synthesis in ACP stays for them.
