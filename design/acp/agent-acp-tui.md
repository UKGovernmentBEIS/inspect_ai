# inspect acp — TUI

A keyboard-first Textual TUI for attaching to running Inspect AI eval samples: chat with the agent, watch its tools, intervene mid-flight.

Invoked as `inspect acp` from a separate terminal while an eval is running with the ACP server enabled. Single sample per attach for v1; switch between samples via `^S`.

The visual spec is **[`inspect acp — TUI design (print).pdf`](inspect%20acp%20—%20TUI%20design%20%28print%29.pdf)**. Crops of each mockup accompany the sections below.

For the broader ACP design (server, sessions, router, asyncio boundary, phased build), see **[`agent-acp.md`](agent-acp.md)**. This doc is the TUI-client surface only.

## Constraints

- **Standalone client** — the TUI is built as a self-contained Textual app and **does not reuse existing Textual code in this repo** (e.g. the `--display full` app under `src/inspect_ai/_display/textual/`). We may want to ship the `inspect acp` binary separately from the main `inspect` package, so its only hard dependencies are `textual` itself, the `acp` Python library, and a thin slice of types shared with the ACP server side.
- **Single sample per attach** for v1; multi-sample navigation is Phase 7.
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

- **Meta row** — `inspect acp · eval <id> · task <name> · sample <n>/epoch <m> · agent <name>` + connection indicator
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
| Connected | quiet green dot in meta row; no overlay | all live pages |
| Reconnecting | amber dot; banner with attempt count + next-retry countdown; transcript dimmed; events replay on reconnect | [06c](images/06c-terminal-disconnected-reconnecting.png) |
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

Bare letters work directly: `a` / `o` / `d` in approval, `s` / `e` in cancel-sample, `↑↓ ↵ /` in pickers.

## `inspect/*` protocol extensions implied by the UI

Several UI elements depend on data that the current ACP surface doesn't expose. Each is listed below with the originating mockup, the data needed, and a tentative method / field name. The pattern follows the existing `inspect/new_session` extension method.

These are flagged here for discussion; the actual extension contracts will be locked in alongside their consumers and recorded in [`agent-acp.md`](agent-acp.md).

1. **Running time per sample** — picker shows `running` column ([04b](images/04b-attach-picker-table.png)). `inspect/listSessions` response needs `started_at` (or pre-computed `running_secs`) per session.

2. **Tools-in-flight count** — header chip `2 tools in flight` ([01](images/01-primary-pane-calling-tools.png)). Derivable client-side from open `tool_call` notifications; if we prefer server-canonical, add `tools_in_flight: int` to a session-state notification.

3. **Running token usage** — header chip `tokens 12.4k` ([01](images/01-primary-pane-calling-tools.png)). New `inspect/sessionStats` push (or extra fields on `session/update`) with running `input_tokens` / `output_tokens` / `total_tokens`.

4. **Retry counter** — `retry 1/3` chip during `Generating` ([02b](images/02b-state-generating-retry-with-intervention.png)). Model-retry events surfaced through `session/update` with `retry: { attempt, max }`.

5. **Agent name** — `agent react` in meta row ([01](images/01-primary-pane-calling-tools.png)). `inspect/new_session` response (or `inspect/sessionInfo`) carries the `@agent`-registered name.

6. **Reasoning block variants** — visible / encrypted-with-summary / encrypted-no-summary / redacted ([03a](images/03a-reasoning-variants.png)). The reasoning `agent_message_chunk` needs a discriminator (`reasoning_kind`) and optional `summary` text.

7. **Operator intervention marker** — purple banner for a user message injected during cancellation ([02b](images/02b-state-generating-retry-with-intervention.png), [02e](images/02e-events-stream.png)). The user-message event needs an `intervention: true` flag (or the surrounding `InterruptEvent → user_message → resume` sequence must be distinguishable client-side).

8. **Plan updates as ephemeral notifications** — separate visual treatment from regular events ([02d](images/02d-state-plan-update-ephemeral.png)). Either a `transient: true` flag on `session/update`, or a dedicated `inspect/planUpdate` notification.

9. **Tool-call timing** — each card shows duration ([01](images/01-primary-pane-calling-tools.png), [03b](images/03b-tool-call-card-anatomy.png)). `tool_call` start/end timestamps in the notification stream, or a `duration_ms` field on the completed update.

10. **`inspect/cancel_sample` method** — modal offers `score` vs `error` disposition ([05b](images/05b-modal-cancel-sample.png)). New method, distinct from ACP's `session/cancel` (which only cancels the current turn): `inspect/cancel_sample { disposition: "score" | "error" }`.

11. **Sample-completed notification with score** — terminal banner shows score line ([06a](images/06a-terminal-completed.png)). Final `inspect/sampleCompleted` notification carrying the scorer output (or equivalent appended to the standard stream).

12. **Sample-errored notification with traceback** — terminal banner shows traceback frames ([06b](images/06b-terminal-errored.png)). `inspect/sampleErrored { error_type, message, traceback: [Frame] }`.

13. **Replay on reconnect** — "events will replay on reconnect" overlay ([06c](images/06c-terminal-disconnected-reconnecting.png)). Confirms the server-side buffering decision from `agent-acp.md`'s open question #1; the TUI relies on it. Need to settle the buffer size + elision rules.

14. **`info` events** — subsystem-level diagnostic surfaced into the transcript ([02e](images/02e-events-stream.png)). New `inspect/info` notification carrying `source: str` (e.g. `inspect.utils.bash`, `benchmark.harness`), `message: str`, optional `payload: dict`, and `timestamp`.

15. **Compaction events** — `messages X → Y · tokens X → Y` banner ([02e](images/02e-events-stream.png)). The existing `CompactionEvent` in the transcript needs to traverse the ACP boundary — either via `session/update` with discriminator, or `inspect/compactionEvent { messages_before, messages_after, tokens_before, tokens_after, strategy, summary_preserved: bool }`.

16. **Mid-stream / intermediate score events** — `score · includes · value <v> · passed` mid-conversation ([02e](images/02e-events-stream.png)). The existing `ScoreEvent` can fire before the sample terminates (multi-turn or intermediate scorers); the stream needs to carry these distinctly from the terminal sample-completed banner.

17. **Turn-interrupt reason / note** — `by operator · redirecting to ret2libc path` ([02e](images/02e-events-stream.png)). The `InterruptEvent` (or its ACP-side counterpart) needs an optional `note: str` field plus the actor (`operator`, `policy`, `timeout`). Tools-in-flight count at cancel time is already implied by item 2.

## Implementation phases

Phasing principle: **passive → active → robust → rich → ergonomic**. Each phase is a self-contained, meaningfully testable unit. Every phase lands the `inspect/*` protocol extensions it depends on (numbered references below point at the list in the previous section).

### Phase 1 — Transport + picker (attach plumbing)

End-to-end "I can find a running eval and open a connection to one of its samples", with the rendering surface deliberately stubbed. Locks in the App lifecycle, the discovery path, and the connection contract before any visual complexity.

**Ships**

- Lift the `Phase 15 not implemented` error in [`src/inspect_ai/_cli/acp.py`](../../src/inspect_ai/_cli/acp.py); launch a Textual `App` when invoked without `--stdio`.
- Skeleton `App` with two screens: `PickerScreen` and a minimal `SessionScreen` showing only the meta row + a "connected" indicator (no transcript widget yet).
- **Attach picker** — always the initial screen, driven by existing [`discovery.py`](../../src/inspect_ai/agent/_acp/discovery.py). Shows running sessions on this machine, or on a remote machine when `--server <addr>` is given. Empty-state bootstrap screen when no sessions are found and no `--server` was specified. Selecting a row opens `SessionScreen`.
- **CLI flags**: rename existing `--socket` to `--server` (accepts `host:port` or a UNIX domain socket path, shared with `--stdio` mode); `--eval-id` narrows the picker to a single eval's sessions (it does not bypass the picker).
- Session attach: complete the JSON-RPC handshake, hold the connection alive, surface disconnect as a simple error toast (no reconnect logic yet — that lands in Phase 5).
- Clean exit on `q` / `^C`.
- Textual `Pilot` snapshot-test scaffolding set up in `tests/agent/test_acp/test_tui/`.

**Protocol extensions landed**: #1 (running time per sample), #5 (agent name).

**Acceptance**

- Manual: with no local sessions and no `--server`, `inspect acp` shows the empty-state bootstrap screen. With one or more running sessions, the picker table appears. `--eval-id <id>` narrows the table to one eval. `--server <addr>` discovers sessions on a remote host. Selecting a row opens `SessionScreen` showing the meta row + "connected" indicator.
- Automated: pilot snapshots for picker (empty + populated + `--eval-id`-narrowed) and the bare `SessionScreen`.

### Phase 2 — Conversation rendering (read-only transcript)

The first visually meaningful payoff: watch the agent's conversation stream live. Read-only — composer still disabled, interrupt not wired.

**Ships**

- Expand `SessionScreen`: status row with pill + state-dependent chips (`N tools in flight`, `model <name>`, `tokens NNNk`), scrollable transcript, footer hints.
- Three event renderers: assistant message, user / dataset_input message, tool-call card (with `running` / `completed` / `failed` chip + duration; click-to-expand for long output).
- Subscribe to `session/update` notifications and dispatch to renderers.
- Composer present but disabled (placeholder).

**Protocol extensions landed**: #2 (tools-in-flight), #3 (token usage), #9 (tool-call timing).

**Acceptance**

- Manual: run `inspect eval … --acp-server` in one terminal, `inspect acp` in another → conversation stream renders end-to-end.
- Automated: snapshot tests for each of the three event-card types and for the status row with each chip combination.

### Phase 3 — Active participant (composer + interrupt)

Turns the viewer into a tool: the operator can chat with the agent and steer it mid-flight.

**Ships**

- Composer widget with focus-aware keymap (`↵` send, `Shift+↵` newline).
- `session/prompt` send path.
- `Esc` while agent is working → `session/cancel`; **operator-intervention banner** rendered on resume.
- Full status-pill state machine (`Awaiting input` / `Generating` / `Calling tools` / `Scoring` / transient `Interrupted` flash).

**Protocol extensions landed**: #4, #7.

**Acceptance**

- Manual: with a long-running tool in flight, send a redirect message → agent pivots; banner appears.
- Automated: pilot test for the interrupt-then-resume sequence; snapshot tests for `Generating`, `Calling tools`, `Interrupted` states.

### Phase 4 — Modals (approval, cancel-sample, help)

Unblocks human-in-the-loop tool use and gives the operator a way to terminate a sample without killing the eval process.

**Ships**

- `session/request_permission` modal with bare-letter shortcuts (`a` / `o` / `d`); auto-dismiss when another attached client answers first.
- New `inspect/cancel_sample` JSON-RPC method (server + TUI modal) with `disposition: "score" | "error"`.
- `?` help overlay (full keymap).

**Protocol extensions landed**: #10.

**Acceptance**

- Manual: tool requiring approval triggers modal; `a` / `o` / `d` all work. `^X` modal cancels-with-score and cancels-with-error both verified end-to-end.
- Automated: pilot tests for both modals. Multi-client test: another attached client answers approval first → TUI modal auto-dismisses.

### Phase 5 — Terminal states & connection resilience

Makes the TUI production-grade. Through Phase 4 it works on the happy path; Phase 5 covers what users actually see when things go wrong.

**Ships**

- Completed banner with score line; Errored banner with inline traceback.
- Disconnect detection in the client; exponential-backoff reconnect with attempt count + countdown overlay.
- **Server-side replay buffer** (settles [`agent-acp.md`](agent-acp.md)'s open question #1: pick buffer size + elision rules) plus client-side replay handling on reconnect.
- Footer next-action shortcuts in terminal states (`^S switch sample`, `^O open log`, `^C copy traceback`, etc.).

**Protocol extensions landed**: #11, #12, #13.

**Acceptance**

- Manual: complete-normally path → green banner. Force-error path → red banner with traceback frames. Kill + restart the server during a stream → client reconnects and missed events replay.
- Automated: pilot tests for both terminal banners; integration test for the disconnect / replay path using an in-process server fixture.

### Phase 6 — Rich event rendering

Fidelity work: covers every event type from `events.png` plus reasoning variants. Doesn't unlock new capability, but it's what makes the transcript actually readable for non-trivial agents.

**Ships**

- Reasoning blocks: visible-summary / encrypted-with-summary / encrypted-no-summary / redacted.
- Plan-update ephemeral cards (struck-through completed items, `done/total` + timestamp).
- Info events (with structured-JSON payload rendering).
- Compaction banner (`messages X → Y · tokens X → Y`).
- Mid-stream score chips.
- Turn-interrupt with reason + actor.

**Protocol extensions landed**: #6, #8, #14, #15, #16, #17.

**Acceptance**

- Manual: a synthetic eval emits every variant; each renders per the mockups.
- Automated: snapshot test per variant.

### Phase 7 — Multi-sample navigation

Ergonomics. Single-sample is sufficient for MVP; this phase exists so a multi-sample eval is pleasant to drive.

**Ships**

- `^S` re-opens the picker in place (without exiting the App).
- Drain the current session cleanly and attach to the selected one without process restart.
- Picker shows live status + running time across concurrent samples (validates extension #1 in the multi-sample case).

**Protocol extensions landed**: (none new — relies on #1 already landed in Phase 1).

**Acceptance**

- Manual: multi-sample eval; navigate between two samples; transcripts switch cleanly; original session's notifications drained.
- Automated: pilot test for the swap sequence.

### Cross-cutting

- **Standalone code** — per the Constraints section above, the TUI is its own self-contained Textual app. Phase 1 widgets (picker, app shell, `SessionScreen`) are built fresh rather than extended from `src/inspect_ai/_display/textual/`; later phases follow the same rule.
- **Test scaffolding** — Phase 1 sets up Textual `Pilot` infra under `tests/agent/test_acp/test_tui/`; every later phase adds snapshots for its new widgets.
- **Synthetic test eval** — a single growing "kitchen-sink" eval fixture that exercises every codepath used by the phases shipped so far. Lives alongside other ACP test fixtures.
- **Test selection during iteration** — TUI work iterates on visual + interaction details, so it's tempting to run the full ACP suite (`tests/agent/test_acp/`) on every change. Don't: ~400 tests at ~3–4s is dead time during quick visual loops. Instead:
    - **Fast loop**: `pytest tests/agent/test_acp/test_tui/` — runs only the pure-function unit tests (`_format_running`, `_format_tokens`, `_row_matches`, …) in well under a second. These cover the formatters and pure logic that change most often during UI iteration.
    - **Pre-commit / structural changes**: `pytest tests/agent/test_acp/test_tui/ --runslow` — adds the Pilot tests (every `app.run_test()`-based test is marked `@pytest.mark.slow`, either per-test or via module-level `pytestmark`). Run this before committing UI changes and whenever you've touched bindings, focus handling, or screen composition.
    - **Touching `picker.py` / `server.py` / `client.py`**: also run `pytest tests/agent/test_acp/test_picker.py tests/agent/test_acp/test_server_dispatch.py` (sub-second) — these pin the picker payload shape and `inspect/list_sessions` response that the TUI client consumes.
    - **Full ACP regression**: `pytest tests/agent/test_acp/ tests/_cli/test_acp_cli.py --runslow` — only when changing protocol shapes, server dispatch, or anything that crosses the wire.
    The pilot tests catch real screen-level regressions (binding shadowing, focus order, column-key bugs) that pure unit tests miss; keep marking new pilot tests `slow` so the fast loop stays fast.
- **[`agent-acp.md`](agent-acp.md) Phase 15 collapse** — once Phase 1 ships, replace [`agent-acp.md`](agent-acp.md)'s `Phase 15` body with a pointer to this doc.
- **Phase 16 (token-level streaming)** in [`agent-acp.md`](agent-acp.md) remains independent and can land any time after Phase 1.
