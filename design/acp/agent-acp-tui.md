# inspect acp — TUI

A keyboard-first Textual TUI for attaching to running Inspect AI eval samples: chat with the agent, watch its tools, intervene mid-flight.

Invoked as `inspect acp` from a separate terminal while an eval is running with the ACP server enabled. Single sample per attach for v1; switch between samples via `^S`.

The visual spec is **[`inspect acp — TUI design (print).pdf`](inspect%20acp%20—%20TUI%20design%20%28print%29.pdf)**. Crops of each mockup accompany the sections below.

For the broader ACP design (server, sessions, router, asyncio boundary, phased build), see **[`agent-acp.md`](agent-acp.md)**. This doc is the TUI-client surface only.

## Constraints

- **Standalone client** — the TUI is built as a self-contained Textual app and **does not reuse existing Textual code in this repo** (e.g. the `--display full` app under `src/inspect_ai/_display/textual/`). We may want to ship the `inspect acp` binary separately from the main `inspect` package, so its only hard dependencies are `textual` itself, the `acp` Python library, and a thin slice of types shared with the ACP server side.
- **Single sample per attach** for v1; multi-sample navigation is Phase 8.
- **asyncio at the transport leaf** — same constraint as the rest of the ACP code (see [`agent-acp.md`](agent-acp.md) "asyncio / anyio boundary"); the `acp` library requires it.

## Screens

### Attach picker

Always the initial screen — either on launch, or when re-opened via `^S`. The picker lists running sessions on this machine (or on a remote machine when `--server <addr>` is given).

- **Empty state** — no running sessions found and no `--server` was specified; shows the bootstrap message and a sample command to enable the ACP server on a local eval.

  ![attach empty](images/04a-attach-empty-state.png)

- **Picker table** — flat list of samples across all running evals. Columns: `eval`, `task`, `sample`, `epoch`, `running`. Greys out as samples complete. `--eval-id <id>` narrows the table to sessions from a specific eval (it does not bypass the picker).

  ![attach picker](images/04b-attach-picker-table.png)

**CLI flags**

- `--server <addr>` — discover sessions on a remote ACP server. Accepts either `host:port` or a UNIX domain socket path. Used by both the TUI and `--stdio` modes (replaces the legacy `--socket` flag).
- `--eval-id <id>` — narrow the picker to sessions from a single eval.

### Primary conversation pane

Main screen once attached. Persistent layout across all conversation states.

![primary pane](images/01-primary-pane-calling-tools.png)

Regions:

- **Meta row** — `inspect acp · eval <id> · task <name> · sample <n>/epoch <m> · agent <name>`
- **Status row** — status pill (state machine, below) + state-dependent chips (`N tools in flight`, `model <name>`, `retry n/m`, `tokens NNNk`)
- **Transcript** — scrollable conversation event list
- **Composer** — multi-line input, focus-aware keymap
- **Footer** — keymap hints for the current state

## Conversation event types

Each event has a dedicated rendering treatment.

| Event | Treatment | Mockup |
|---|---|---|
| Assistant message | text block with model chip; streaming cursor when state is `Generating` | [02b](images/02b-state-generating-retry-with-intervention.png) |
| User / dataset input | text block with `user · dataset_input` chip | [02a](images/02a-state-awaiting-input.png) |
| Tool-call card | bordered card, flush-left, tool name + args/output + status chip (`running` / `completed` / `failed`) + duration; click-to-expand for long output | [03b](images/03b-tool-call-card-anatomy.png) |
| Reasoning block | dimmed, expandable; variants for visible-summary / encrypted-with-summary / encrypted-no-summary / redacted | [03a](images/03a-reasoning-variants.png) |
| Operator intervention | purple banner showing a user message injected mid-turn during interruption | [02b](images/02b-state-generating-retry-with-intervention.png), [02e](images/02e-events-stream.png) |
| Plan update | ephemeral notification card, completed items struck-through, `done/total` count + timestamp | [02d](images/02d-state-plan-update-ephemeral.png) |
| Info event | cyan/teal `info · <source> · <ts>` chip with optional structured JSON payload; subsystem-level diagnostic surfaced into the transcript | [02e](images/02e-events-stream.png) |
| Conversation compacted | amber banner showing `messages X → Y · tokens X → Y · summary preserved · raw messages dropped from context` | [02e](images/02e-events-stream.png) |
| Mid-stream score | green `score · includes · value <v> · passed · <reason>` chip — score event that fires before the sample terminates (e.g. multi-turn or intermediate scorers) | [02e](images/02e-events-stream.png) |
| Turn interrupted | red banner with `by operator · <note> · in-flight tools cancelled · agent loop awaits next user message` | [02e](images/02e-events-stream.png) |
| Score event (terminal) | green `sample <n> completed` banner with score line | [06a](images/06a-terminal-completed.png) |
| Error event (terminal) | red `sample <n> errored` banner with inline traceback | [06b](images/06b-terminal-errored.png) |

The full event stream shown end-to-end:

![events stream](images/02e-events-stream.png)

## Status pill state machine

Exactly one pill always visible in the status row. The chosen colour propagates to associated elements (in-flight tool-card borders, banner backgrounds).

| State | Colour | Entered when | Notes |
|---|---|---|---|
| Awaiting input | sage | default resting state, after agent yields | composer focused, send enabled |
| Generating | amber | model invocation begins | retry chip shown if retry > 1 |
| Calling tools | teal | one or more tool calls in flight | `N tools in flight` chip; `Esc` interrupts ([02c](images/02c-state-calling-tools-two-in-flight.png)) |
| Scoring | amber | scorer running after sample completes | composer disabled |
| Completed | sage | scorer finished, sample terminal | composer replaced by next-action shortcuts |
| Errored | rust | sample terminal after error | composer replaced by traceback actions |
| Interrupted | rust | transient, after `Esc` until next turn starts | flashes briefly, then back to `Awaiting input` |

## Modals

### session/request_permission

Shown when an attached agent invokes a tool requiring human approval.

![approval modal](images/05a-modal-request-permission.png)

- Header: tool name + one-line description
- Body: pretty-printed arguments
- Actions: `[a] allow always`, `[o] allow once`, `[d] deny`
- Bare letters trigger directly. Auto-dismisses if another attached client answers first.

### inspect/cancel_sample

Shown on `^X`.

![cancel modal](images/05b-modal-cancel-sample.png)

- Header: sample / task / turn / tools-in-flight summary
- Actions:
  - `[s] score` — run the scorer with current state; sample completes normally
  - `[e] error` — fail the sample with a `CancelledError` (equivalent to `fail_on_error=True`)
  - `[esc] back`

### Help (`?`)

Single-screen overlay listing the full keymap. Bound globally except when the composer holds non-empty text.

## Connection / terminal states

| State | Treatment | Mockup |
|---|---|---|
| Connected | no overlay; toasts silent | all live pages |
| Reconnecting | toasts narrate (`Reconnecting to ACP server (disconnected N minute…)` every 60s after the first minute); transcript stays as-is so the operator can read history; events replay on reconnect | [06c](images/06c-terminal-disconnected-reconnecting.png) |
| Completed | terminal — `Completed` pill, sample-completed banner, footer: `^S switch sample` / `^R rescan` / `^O open log` / `^C quit` | [06a](images/06a-terminal-completed.png) |
| Errored | terminal — `Errored` pill, sample-errored banner with inline traceback, footer: `^O open log` / `^C copy traceback` / `^S switch sample` | [06b](images/06b-terminal-errored.png) |

## Keymap

**Composer focused (default):**

| Key | Action |
|---|---|
| ↵ | send |
| Shift+↵ | newline |
| Esc | clear draft if empty + agent working → interrupt |
| ^X | cancel sample |
| ^S | switch sample |
| ^E | expand focused card |
| ^L | rescan / retry |
| ^O | open log (only when composer empty) |
| ? | help (only when composer empty) |
| ^C | quits the app — reserved, never bound to interrupt |

**In modals & pickers (no text input):**

Bare letters work directly: `s` / `e` in cancel-sample, `↑↓ ↵ /` in pickers.

**During tool-call approval** (composer Input is replaced by the approval bar — see Phase 1):

| Key | Action |
|---|---|
| a | approve |
| r | reject |
| e | escalate |
| t | terminate |
| m | modify |
| Tab + ↵ | navigate buttons + activate |
| mouse | click any bar button |

## Implementation phases

Phasing principle: **passive → active → robust → rich → ergonomic**. Each phase is a self-contained, meaningfully testable unit. Protocol extensions that surface as the work proceeds are recorded in [`agent-acp.md`](agent-acp.md) alongside the server-side contract — not catalogued ahead-of-time here.

### Shipped

A summary of what's landed to date. Items below are intentionally compressed — for detail, read the code.

- **Transport + picker (attach plumbing)** — `inspect acp` CLI subcommand, discovery + connection plumbing, attach picker that lists running sessions across multiple evals via `inspect/list_sessions`, empty-state bootstrap when no sessions are found, `--server` / `--eval-id` flags, session attach (JSON-RPC handshake + held-open connection), pilot test scaffolding under `tests/agent/test_acp/test_tui/`.
- **Conversation rendering (read-only)** — status row with `Awaiting input` / `Generating` / `Calling tools` pills + state-dependent chips (tools-in-flight, model, tokens), scrollable transcript, three event renderers (assistant message, user / dataset_input, tool-call card with status + duration).
- **Composer + interrupt** — `session/prompt` send path, `Esc` interrupts an in-flight turn via `session/cancel`, full pill state machine including the transient `Interrupted` flash.
- **Plan widget** *(landed off the original schedule)* — collapsed one-line `plan [✓ done/total] current: …` strip pinned above the composer, plus a `^p`-toggled / click-toggled overlay rendering `AgentPlanUpdate` notifications. Opts in via `clientCapabilities._meta["inspect.plan_rendering"]`. Departs from the original spec's "ephemeral notification card" treatment in favour of a persistent strip + on-demand overlay — closer to how operators actually consume plan state at a glance. Footer slot hidden until the first plan arrives. Lives entirely in `src/inspect_ai/agent/_acp/tui/widgets/plan.py`; pilot + state coverage in `tests/agent/test_acp/test_tui/test_plan.py`.
- **Approval (composer-area bar)** *(Phase 1 — pivoted from modal to inline-on-card + composer-area bar)* — `human_approver` chain's "ask the operator" step now routes through ACP `session/request_permission` and renders as an inline content section on the matching tool-call card (matched by `toolCallId`) plus a composer-area `_ApprovalBar` (`> approve?  [ a ] approve  [ r ] reject  [ e ] escalate  [ t ] terminate  [ m ] modify`). New `approval` value on the lifecycle pill; first option focused on mount so Tab+Enter activates without a click; bare-letter shortcuts gated to `approval` lifecycle. Producer-side bakes bold per-half titles + horizontal-rule separator into the request markdown so non-Inspect ACP clients (Zed et al.) get the same visual structure for free — strict superset, no protocol extension.
- **Cancel Sample (composer-area bar)** *(Phase 4 — pivoted from modal to bar)* — `^N` brings up a composer-area `_CancelSampleBar` (`> cancel sample?  [ s ] Cancel: Score  [ e ] Cancel: Error  [ esc ] Go Back`) instead of the originally-spec'd modal, for the same reasons as Phase 1's approval pivot. `[e] Cancel: Error` is hidden when `ActiveSample.fails_on_error` is True, mirroring `--display full`'s `cancel_with_error.display = not sample.fails_on_error` rule exactly (fractional / integer-count thresholds that collapse to True hide `[e]` here too). The picker propagates the boolean via the picker `_meta` payload's `failsOnError` field and the binding-confirmation `session/update` `_meta` (so direct-attach via `session/load` picks it up too, not just picker-attach). The bar's `[s] Cancel: Score` and `[e] Cancel: Error` shortcuts share screen-level letter bindings with the approval bar's `s`/`e` via a single `prompt_letter` dispatcher (Textual's binding table is letter-keyed; two bindings on the same letter is last-write-wins, so the dispatcher routes based on which bar owns the row — cancel bar takes precedence when visible). Generic `_PromptOption` widget extracted into `widgets/_prompt.py` and shared with `_ApprovalBar` so both bars share the focusable + clickable + `[ k ] label` rendering. Footer reorganised — `cancel sample | switch sample | quit` cluster sits flush-right via an `AppFooter` subclass that inserts a `1fr` spacer; the three "end or navigate away from this session" actions are grouped together as a visual unit.
- **Cancel Tool Call (screen-footer `^L` keybind)** *(Phase 2 — pivoted from clickable `×` + card-focus model to a screen-footer keybind only)* — `^L cancel tool` appears in the screen footer (left group, between `^p plan` and the right-cluster `^n cancel sample`) and cancels the *most-recently-started* eligible tool. The targeted tool's card flips its footer to a dim `· cancelling…` marker as feedback that the request landed; the natural failure-status event (server-side `_call_tools.py` synthesises a `ChatMessageTool` with `error.type == "timeout"`) drives the card to terminal a moment later. A second `^L` advances to the next eligible tool (the cancel-requested one is filtered out). No per-card inline affordance — the iteration converged on "the footer hint is the only thing the operator needs," and per-card duplication just adds visual noise. Cards awaiting an operator approval decision are filtered from the eligibility set — the approval bar's `reject` / `terminate` is the right exit there. `mark_cancel_requested` on `SessionState` is the load-bearing idempotence guard (returns False on double-fires); `cancel_tool_call_id` accessor handles the eligibility filter and most-recently-started tiebreaker; `check_action` hides the footer hint entirely when no in-flight tool is cancellable. No new wire shape — fires the already-shipped `inspect/cancel_tool_call({sessionId, toolCallId})` request from `agent-acp.md` Phase 12.
- **Queued user messages (in-transcript ephemeral echo)** *(Phase 3 — pivoted from "transcript chip + status-row counter" to "dim ephemeral echo only", and from "stack N ephemerals" to "single growing ephemeral" to mirror server-side coalesce)* — operator hits Enter while `lifecycle != "idle"`; the composer text mounts (or appends) to a queued `MessageGroup(is_queued=True)` rendered with the chip `user · queued` and a dim body. Single-bucket invariant: at most ONE queued ephemeral exists at any time — subsequent sends-while-busy APPEND with `\n\n` paragraph separators to the same group. Mirrors the server-side `_coalesce_operator_messages` merge (`agent-acp.md` Phase 3 follow-up): N queued sends drain as ONE merged `ChatMessageUser`, so the visible ephemeral matches exactly what the model will see — and the model gets a clean alternating user/assistant turn instead of N consecutive user turns. When the server's coalesced chunk arrives, `_consume_chunk` pops the single queued ephemeral and the merged real group renders in its place (key-keyed swap on the `TranscriptWidget` because the locally-minted `queued-N` id differs from the server's). The originally-spec'd `N queued` header-pill counter was dropped — the ephemeral row IS the at-a-glance signal. Send during `idle` deliberately skips the ephemeral (chunk usually round-trips within ms; the row would just flash). Send failure rolls back precisely: the optional `_QueuedEnqueueHandle` returned from `enqueue_queued_user_message` records the prior text snapshot, so `undo_queued_enqueue` restores just the failed append (preserving earlier queued sends) or removes the whole group on fresh-creation rollback. `mark_complete` drops any undrained ephemeral so the read-only postmortem view doesn't misrepresent never-delivered messages as delivered. Lives in `state.py` (`MessageGroup.is_queued` + `_QueuedEnqueueHandle` + `enqueue_queued_user_message` / `undo_queued_enqueue` / `_current_queued_user_group` / `_pop_queued_user_group`), `widgets/message.py` (chip + dim-body branch), and `session_screen.py:action_submit` (enqueue-before-await + handle-based rollback-on-failure). Multi-client driver edge case (FIFO pop being per-session, not per-client) shrinks to a non-issue under the new single-bucket model: any operator chunk arrival just pops THE ephemeral, whoever submitted it.
- **Scoring lifecycle (split-phase session + score chips)** *(Phase 5 — picked a hybrid of the original (b) + (c): transport-agnostic session + split-phase teardown, not a full lifetime decoupling)* — scoring runs AFTER the agent's `acp_session()` exits, so without this phase `ScoreEvent`s never reach attached clients. `LiveAcpSession.__aexit__` now PARKS when bound to an `ActiveSample` (interrupt coordinator + approver registry cleared; router + pubsub stay attached); the deferred full teardown moves to a new `finalize()` method called from `active_sample().__aexit__` after scoring + logging complete. Predecessor handoff: when a solver runs two agents consecutively in the same sample, the successor's `__aenter__` finalizes the predecessor before binding. Six new post-agent guards on `before_turn` / `after_cancel` / `turn_scope` / `submit_user_message` / `cancel_current_turn` / `attach_approver_client` no-op gracefully when the agent has parked (per-method comments distinguish loop-only invariants from network-reachable defenses). The eval primitive (`log/_samples.py`) doesn't import ACP — `ActiveSample` got two callback slots (`on_complete` async, `on_interrupt` sync) that the live session registers in `__aenter__`; `sample.interrupt()` and `sample.limit_exceeded()` fire `on_interrupt` before the task-group cancel so in-flight `ModelEvent.pending=True` is cleared (anyio cancellation bypasses the normal completion paths), and the TUI's assistant chip stops spinning past the scoring chips. TUI-side: new `ScoreChip` dataclass + `ScoreChipWidget` (header + optional collapsible markdown body, with the `markup=True` header carefully escape-guarded so score text containing source / diffs / brackets can't take the transcript render down); consumed via the `inspect/event` raw firehose by subscribing to `["score", "span_begin", "span_end"]` (`RAW_EVENTS_META_KEY` value shape shifted from `bool` → `list[str]` with `"*"` glob sentinel — `frozenset[str] | None` on the server). The outer `span(name=SCORERS_SPAN_NAME)` boundary clears the plan strip and latches `_scoring_started` to suppress any later (typically stale-from-replay) `AgentPlanUpdate`; per-scorer `span(type=SCORER_SPAN_TYPE)` mounts a `scoring · X…` indicator chip cleared by either the matching `ScoreEvent` (real score replaces placeholder) or the matching `span_end` (scorer returned None / raised without firing). Span name strings lifted to `SCORERS_SPAN_NAME` / `SCORER_SPAN_TYPE` constants in `util/_span.py` so the producer (`_eval/score.py`) and consumer (`tui/state.py`) share one source of truth. Replay path on late-attach rewritten from "raw pass then semantic pass" to a single interleaved walk in transcript source-order via a new stateful `ReplayTranscriptor` class — score chips appear AFTER the conversation that produced them, plan updates land at their original timestamp. New `mark_sample_cancelling` / `rollback_sample_cancelling` lifecycle state on the TUI: `^N` choice sets `_cancelling=True` so the pill keeps reading `running` (NOT `interrupted`) through the server-side scoring + finalize teardown window; RPC failure rolls back. Stream buffer hygiene (sub-discovery during swe-bench scorer testing): swe-bench-class scorers emit >500KB `Score.explanation` payloads that exceeded asyncio's 64 KiB readline default and crashed the TUI receive loop — new `ACP_STREAM_BUFFER_LIMIT = 64 MiB` (in `_config.py`) applied to every server / TUI client / stdio asyncio stream entry point. Also: `_AcpDisconnectFilter` root-logger filter suppresses upstream `acp` library tracebacks on routine peer disconnects (BrokenPipe etc.), demoting `AcpServer._on_connection`'s post-disconnect close failure to DEBUG. Architectural review follow-ups: the registration-hook pattern replaced an earlier `getattr(sess, "finalize")` duck-type in `_samples.py`; six post-agent guards got per-method caller-naming comments distinguishing loop-only invariants from network-reachable defenses; `_scoring_indicator_span_id` folded onto `ScoreChip.span_id`. Lives across `agent/_acp/session_live.py`, `log/_samples.py`, `agent/_acp/tui/state.py`, `agent/_acp/tui/widgets/score.py`, `util/_span.py`, `agent/_acp/_config.py`, `agent/_acp/inspect_ext.py`, `agent/_acp/session_router.py`, `agent/_acp/event_mapping.py`; test coverage in `test_tui/test_scoring.py`, `test_active_sample_link.py` (6 new hook tests), `test_disconnect_log_filter.py`.

### Phase 1 — Approval (inline on tool-call card)

Routes the `human_approver` chain's "ask the person at the keyboard" step through ACP `session/request_permission` and renders the prompt **inline on the corresponding tool-call card** rather than in a modal pop-up. The server-side `Phase 14` work (in [`agent-acp.md`](agent-acp.md)) already plumbs the request to attached clients; this phase adds the client surface plus a small producer-side markdown enrichment so the inline section matches the in-proc `ApprovalPanel`'s visual fidelity.

Pivot from the original modal design: keeping the approval anchored to the tool-call card it gates (matched by `toolCallId`) keeps the operator in the transcript flow, removes a modal focus-management headache, and reuses the existing transcript widget chain. A new `approval` value on the lifecycle pill sits alongside `running` / `interrupted` / `complete`; priority above `running` because the agent is genuinely blocked on the operator.

**Ships**

- **Client-side request route** — `tui/client.py` registers `Route(method="session/request_permission", kind="request")` on the `MessageRouter`. The handler validates the request, creates a `PendingApproval` (request + `asyncio.Event`), invokes the screen-side callback, parks on the event, returns `AllowedOutcome(option_id=…)` on operator choice or `DeniedOutcome(cancelled)` on cancellation/unmount. `try/finally` cancellation safety flips `pending.cancelled` and fires the event so concurrent readers see a consistent state.
- **State extension** — `PendingApproval` dataclass + `pending_approval` / `last_approval_decision` fields on `ToolCallState`. `consume_approval_request(pending)` synthesizes a card from the request payload if no `ToolCallStart` has arrived yet (the permission flow fires before tool execution). `resolve_approval(tool_call_id, option_id=…)` clears the slot, records the post-resolution label, fires the event. `mark_complete` / `mark_interrupted` also resolve any in-flight approvals with `cancelled=True` so disconnect / Esc don't leave the JSON-RPC handler parked. `ToolCallStatus` literal unchanged — the UI gates on `pending_approval is not None`, orthogonal to `pending/in_progress/completed/failed`.
- **Inline `_ApprovalContent`** on the tool-call card — context preview rendering the `view.context` / separator / `view.call` halves the server baked into the approval request's markdown. Dispatches `request.tool_call.content` blocks through the existing `_compose_item` pipeline (so `FileEditToolCallContent` renders as a real diff, `TerminalToolCallContent` as terminal output, `ContentToolCallContent` as markdown via `StyledMarkdown`). No action buttons live in the card — those moved to the composer-area `_ApprovalBar` (next bullet).
- **Composer-area `_ApprovalBar`** — when an approval is pending, the composer `Input` is hidden and a bar takes the row: `> approve?   [ a ] approve   [ r ] reject   [ e ] escalate   [ t ] terminate   [ m ] modify`. Bracketed underlined letters double as bare-letter shortcuts (gated to `approval` lifecycle via `check_action` so they don't fire while typing into the composer). Buttons are also Tab-navigable and mouse-clickable. Per-kind colour: `allow_*` → `$success`, `reject_once` → `$warning`, `reject_always` → `$error`. First button focused on mount so Tab+Enter works without a click. Anchoring the actions at the bottom of the screen keeps the next-thing-to-do in the operator's eye line and avoids the "scroll up to find the buttons" issue the earlier in-card design had on long tool cards.
- **Post-resolution decision suffix** — after the operator (or session cancellation) resolves, the bar hides, the inline content section unmounts, and the decision is appended to the tool card's footer row in colour: `"✓ Ns · approved by you"` / `"✗ Ns · denied by you"` / `"⊘ Ns · cancelled"`. Uses `$success` / `$error` / `$warning` colour tokens. Inline on the same row as the tool's status glyph + duration — saves a row vs. a separate summary line.
- **`approval` lifecycle pill** — new `Lifecycle` literal value with `"⚠ awaiting approval"` text and `$warning` colour. Priority order: `complete > approval > running > interrupted > idle`. Composer `Input` is hidden (`display: none`) while the lifecycle is `approval`; the bar shows in its place.
- **Producer-side markdown structure** — `approval/_human/acp.py:_build_request` bakes the in-proc `render_tool_approval` visual structure (bold per-half titles, horizontal-rule separator between `view.context` and `view.call`, fenced code for non-markdown format) directly into the markdown text it sends. **No protocol extension** — every ACP client (Zed, future ones) renders the structure natively from stock markdown. The TUI's existing `_compose_item` → `StyledMarkdown` pipeline picks up the headings and rules for free.

**Protocol extensions landed**: none. The whole feature lands on existing ACP `session/request_permission` semantics; the visual structure improvement is plain markdown in the request body. Strict superset for non-Inspect clients.

**Acceptance**

- Manual: eval with a human-approver tool (`inspect eval <task> --acp-server --approval=human`); attach via `inspect acp` in another terminal. When a `bash` tool fires, watch the card appear with the inline content preview AND the composer-area approval bar with `[ a ] approve [ r ] reject …`. Press `a`; observe the card transition to decision summary + running tool, the bar disappear, and the composer Input return. Repeat with Tab+Enter; repeat with a mouse click on Reject. Header pill cycles `running → ⚠ awaiting approval → running` cleanly.
- Manual: trigger an approval for a tool whose viewer produces a `FileEditToolCallContent` diff variant; confirm the inline content section renders the actual diff (not a stringified blob).
- Manual (multi-client): attach Zed alongside `inspect acp`. The driver chain (last-prompt-wins, per `agent-acp.md`'s single-driver section) routes the approval to whichever client most recently typed; the other observes via the normal event stream and never sees a competing prompt — no stale-card scenario to test.
- Automated: pure-function tests for the state handshake (`consume_approval_request` / `resolve_approval` / `current_pending_approval` accessor / auto-dismiss heuristic / lifecycle priority / decision-label mapping); pilot tests for the inline content section render + the composer bar (mount, hide-when-no-pending, first-button focus, button-press round-trip, action_approval_decide gate); producer-side tests for the embedded title/separator/fence markdown shape; wire-level tests for the handler's response shape (`AllowedOutcome` + `DeniedOutcome` + cancellation propagation).

**Known v1 gaps (intentional)**

- **`?` help overlay** — originally bundled into this phase. Deferred — the inline approval feature is self-contained and shipping the help overlay separately keeps the diff focused.

### Phase 2 — Cancel Tool Call (screen-footer `^L` keybind) ✅

Per-tool-call cancel — kill ONE in-flight tool without unwinding the whole turn. Server-side `inspect/cancel_tool_call` was already implemented in `agent-acp.md`'s Phase 12; this phase adds the TUI surface. Distinct from `Esc` (which fires `session/cancel` for the whole turn including ALL in-flight tools): per-tool cancel lets a long-running `bash` get cancelled while the model + sibling tool calls keep going. The sub-agent's loop sees the cancelled tool as a synthesized `ChatMessageTool` with `error.type == "timeout"` and decides what to do next.

Two pivots from earlier iterations:

1. **From clickable `×` + card-focus model → screen-footer keybind.** The original spec wanted a per-card affordance reachable via mouse or focused-card keyboard navigation. The card-focus model is a meaningful UI investment that didn't earn its weight here.
2. **From inline `· cancel tool call` link on every card → no per-card affordance at all.** An intermediate iteration mounted the link on every in-flight card (with the `^L` target getting a `[$accent]^l[/]` accelerator hint). After seeing it live, that visual register was redundant noise — the screen-footer `^L cancel tool` hint already communicates the action; per-card duplication just made each tool row busier without adding capability. Mouse users lose the ability to pick a specific tool by clicking its card; the trade-off is acceptable because `^L`'s "most-recently-started + advance on repeat" rule covers the common case (cancel runaway, then the next runaway) without any operator-side targeting.

**Ships**

- **`ToolCallState.cancel_requested` flag + `SessionState.cancel_tool_call_id` accessor + `mark_cancel_requested(id) → bool`** (`tui/state.py`):
  - `cancel_requested` is the load-bearing idempotence signal AND the gate the widget reads to flip its footer to `cancelling…`.
  - `cancel_tool_call_id` returns the `tool_call_id` of the most-recently-started eligible tool (status in {`pending`, `in_progress`}, no `pending_approval`, not yet cancel-requested), or `None`. This is what `^L` resolves against; repeat `^L` picks the next-most-recent because the prior one falls out of the eligibility set.
  - `mark_cancel_requested(id)` is the single mutation entry point — flips the flag + notifies subscribers + returns `False` on every subsequent call (terminal / already-requested / pending-approval short-circuits). Callers (just `SessionScreen._dispatch_cancel_tool_call` for now) fire-and-forget the JSON-RPC request only when this method returns `True`.
- **`ToolCallWidget` footer extension** (`widgets/tool_call.py`) — single line added to `_footer_text`: when `cancel_requested and not is_terminal`, append `[dim]· cancelling…[/]` to the existing `{glyph} {duration}` line. No constructor changes — the widget doesn't need to know about its peer cards. Pending-approval state still short-circuits to the dedicated `tool call approval requested` placeholder at the top of the method.
- **`SessionScreen` wiring** — new `ctrl+l → cancel_tool_call` binding (ordered between `^p plan` and `^n cancel sample` so the footer left-group reads `submit / newline / interrupt / plan / cancel tool` with the right-cluster `cancel sample / switch / quit` flushed right by the `AppFooter` subclass). `check_action` returns `False` when `cancel_tool_call_id is None` to hide the footer hint entirely (no eligible tool). `action_cancel_tool_call` resolves the accessor and routes through `_dispatch_cancel_tool_call(tool_call_id)`, which asks `mark_cancel_requested` to flip the flag (gating on its bool return) and spawns `_fire_cancel_tool_call` in a worker. The fire-and-forget worker mirrors `_CancelSampleBar._fire_cancel` exactly — try/except wrapping `connection.send_request(INSPECT_CANCEL_TOOL_CALL_METHOD, {sessionId, toolCallId})`, failures surface via `app.notify`. The response body (`{cancelled: bool}`) isn't inspected — the natural event-stream failure status drives the card transition.

**Protocol extensions landed**: none. The server side (`inspect/cancel_tool_call` request + the timeout-synthesis failure path in `_call_tools.py`) was already in place from `agent-acp.md` Phase 12.

**Acceptance**

- Manual: `inspect eval <task> --acp-server` with a long-running tool (`sleep 30`); attach via `inspect acp`. Confirm `^l cancel tool` appears in the screen footer once the tool is in flight. Hit `^L` — the targeted card's footer flips to `cancelling…`, then ~1s later the card transitions to the standard `✗ Ns` failed treatment.
- Manual (multi-tool): dispatch two parallel bash sleeps via a tool batch. `^L` cancels the most-recently-started; a second `^L` cancels the other. Both cards transition through `cancelling…` to `✗ Ns`; the agent loop continues with the synthesized timeout results.
- Manual (approval interaction): configure `human_approver` for the tool. While the approval bar is up, confirm `^l cancel tool` is NOT in the footer (`check_action False` because `cancel_tool_call_id is None` while the only in-flight tool is filtered for pending approval). Approve → the tool enters in-flight state → `^l cancel tool` reappears in the footer.
- Manual (no-op gating): with no tools in flight, `^l cancel tool` does NOT appear in the footer. Demo eval (`demo_cancel_tool_eval.py`) exercises this and the multi-tool case alongside the plan widget so both `^p plan` and `^l cancel tool` are visible at the same time.
- Automated:
  - Pure-function tests for `SessionState.cancel_tool_call_id` (empty / one / two / pending-approval filter / cancel-requested filter) and `mark_cancel_requested` (flips + notifies / idempotent / unknown id / terminal / pending-approval) in `tests/agent/test_acp/test_tui/test_state.py`.
  - Pure-function tests for `ToolCallWidget._footer_text` composition (in-flight footer is bare glyph + duration, `cancelling…` appears after request, dropped on terminal, pending-approval short-circuit, approval-decision suffix intact) in `tests/agent/test_acp/test_tui/test_tool_call_footer.py`. No Textual app boot — sub-second.
  - Pilot tests for screen dispatch (single-tool ^L, multi-tool ^L picks newest, ^L advances after first request, no-op when no eligible tool, footer flips to `cancelling…`, double ^L on a single tool fires only once) in `tests/agent/test_acp/test_tui/test_cancel_tool_call.py`.

### Phase 3 — Queued user messages (in-transcript ephemeral echo) ✅

Operator hits Enter while the agent is busy — message rides `session/prompt` into the server's `submit_user_message` queue and drains at the next `before_turn`. The send path itself was already working end-to-end at the protocol level (per `agent-acp.md` Phase 3); the gap the TUI had was *feedback* — between Enter and the eventual server echo there was nothing on screen, so a multi-second tool run made the operator wonder whether the message had registered.

Three pivots from the original Phase 3 spec:

1. **From "queued chip + status-row counter" to "ephemeral echo in the transcript only."** The original spec wanted both a per-message `queued · awaits next turn` chip in the transcript AND a `N queued` chip alongside the lifecycle pill. The chip-in-transcript surface ships; the header counter doesn't. Once the queued rows are visible in the transcript with a clear "not yet real" treatment, the counter is redundant — it would track the same information in a less specific surface, and adding another piece of state to the header just adds visual noise. If a future scrolled-far-up scenario makes the off-screen-queued count actually load-bearing we can add it later; for now the in-transcript signal carries the feature.
2. **From "queued · awaits next turn" chip + canonical body to "user · queued" chip + dim body.** The original chip text was long enough to compete with the body for attention. Shortened to `user · queued` and paired with a dim body so the row reads as "not yet real" at first glance even without the operator parsing the chip text — the visual treatment alone telegraphs ephemeral state. On the server-echoed chunk's arrival a fresh widget mounts (different `message_id` ⇒ different `TranscriptWidget` key) with the canonical `user · operator` chip + undimmed body in place.
3. **From "stack N ephemerals" to "single growing ephemeral"** *(follow-up after the initial Phase 3 shipped — the screenshotted bug)*. The initial implementation appended a separate `MessageGroup` per send-while-busy and FIFO-popped one per arriving operator chunk. Manual testing surfaced a behaviour issue: server-side `before_turn` drained the N queued messages as N consecutive `ChatMessageUser(source="operator")` items, the agent loop extended them onto `state.messages`, and the model saw N user turns before its next assistant turn — a degenerate conversation shape (e.g. responding "OK" because two `here we go again` / `again` prompts didn't form a coherent request). Fix landed in two halves: server-side `_coalesce_operator_messages` (in `agent-acp.md` Phase 3 follow-up) merges drained operator messages into one `ChatMessageUser` with `\n\n`-joined text, AND the TUI mirror — at most ONE queued ephemeral exists at any time, subsequent sends-while-busy APPEND with `\n\n` separators to the same group. The visible row matches exactly what the model receives; the model sees a clean alternating user/assistant turn structure regardless of how many operator sends preceded it.

**Ships**

- **`MessageGroup.is_queued: bool = False`** in `tui/state.py`. Default False so existing widgets are unaffected; True only on client-side ephemerals. NOT registered in `_messages_by_id` / `_pending_message_ids` — queued ephemerals live solely in `items` so the retry-collapse / drop-tombstone / turn-cap logic ignores them (the locally-minted `queued-N` ids would otherwise interact with server-driven aliasing and produce wrong-looking state).
- **`_QueuedEnqueueHandle` dataclass + single-bucket enqueue/undo pair** — `SessionState.enqueue_queued_user_message(text)` returns a frozen `_QueuedEnqueueHandle(group, prior_text)`. Append-on-existing semantics: if a queued group already exists, the new text is appended to `segments[0].text` with `\n\n`, and the handle records the prior snapshot for precise rollback; otherwise a fresh `MessageGroup` is created and the handle's `prior_text` is `None` (rollback ⇒ remove the whole group). `SessionState.undo_queued_enqueue(handle)` restores the prior text on append-handle, removes the group on fresh-handle, and is idempotent (no-op when the group has already been popped by an arriving chunk). The single-bucket invariant — at most one queued group at any time — mirrors the server-side coalesce: a `_current_queued_user_group` accessor finds the bucket, and `_pop_queued_user_group` pops it on chunk arrival.
- **Pop on operator-source chunk arrival** — `_consume_chunk` runs `_pop_queued_user_group()` before `_resolve_or_create_group` when the chunk's `_meta["inspect.user_source"] == "operator"`. The pop and the new group's append batch into the same `consume()`-tick notify so subscribers see one coherent swap. Non-operator user chunks (dataset input, system) deliberately do NOT pop — unrelated to our locally-queued ephemeral.
- **`mark_complete` drops residual queued** — `_drop_queued_user_messages` walks `items` filtering by `is_queued=True` and rebuilds the list. Batched with the sticky-complete flip + approval-cancel sweep so subscribers see exactly one notification into `complete`. Without this, post-completion the read-only postmortem view would show a dim "queued" row that will never be drained, misrepresenting it as if it were waiting on a turn boundary that's never coming.
- **`MessageWidget` chip + body rendering** (`widgets/message.py`):
  - `_chip_text` for `role="user"`: when `is_queued`, returns `user · queued` (no `· operator` clause). Branch ordering matters — checked before the canonical `user_source` clause so a queued ephemeral with `user_source="operator"` reads as queued, not operator.
  - `_compose_segment` for queued groups: yields a plain dim `Static(seg.text, classes="queued-body", markup=False)` instead of the canonical `CollapsibleContent` → `StyledMarkdown` pipeline. Operator composer text is plain — bypassing Markdown rendering both honours the `$text-muted` cascade (Rich Markdown would otherwise override per-element colour) and avoids the unhelpful expander affordance.
- **`SessionScreen.action_submit` integration** — between text extraction and the `connection.send_request` await, `if self._state.lifecycle != "idle": handle = self._state.enqueue_queued_user_message(text)`. The optimistic enqueue is **sync** before any await, so the operator sees the row land before the request even leaves. On exception `self._state.undo_queued_enqueue(handle)` restores the prior state precisely — the prior text on append, the whole-group-removal on fresh creation — and the composer's draft is preserved (existing toast surfaces the error). Sends during `idle` skip the ephemeral entirely — the agent is parked in `before_turn` and the chunk usually round-trips within ms, so an ephemeral would just flash.

**Protocol extensions landed**: none on the wire (the operator-source chunk emission was already there from `agent-acp.md` Phase 3). The follow-up fix added server-side `_coalesce_operator_messages` documented in `agent-acp.md`.

**Acceptance**

- Manual: `inspect eval <task> --acp-server` with a long-running tool (`sleep 30`); attach via `inspect acp`. While the tool is in flight, type into the composer and hit Enter. The dim `user · queued` row appears immediately at the bottom of the transcript; the composer clears. When the agent's react loop yields and `before_turn` drains, the ephemeral disappears and a regular `user · operator` row replaces it in the same position.
- Manual (multi-send growth): queue three messages back-to-back during a single long-running turn. The same ephemeral row grows with `\n\n`-joined text on each send (single bucket). When the agent yields, ONE merged operator message replaces it, AND the model produces ONE assistant response (not three) — the bug the screenshot showed is gone.
- Manual (failure rollback after multiple sends): queue two messages, then trigger a mid-send transport failure on the third. The third send's append is rolled back precisely; the first two queued sends survive in the ephemeral. The composer's draft is preserved.
- Manual (idle): send during `idle` (between turns) — no ephemeral flash; the real chunk arrives within ms and just renders normally.
- Automated:
  - Pure-function tests in `tests/agent/test_acp/test_tui/test_queued_messages.py`: fresh enqueue shape (handle with `prior_text=None`), append-on-existing (single bucket + `\n\n` join + handle's `prior_text` snapshot), undo on fresh handle removes group, undo on append handle restores prior text, undo idempotence on already-gone group, pop-the-queued on operator chunk arrival, regression guards (non-operator chunks / idle path), `mark_complete` clears residual, ephemeral stays out of `_messages_by_id` / `_pending_message_ids`, chip text for queued vs canonical operator vs input groups.
  - Pilot tests in `tests/agent/test_acp/test_tui/test_queued_messages_pilot.py`: send-during-running enqueues ephemeral + clears composer + forwards request, send-during-idle skips ephemeral, arriving operator chunk swaps ephemeral for real group, send-failure rolls back via handle and preserves draft, multiple sends grow a single ephemeral and drain as one.

**Known v1 gaps (intentional)**

- **No queue management.** No editing, reordering, or per-message delete (deliberately lighter-touch than Claude Code's queue UI). The composer clears on send; once text is in the ephemeral it grows on subsequent sends and drains as the merged group on chunk arrival (or clears on `mark_complete`). If a user needs to "cancel" a queued message they can `Esc` the current turn — but the queued message itself stays queued and drains on the next `before_turn` regardless (matches server-side semantics; the design doc explicitly preserves queued messages through interrupts).

### Phase 4 — Cancel Sample (composer-area bar)

Gives the operator a way to terminate a single sample without killing the whole eval process. Server-side `inspect/cancel_sample` was already in place; this phase added the TUI surface.

Pivot from the original modal design: same reasoning as Phase 1's approval pivot — anchoring the choice in the composer area keeps the operator's eye on the bottom of the screen (where the next-thing-to-do already lives), avoids a modal focus-management headache, and reuses the same `_PromptOption` widget the approval bar uses. The bar lives alongside `_ApprovalBar` in the composer row; only one ever owns the row at a time.

The shortcut also changed from `^X` (in the original spec) to `^N` because `^X` is reserved as the app-level quit binding.

**Ships**

- **Composer-area `_CancelSampleBar`** — `^N` opens `> cancel sample?   [ s ] Cancel: Score   [ e ] Cancel: Error   [ esc ] Go Back` over the composer row (the composer `Input` and any visible approval bar hide while it's up). `[s] Cancel: Score` runs the scorer on whatever work landed; `[e] Cancel: Error` marks the sample errored; `[esc] Go Back` dismisses without sending anything. First option focused on mount so Enter activates without a Tab; mouse-clickable; Tab cycles options. The bar fires `inspect/cancel_sample({sessionId, action})` itself when the operator picks a disposition, then hides — the natural `inspect/session_ended` → `mark_complete` flow drives the lifecycle transition. Footer hint cluster hidden once `lifecycle == "complete"`.
- **Polarity matches `--display full`** — `[e] Cancel: Error` is hidden whenever `ActiveSample.fails_on_error` is True, mirroring `cancel_with_error.display = not sample.fails_on_error` exactly. Fractional thresholds (`fail_on_error=0.2`) and integer counts (`fail_on_error=5`) collapse to True in `ActiveSample.fails_on_error` and therefore hide `[e]` here too. The server-side `inspect/cancel_sample` handler enforces the same predicate (`invalid_params` if the operator somehow sends `action="error"` while `fails_on_error` is True).
- **`failsOnError` propagation on both attach paths** — `PickerTarget.fails_on_error` is read directly from `ActiveSample.fails_on_error` (single source of truth, no helper). `picker_target_meta_dict()` surfaces it as `failsOnError` in the structured `_meta` payload, which rides three wire sites in lockstep: the picker `session/update` notification, the `inspect/list_sessions` response, AND the binding-confirmation `session/update` that fires after both `session/new` (picker-attach) and `session/load` (direct-attach). The TUI's `_refresh_row_from_binding_meta` consumes the latter so direct-attach via `session/load(<known sessionId>)` picks up the authoritative value even when the picker hadn't enumerated the session yet.
- **Generic `_PromptOption` widget** in `widgets/_prompt.py` — focusable `Static` with `[ k ] label` rendering, `enter`/`space` press bindings, mouse-clickable, posts a generic `Pressed(action_id)` message. Shared between `_ApprovalBar` and `_CancelSampleBar` so both bars carry the same terminal-prompt aesthetic + keyboard ergonomics without duplicated widget code. Each bar layers its own colour vocabulary (success/warning/error/back) via CSS class selectors on the option's `kind-…` class.
- **Letter-binding dispatcher (`prompt_letter`)** — Textual's binding table is keyed by letter, so two bindings on the same letter (`e` is shared by approval's escalate AND cancel's error) is last-write-wins. The screen registers each letter once and routes through `action_prompt_letter` which picks approval vs. cancel based on which bar is visible. Cancel bar takes precedence when up; `e` while cancel is visible fires `Cancel: Error`, never `escalate`.
- **`^N` gated by `lifecycle != "complete"`** via `check_action` so the footer hint and the binding both disappear once the sample finishes — nothing to cancel on a terminal sample.
- **`Esc` layered semantics** — `action_interrupt` now dismisses a visible cancel bar first (operator backed out of cancelling), then clears the composer draft, then sends `session/cancel`. The cancel-bar takeover is highest precedence so `esc` reads as "back out of this prompt" consistently across all composer-area bars.
- **Footer right-cluster (`AppFooter` subclass)** — `cancel sample | switch sample | quit` cluster sits flush-right via a `1fr` `_FooterSpacer` between the everyday left-group bindings and the right cluster. The three "end or navigate away from this session" actions read as a visual unit at the screen edge.

**Protocol extensions landed**: `failsOnError` field added to the picker target's `_meta` shape (carried by `picker_target_meta_dict`); reaches the client over the picker notification, the `inspect/list_sessions` response, and the binding-confirmation `session/update`. `inspect/cancel_sample` itself was already in place from `agent-acp.md` Phase 12.

**Acceptance**

- Manual: start a long-running eval with `--acp-server`; attach via `inspect acp`; hit `^N`; observe the bar take the composer row with `[ s ] Cancel: Score   [ e ] Cancel: Error   [ esc ] Go Back`. Press `s` and confirm the sample finishes via the scorer; restart with `--fail-on-error` set and confirm `[e]` is hidden + body collapses to just `[ s ] / [ esc ]`. Restart again with `--fail-on-error=0.2` and confirm `[e]` is still hidden (fractional thresholds collapse to `fails_on_error=True`, same as `--display full`).
- Manual: connect via `session/load(<sessionId>)` directly (bypassing the picker); confirm the bar's `[e]` visibility still tracks `fails_on_error` correctly — the binding-confirmation `_meta` carries the value on this path too.
- Manual: hit `^N`, then `esc` — the bar dismisses cleanly without firing the request.
- Manual: footer reads `…  ^p plan   ^n cancel sample   ^s switch sample   ^c quit` with the right cluster flushed to the screen edge.
- Automated: pilot tests for `^N` open/dismiss, bare-letter `s` / `e`, focus-on-mount on the score option, Tab navigation through both two-choice and single-choice bars, composer-Input hidden while bar visible, `^N` no-op when `lifecycle == "complete"`, footer right-cluster layout. Pure-function tests for `SessionRow.fails_on_error` parsing on both wire paths. Server-side `inspect/cancel_sample` handler tests pin the `fails_on_error` polarity check.


### Phase 5 — Scoring lifecycle ✅

Scoring runs AFTER the agent's `acp_session()` context manager exits, so without this phase `ScoreEvent`s emitted during scoring never reach attached ACP clients — the connection has already closed by the time the scorer fires. The original Phase 5 spec listed three lifecycle-fix options (move the `acp_session()` scope up; decouple session lifetime from the agent entirely; introduce a "scoring-only" sub-state). The implementation picked a **hybrid of (b) + (c)**: the session became transport-agnostic AND split-phase, with explicit registration hooks the eval primitive fires rather than ACP-specific direct calls.

**Two pivots from the original spec:**

1. **From "Pick (a) or (b) or (c)" → split-phase teardown + registration hooks.** The session's `__aexit__` parks (clears interrupt coordinator + approver registry; keeps router + pubsub attached) when bound to an `ActiveSample`; a new async `finalize()` method does the full deferred teardown, called from `active_sample().__aexit__` after scoring + logging finish. `ActiveSample` carries two callback slots (`on_complete` async, `on_interrupt` sync) that `LiveAcpSession.__aenter__` registers — the eval primitive doesn't import the ACP layer at all. The registration-hook pattern came in second-pass: the first cut had `active_sample().__aexit__` use `getattr(sess, "finalize", None)` duck-typing, which an architectural review flagged as cross-layer coupling. Replacing duck-type with explicit hooks dissolved three review concerns at once (cross-layer coupling, `isinstance` hedge in the predecessor handoff, and the cancel-sample semantic coupling discussed below).

2. **From "dedicated `inspect/sampleCompleted` notification + mid-stream `ScoreEvent` → `session/update`" → raw events firehose subscription.** The originally-spec'd dedicated `sampleCompleted` notification was dropped — `inspect/session_ended` + in-stream score chips give the operator the same signal without protocol surface growth. Mid-stream score chips piggyback on the existing `inspect/event` raw firehose (`agent-acp.md` Phase 10) by subscribing to `["score", "span_begin", "span_end"]` — the TUI takes a documented coupling to Inspect's internal `score` event discriminator and the `"scorers"` / `"scorer"` span names (the latter lifted to named constants for visibility). A dedicated `inspect/scoring_*` notification family was considered and rejected as redundant: the raw firehose is already Inspect-aware and the span names are stable load-bearing identifiers across multiple downstream consumers (log/timeline reconstruction, etc.).

**Ships**

- **Split-phase session lifecycle** (`agent/_acp/session_live.py`). `LiveAcpSession.__aexit__` now branches on whether the session is bound to an `ActiveSample`: **bound** parks (sets `_agent_completed=True`; clears `_interrupt._subscribers` and the `_approvers` registry; keeps the router + pubsub + `ActiveSample.acp_session` binding alive); **unbound** does immediate full teardown (reached by tests that build `LiveAcpSession()` directly AND by production when `__aenter__`'s `acp_guard("ACP session: ActiveSample registration failed")` catches an exception, leaving `active.acp_session` unassigned). New `finalize()` async method does the deferred teardown — idempotent via a `_finalized` flag, with an `is self` identity guard that protects `active.acp_session` from being cleared when a successor has already bound. **Predecessor handoff**: when a solver runs two agents consecutively in the same sample, the successor's `__aenter__` awaits `prev.finalize()` before assigning itself, so the predecessor's router detaches and clients bound to its sessionId see EOF + `inspect/session_ended` before the new binding takes over. **Six post-agent guards**: every public method reachable after parking checks `self._agent_completed` and no-ops gracefully — `before_turn` / `after_cancel` / `turn_scope` are loop-only invariants (agent loop has exited by the time `_agent_completed` is True; the guards are defense-in-depth against programming bugs), while `submit_user_message` / `cancel_current_turn` / `attach_approver_client` are legitimate network-reachable defenses (wire `session/prompt`, TUI Send button, fresh `Forwarders.start` chain during scoring all land at unpredictable moments).

- **ActiveSample callback hooks** (`log/_samples.py`). Two new slots: `on_complete: Callable[[], Awaitable[None]] | None` (async, called from `active_sample().__aexit__` shielded, with WARNING-log on failure — replacing the prior silent `except Exception: pass`) and `on_interrupt: Callable[[], None] | None` (sync, called by a new `_fire_on_interrupt()` helper from `interrupt()` AND `limit_exceeded()` before `tg.cancel_scope.cancel()`, wrapped + logged). Replaces the prior direct `getattr(sess, "finalize", None)` duck-type in `_samples.py`. `LiveAcpSession.__aenter__` registers both callbacks alongside the existing `active.acp_session = self` write; `finalize()` clears all three under the same `is self` identity guard. **Strict improvement** over the pre-Phase-5 ACP-only `connection.py:cancel_sample` direct call: timeouts and limit-exceededs now also clean up in-flight `ModelEvent.pending=True` via the hook, not just operator-driven sample cancels.

- **TUI score chip rendering** (`agent/_acp/tui/state.py`, `agent/_acp/tui/widgets/score.py`, `agent/_acp/tui/widgets/transcript.py`). New `ScoreChip` dataclass with `(scorer, value, passed, reason, chip_id, span_id)` fields. New `ScoreChipWidget` with a controlled-content header (`score · <scorer> · value <v> · passed`) plus an optional `CollapsibleContent`-wrapped markdown body for the score explanation — the split keeps Rich's `markup=True` parser away from score text that contains source snippets, diffs, brackets, or backslashes (which would otherwise raise `MarkupError` and take down the whole transcript render); every spliced-in value runs through `escape_markup`. `_format_score_value` mirrors `Score.as_str` for scalars + falls back to `repr` for non-scalar shapes. Wired into the transcript via the union extension `TranscriptItem = Union[MessageGroup, ToolCallState, ScoreChip]` and the matching `_build_widget` / `_fingerprint` / `_key_for` branches.

- **Scoring-phase consumption** (`agent/_acp/tui/state.py`). New `consume_inspect_event` routes the `inspect/event` raw firehose by `event["event"]` discriminator: `"score"` → `consume_score_event` (mounts chip), `"span_begin"` → `_consume_span_begin` (recognises outer scoring boundary + per-scorer indicator), `"span_end"` → `_consume_span_end` (clears indicator when its scorer's span closes without firing a `ScoreEvent`). The outer `span(name=SCORERS_SPAN_NAME)` boundary clears the plan strip (`plan_entries=None`) and latches a new sticky `_scoring_started: bool` flag — any subsequent `AgentPlanUpdate` is suppressed by `_consume_plan_update` (covers the late-attach race where raw replay clears the plan and semantic replay would otherwise re-mount the historical AgentPlanUpdate that was live mid-agent). Per-scorer `span(type=SCORER_SPAN_TYPE)` mounts a `scoring · <name>…` indicator chip with the span id stamped onto `ScoreChip.span_id`; whichever of the matching `ScoreEvent` (replaces the placeholder) or `span_end` (no score fired — scorer returned None or raised) arrives first removes it. At most one indicator is live at a time (scorers run sequentially in the task runner's loop). `mark_complete` drops any stranded indicator so the read-only postmortem view doesn't show a phantom in-progress scorer.

- **Span name constants** (`util/_span.py`, `_eval/score.py`, `agent/_acp/tui/state.py`). `SCORERS_SPAN_NAME = "scorers"` and `SCORER_SPAN_TYPE = "scorer"` lifted next to `AGENT_SPAN_TYPE` in `util/_span.py`. The producer (`_eval/score.py`'s scorer loop) and the consumer (`tui/state.py`'s `_consume_span_begin`) share one source of truth — a future span rename is a single-grep audit. The TUI's coupling is now visible and centralised, not scattered across four magic-string sites.

- **Raw events subscription protocol shift** (`agent/_acp/connection.py`, `agent/_acp/inspect_ext.py`, `agent/_acp/session_router.py`, `agent/_acp/tui/client.py`). `ConnectionState.raw_events_enabled: bool` → `raw_events_subscription: frozenset[str] | None`. Wire-side `_meta[RAW_EVENTS_META_KEY]` value shape: `bool` → `list[str]` (event type names, with `"*"` glob sentinel — the forwarder's membership check treats glob and named-subscription uniformly). `_decode_raw_events_subscription` handles the migration: missing / empty list → None, all-strings list → frozenset, anything else (including the legacy bool form) → None + one-shot warning. `RawEventForwarder._matches` filters by event type BEFORE serialization (pays the `model_dump` cost only for events the client subscribed to). The pre-condensation guarantee from `agent-acp.md` Phase 10 still holds — filter is by event-type string, which is intrinsic to the event class. `attach_session` in `tui/client.py` registers the new `inspect/event` notification route; `CLIENT_CAPABILITIES` advertises `RAW_EVENTS_META_KEY: ["score", "span_begin", "span_end"]`.

- **Interleaved replay** (`agent/_acp/session_router.py`, `agent/_acp/event_mapping.py`). Replay-on-attach rewritten from "raw pass, then semantic pass" to a single walk over the snapshot in transcript source-order, dispatching to whichever streams subscribed via `id(event)`-keyed sets. New stateful `ReplayTranscriptor` class wraps the depth-tracker + dedup state so callers can feed events one at a time and still get the same notifications, same order, as the batch `replay_transcript` would. On late attach, score chips now appear AFTER the conversation that produced them and plan updates land at their original timestamp — preserves wire ordering across the two streams. `id()` is safe because the snapshot holds strong refs (no GC reuse risk) and Pydantic value-equality would otherwise collide in a hash-keyed set. `_scoring_started` flag on the TUI is a complementary belt-and-braces defense — interleaved replay fixes the structural ordering problem; the flag protects against any straggling out-of-order plan update from live forwarding too.

- **Cancel-sample lifecycle smoothing** (`agent/_acp/tui/widgets/cancel_sample.py`, `agent/_acp/tui/state.py`, `agent/_acp/connection.py`). New `mark_sample_cancelling()` / `rollback_sample_cancelling()` lifecycle methods on `SessionState`. Sibling to `mark_interrupted` but flips `_cancelling=True` instead of `_interrupted=True` — the pill keeps reading `running` (NOT `interrupted`) through the server-side scoring + finalize teardown window. Shared `_clear_active_work_signals()` helper holds the in-flight cleanup (drop empty pending message groups, mark in-flight tool calls failed, resolve pending approvals as cancelled); the two public methods diverge only on the lifecycle flag they set. `_CancelSampleBar.choose` calls `state.mark_sample_cancelling()` BEFORE sending the RPC for instant feedback (the spinning assistant chip + live tool-call timer flip to terminal immediately, rather than waiting for the server's cancel propagation through scoring + finalize); on RPC failure `_fire_cancel` calls `state.rollback_sample_cancelling()` (only `_cancelling` is rolled back — the in-flight cleanup is honest post-condition of the operator's intent). `connection.py:cancel_sample` no longer does its own `_find_live_session` + `target.cancel_current_turn()` — `sample.interrupt(action)` now drives it via the registered `on_interrupt` hook (and the same cleanup runs for non-ACP cancels: timeouts, token limits, etc., as a strict improvement).

- **Stream buffer + log noise** (`agent/_acp/_config.py`, `agent/_acp/_guards.py`, `agent/_acp/server.py`, `agent/_acp/stdio.py`, `agent/_acp/tui/client.py`). New `ACP_STREAM_BUFFER_LIMIT: Final[int] = 64 * 1024 * 1024` constant (in a new `_config.py` module — `_guards.py` returns to exception-handling helpers only) applied as the `limit=` arg to every `asyncio.start_unix_server` / `start_server` / `open_unix_connection` / `open_connection` call. Motivation: swe-bench-class scorers can carry a 500KB+ `Score.explanation` (test stdout/stderr captured verbatim into the score) — asyncio's 64 KiB default readline buffer raises `LimitOverrunError` on a single line that exceeds it, crashing the TUI receive loop and freezing the operator's UI on `scoring · X…` because the matching score chip never arrived. New `_AcpDisconnectFilter` root-logger filter suppresses upstream `acp` library tracebacks for routine peer disconnects: the upstream uses `logging.exception(...)` (root logger, not a named logger — verified at `acp/connection.py:120,264` and `acp/task/sender.py:67`) on every peer disconnect, so without the filter the eval console gets two or three full BrokenPipe / ConnectionResetError tracebacks per disconnect. Filter is tightly scoped: matches the three exact upstream message strings AND only suppresses when the exception is in `NORMAL_DISCONNECT_EXC`. Installed once from `AcpServer._serve` (idempotent). `AcpServer._on_connection` close-after-disconnect failures log at DEBUG (not ERROR) for the same noise-suppression reason.

**Protocol extensions landed**

- `RAW_EVENTS_META_KEY` value shape: `bool` → `list[str]` (frozenset of event-type names server-side; `"*"` glob sentinel for "all events"). Malformed values (including the legacy `bool` form) decode to None (no subscription) with a one-shot warning. The legacy bool form was never advertised externally — the TUI is the only first-party client.
- No new dedicated methods. `inspect/sampleCompleted` (originally spec'd) was dropped — `inspect/session_ended` + in-stream `ScoreEvent`s via `inspect/event` give the operator the same signal without protocol surface growth.

**Acceptance**

- Manual: `inspect eval <task> --acp-server` with a multi-scorer task; attach via `inspect acp`. Mid-stream score events render as inline `ScoreChipWidget`s with the right header (`score · <scorer> · value <v> · passed/failed`) plus an expandable markdown body for the explanation. Multi-scorer runs show per-scorer `scoring · X…` indicators that replace cleanly with the real score chip when each scorer completes; if a scorer returns None or raises, the indicator clears via the matching `span_end`. The plan strip clears the moment scoring starts and stays cleared. Running the eval with a swe-bench-style scorer that emits a >100 KB `Score.explanation` no longer breaks the TUI receive loop. Eval console no longer shows BrokenPipe tracebacks on TUI disconnect.
- Manual (cancel sample): `^N` → `[s] Cancel: Score` → the assistant chip and live tool-call timer flip to terminal state immediately (within one tick); the pill keeps reading `running` (not `interrupted`) through scoring + finalize; transitions cleanly to `complete` on `inspect/session_ended`. With `--fail-on-error` set, the `[e] Cancel: Error` choice is hidden as before. RPC failure (kill the server mid-cancel) rolls back the lifecycle pill cleanly.
- Automated: pure-function tests in `tests/agent/test_acp/test_tui/test_scoring.py` cover `consume_score_event` mounting, chip-window rotation alongside the conversation cap, `consume_inspect_event` dispatch, indicator mount/clear lifecycle, plan-update suppression after `_scoring_started`, `mark_sample_cancelling` / `rollback_sample_cancelling` lifecycle transitions. New tests in `tests/agent/test_acp/test_active_sample_link.py` cover the registration hooks: callback registration on `__aenter__`, identity-guard on `finalize` doesn't clear a successor's hooks, `sample.interrupt()` and `sample.limit_exceeded()` fire `on_interrupt`, hook-raise doesn't block the cancel propagation, `on_complete` fires from `active_sample()` exit, `on_complete` failure is logged + swallowed. Disconnect-log-filter tests in `tests/agent/test_acp/test_disconnect_log_filter.py` cover the filter (drops disconnect tracebacks for matching messages + matching exceptions; passes real failures + unrelated messages through; idempotent install; end-to-end via root-logger emit).

**Known v1 gaps (intentional)**

- **No structured "scoring started" or per-scorer notifications on the wire.** The TUI takes a documented dependency on the `score` / `span_begin` / `span_end` raw-event types AND on the `"scorers"` / `"scorer"` internal span names (lifted to constants for centralisation but still internal). The alternative — dedicated `inspect/scoring_started` / `inspect/scorer_started` / `inspect/scorer_ended` notifications in `inspect_ext.py` — was considered and rejected as redundant: the raw firehose is already Inspect-aware and the span names are load-bearing identifiers across multiple downstream consumers (log/timeline reconstruction, etc.) so a silent rename is structurally unlikely.
- **`_AcpDisconnectFilter` is a permanent root-logger filter, not context-managed to the AcpServer's lifetime.** Upstream `acp` library uses `logging.exception(...)` (root logger) directly, so a tighter logger scope isn't available. Context-managed install was considered but adds complexity for marginal benefit; the filter is tightly scoped via exact message-string match AND exception-type filter, so blast radius is already minimal.
- **No terminal "sample complete / errored" banner yet** — Phase 6 (terminal states) covers the green "Completed" / red "Errored" banner with the score line. Phase 5 ships the in-stream chips that lead up to it.

### Phase 6 — Connection resilience ✅

Originally bundled terminal banners + reconnect + replay/footer; split for shipping. This phase covers the **connection lifecycle resilience** layer; the Completed banner, the Errored banner + `errored` lifecycle, and `^C copy traceback` move to Phase 7 alongside the score/error rendering they depend on. `^O open log` dropped entirely. `^R rescan` stays Phase 8 (picker work). Replay payload elision rejected — payloads are naturally bounded by model context windows and the 64 MiB stream buffer from Phase 5 handles outliers (closes [`agent-acp.md`](agent-acp.md) open question #1).

Motivating real-world case: remote attach via `--server host:port` — transient Wi-Fi drops, VPN renegotiation, NAT idle-timeout RSTs shouldn't lose the operator's session. Local AF_UNIX deployments rarely need it (the eval process dying takes the socket with it) but get the same passive behaviour for free — the dot stays amber and the operator hits `^S` to return to the picker.

A clean disconnect (`inspect/session_ended` arrived before EOF) is **not** reconnect-eligible — the sample is genuinely over, `mark_complete` fires as today. The reconnect machinery only kicks in for ungraceful transport loss.

**Ships**

- **`AttachedSession` reconnect coordinator** (`tui/client.py`). Replaces the prior "set `disconnected` and give up" path. The coordinator runs as a long-lived task spawned post-handshake; it watches the per-connection receive task for exit, distinguishes graceful (session_ended received → don't reconnect) from ungraceful (retry forever) via `SessionState.session_ended_received`, and on ungraceful loss flips `state.mark_disconnected()`, kicks off a toast cadence task, and drives an exponential-backoff retry loop (1s, 2s, 4s, 8s, 16s, then capped at 30s indefinitely). On success it rebuilds the Connection + writer + receive task in place — `self._session.connection` references read through the swap transparently from the screen's POV. On `session/load` returning `invalid_params` (target sample ended during the disconnect window) it calls `mark_complete()` + emits the "Sample ended during disconnect" toast and stops. Forever-retry by design — the operator hits `^S switch sample` (already wired) to bail; there is NO cap that would surprise-give-up.
- **`_establish_connection`** (private) extracts the socket-open + initialize + session/load handshake from the previous monolithic `attach_session`, so the initial attach AND every reconnect go through one code path (one place to audit for handshake regressions, one place where partial-build teardown lives).
- **`SessionState._disconnected` + `_session_ended_received` flags** (`tui/state.py`). Orthogonal to the existing `lifecycle` literal — connection state is about **transport** health, lifecycle describes **agent-side** activity; conflating them would lie about either when they diverge (brief socket blip during a "running" agent). `mark_disconnected` / `mark_reconnected` / `mark_session_ended_received` mutate the flags + notify subscribers. The `disconnected` property is gated on NOT `_complete` so terminal sessions always read as connected. Caching the target sessionId on the existing `SessionRow.session_id` was sufficient — no new state needed for the reconnect target.
- **`session/load` calls `state.mark_session_ended_received()` before `mark_complete()`** (`tui/client.py` `_build_session_router._on_session_ended`). The order is load-bearing: the coordinator's graceful-vs-ungraceful check reads `session_ended_received` when the receive loop subsequently exits; setting it before the lifecycle flip ensures the coordinator sees it whether the receive-loop exit precedes or follows the screen's mark_complete observation.
- **Toast cadence** (`AttachedSession._toast_cadence`). First "Reconnecting to ACP server (disconnected N minute…)" toast fires at ≥60s after the disconnect — fast glitches (sub-minute recoveries) deliberately don't nag. Subsequent toasts every 60s, with elapsed-time formatting. One "Reconnected to ACP server" toast on success. One "Sample ended during disconnect" toast on `invalid_params`. All emitted via `app.notify` through a thin adapter wired in `app.py:_attach_and_show`. Toasts are the *only* operator-visible disconnect signal in v1 — there is no header indicator (a connection-status dot was prototyped and pulled as visual noise; the toast cadence is sufficient because sub-60s glitches don't need attention and longer disconnects get explicit narration).
- **Send-while-disconnected guard** (`tui/session_screen.py` `action_submit`). Early-return that toasts "Not connected to ACP server — message not sent" (severity=warning) and preserves the composer draft. Without this guard, sending into a dead writer would either block on the never-resolved response future OR raise mid-await (existing toast catches that, but the draft would already be cleared by then). The draft survives so the operator can re-send once the next reconnect toast confirms transport is back.
- **Server-stamped replay marker + client chunk replay-reset dedup** (`inspect_ext.py` `REPLAY_META_KEY = "inspect.replay"`, `session_router.py` `_stamp_replay_marker`, `tui/state.py` `_consume_chunk` / `mark_replay_started` / `_replay_reset_message_ids`). On reconnect the server's `session/load` runs the standard replay-on-attach flow (snapshot of last 100 events from `Transcript._events`, mapped + plan-policy-transformed, sent as a `session/update` stream). Without dedup, replayed `agent_message_chunk` / `user_message_chunk` / `system_message_chunk` sequences would double the rendered text since `_append_segment` extends the last segment. A heuristic dedup based on `inspect.model_event_complete` markers + pending-signal restart misses the common cases — normal in-flight assistant content (no completion marker yet), and user/system chunks which never emit the completion marker at all. Fix: the server stamps `REPLAY_META_KEY = True` on the OUTER `SessionNotification.field_meta` for every notification emitted by the replay path; live forwarding never sets it. The client checks the outer meta in `consume`, threads `is_replay` into `_consume_chunk`, and on the first replayed chunk for a given message id (tracked in `_replay_reset_message_ids`, cleared by `mark_replay_started` at the start of each new replay) clears `segments` before applying. Symmetric across all chunk kinds. Tool calls (id-keyed), plan updates (full replacement), usage (snapshot) are already idempotent — no changes needed.
- **Raw-event replay-dedup** (`tui/state.py` `consume_inspect_event`). Each `inspect/event` payload carries a stable `uuid` from `BaseEvent`. The `_seen_inspect_event_uuids` set early-returns on duplicates so replayed score events don't double-mount score chips and replayed `span_begin` events don't re-mount per-scorer indicators after the real score chip has replaced them.
- **`_watch_disconnect` semantics updated** (`tui/session_screen.py`). The `session.disconnected` event is now fired ONLY on terminal teardown (close / session_ended after the receive loop drains / session_gone after reconnect rejection). Transient ungraceful disconnects are handled internally by the coordinator and never set `disconnected`. The watch task still calls `mark_complete` as a defensive idempotent backstop.

**Already shipped (Phase 10 / Phase 5) — documented here for completeness**:

- Server-side replay snapshot + cap (`session_router.py:50` `REPLAY_MAX_EVENTS = 100`; `session_router.py:172` snapshot on bind; `session_router.py:460-575` interleaved semantic + raw replay).
- `session/load` rebind triggers fresh replay (`connection.py:274-282` calls `_stop_forwarders` → `_start_forwarders` → fresh snapshot + replay). Because `Transcript._events` accumulates regardless of whether a subscriber is bound (`session_live.py:378-383`), the snapshot taken at reconnect-time naturally includes events emitted during the gap (subject to the tail-100 cap).
- `inspect/session_ended` notification (`inspect_ext.py:119` constant; `session_router.py:357-369` `_send_session_ended` fires after raw drain on clean stream EOF).
- `^S switch sample` already wired (`session_screen.py:532-535`).

**Protocol extensions landed**: one. `REPLAY_META_KEY = "inspect.replay"` is stamped on the OUTER `SessionNotification.field_meta` for every notification emitted by the server's replay-on-attach path; live forwarding never sets it. The client uses the marker to drive symmetric replay-reset dedup across all chunk kinds (assistant / user / system). The replay machinery itself, `session/load` semantics, and `inspect/session_ended` were already in place from Phase 10 / Phase 5; this phase wires them into the resilience UX.

**Acceptance**

- Manual (local AF_UNIX): `inspect eval <task> --acp-server` long-running; attach via `inspect acp`; `kill -9 <eval_pid>`. Dot flips amber; after ~60s the "Reconnecting" toast appears; retries continue indefinitely. Operator hits `^S` to return to the picker. No crash, no spurious "Reconnected" against a different eval.
- Manual (simulated network drop, TCP): `inspect eval <task> --acp-server=12345` + `inspect acp --server 127.0.0.1:12345`; briefly block the port (e.g. `sudo pfctl` rule); dot amber, retry loop runs; remove block; dot green, "Reconnected" toast, replay catches the transcript up.
- Manual (clean end): start eval, attach, wait for sample to complete normally. `inspect/session_ended` arrives, lifecycle flips to `complete`, NO reconnect attempted, NO disconnect toast.
- Manual (send-while-disconnected): during a disconnect window, type into the composer and hit Enter; toast appears, draft preserved.
- Automated: `tests/agent/test_acp/test_tui/test_reconnect.py` (state transitions, backoff schedule, invalid_params → mark_complete, toast cadence, send-while-disconnected pilot, receive-loop finally-closes-connection regression). `tests/agent/test_acp/test_tui/test_replay_dedup.py` (chunk replay reset, raw event uuid dedup, regression coverage for already-idempotent paths). Pre-existing TUI suite green with no regressions.

**Known v1 gaps (intentional)**

- **No reconnect overlay / countdown UI / header indicator.** Toasts are the entire UX. An overlay-with-countdown was considered (per the original spec mockup) and dropped as too aggressive: it would force operator attention even for sub-minute glitches that recover before they're noticed. A persistent header dot was also prototyped and pulled as visual noise — the toast cadence (silent for the first 60s, then once per minute) lands in the right place and doesn't add a permanent chrome element for a transient condition.
- **No max-attempts cap.** Forever-retry. The operator's `^S switch sample` is the bail-out. A cap would risk surprising the operator with "gave up after N minutes" when they expected the connection to come back.
- **No special handling for the rare race** where reconnect succeeds but a fresh disconnect happens before the "Reconnected" toast renders. The toast just fires and immediately the dot flips back to amber; harmless cosmetic flicker.
- **`_watch_disconnect` keeps `mark_complete` as a defensive backstop** even though all current code paths call it explicitly. Cheap idempotent call; protects against future code paths that might set `session.disconnected` without going through one of the established transitions.

### Phase 7 — Rich event rendering

Fidelity work: covers every remaining event type from the events-stream mockup. Doesn't unlock new capability, but it's what makes the transcript actually readable for non-trivial agents.

**Ships**

- Reasoning blocks: visible-summary / encrypted-with-summary / encrypted-no-summary / redacted ([03a](images/03a-reasoning-variants.png)).
- Info events with structured-JSON payload rendering ([02e](images/02e-events-stream.png)).
- Compaction banner (`messages X → Y · tokens X → Y`).
- Turn-interrupt banner with reason + actor.
- Operator-intervention marker (purple banner on injected user messages).
- Retry counter chip during `Generating`.

(Plan updates already landed via the plan strip/overlay above — not duplicated here.)

**Protocol extensions landed**: retry-counter notifications (`retry: { attempt, max }`), reasoning-variant discriminator on the reasoning chunk, operator-intervention marker on injected user messages, `inspect/info` notification, compaction event crossing the ACP boundary, and turn-interrupt reason / actor fields on the `InterruptEvent`.

**Acceptance**

- Manual: a synthetic eval emits every variant; each renders per the mockups.
- Automated: snapshot test per variant.

### Phase 8 — Picker theming / appearance / functionality

Improvements to the attach picker — both visual polish and live-multi-sample ergonomics. The shipped picker is functional but minimal; this phase makes it pleasant to live with as evals proliferate and incorporates the original "multi-sample navigation" goal as one piece of the broader picker rework.

**Ships**

- Visual refresh: typography pass, column tuning, hover / focus states matching the rest of the TUI chrome.
- **Multi-sample navigation** — `^S` reopens the picker in place without exiting the App; drain the current session cleanly and attach to the selected one without a process restart.
- Picker shows live status + running time across concurrent samples (exercises the `started_at` / running-secs field on the `inspect/list_sessions` response in the multi-sample case).
- Refresh ergonomics — explicit `^R` rescan in addition to the existing periodic poll.
- Filtering / sorting in-app (complements the existing `--eval-id` startup flag).

**Protocol extensions landed**: (none new — relies on the already-landed `inspect/list_sessions` payload).

**Acceptance**

- Manual: multi-sample eval; navigate between two samples; transcripts switch cleanly; original session's notifications drained. Picker stays readable as evals come and go.
- Automated: pilot test for the swap sequence; snapshot tests for picker visual states (empty / one eval / many evals / one sample greying out mid-display).

### Cross-cutting

- **Standalone code** — per the Constraints section above, the TUI is its own self-contained Textual app. The shipped widgets (picker, app shell, `SessionScreen`, transcript, plan strip) are built fresh rather than extended from `src/inspect_ai/_display/textual/`; later phases follow the same rule.
- **Test scaffolding** — Textual `Pilot` infra under `tests/agent/test_acp/test_tui/` is in place; every new phase adds snapshots / pilot tests for its new widgets.
- **Synthetic test eval** — a single growing "kitchen-sink" eval fixture that exercises every codepath used by the phases shipped so far. Lives alongside other ACP test fixtures. `demo_plan_eval.py` at the repo root is the current minimal example (plan widget exercise); fold it into the kitchen-sink fixture or replace as more phases land.
- **Test selection during iteration** — TUI work iterates on visual + interaction details, so it's tempting to run the full ACP suite (`tests/agent/test_acp/`) on every change. Don't: ~400 tests at ~3–4s is dead time during quick visual loops. Instead:
    - **Fast loop**: `pytest tests/agent/test_acp/test_tui/` — runs only the pure-function unit tests (`_format_running`, `_format_tokens`, `_row_matches`, …) in well under a second. These cover the formatters and pure logic that change most often during UI iteration.
    - **Pre-commit / structural changes**: `pytest tests/agent/test_acp/test_tui/ --runslow` — adds the Pilot tests (every `app.run_test()`-based test is marked `@pytest.mark.slow`, either per-test or via module-level `pytestmark`). Run this before committing UI changes and whenever you've touched bindings, focus handling, or screen composition.
    - **Touching `picker.py` / `server.py` / `client.py`**: also run `pytest tests/agent/test_acp/test_picker.py tests/agent/test_acp/test_server_dispatch.py` (sub-second) — these pin the picker payload shape and `inspect/list_sessions` response that the TUI client consumes.
    - **Full ACP regression**: `pytest tests/agent/test_acp/ tests/_cli/test_acp_cli.py --runslow` — only when changing protocol shapes, server dispatch, or anything that crosses the wire.
    The pilot tests catch real screen-level regressions (binding shadowing, focus order, column-key bugs) that pure unit tests miss; keep marking new pilot tests `slow` so the fast loop stays fast.
- **[`agent-acp.md`](agent-acp.md) Phase 15 collapse** — outstanding bookkeeping. The original transport + picker work has shipped; [`agent-acp.md`](agent-acp.md)'s `Phase 15` body should be replaced with a pointer to this doc.
- **Phase 16 (token-level streaming)** in [`agent-acp.md`](agent-acp.md) remains independent and can land any time.
