# Tool Call Cancel (`inspect ctl sample cancel-tool-call`)

> **Status: implemented.** Companion to [`control-channel.md`](control-channel.md), which owns the control-channel architecture and conventions this directive rides (mutation contract, selector rules, version-skew policy); this doc owns the tool-call-cancel semantics. Originating issue: meridianlabs-ai/inspect_ai#313.

Occasionally a tool call hangs and its timeout never fires. The sample then sits "running" indefinitely: the model is mid-turn awaiting a tool result that will never arrive, and every coarser remedy destroys work — `ctl sample cancel` ends the whole sample, `ctl task cancel` the whole task. The surgical fix already exists twice over: ACP's `inspect/cancel_tool_call` extension cancels exactly one in-flight tool call by id, and the in-process TUI's "timeout tool call" button cancels the pending call(s); either way the model gets a timeout-shaped tool result and the sample continues. But ACP requires the eval to have been launched with `--acp-server` and an ACP client bound to the sample's session, and the TUI requires an interactive `--display full` terminal. The control channel is default-on, discoverable after the fact, and scriptable — an operator (or watchdog agent) who notices a stuck sample in `ctl sample list` should be able to unstick it from the same surface. **`ctl sample cancel-tool-call`** closes that gap.

## Scenarios

- **Hung tool call, live run.** A sandbox `exec` RPC wedges (dead daemon, network partition to a remote sandbox) on a tool invoked with no timeout — `bash()` / `python()` default `timeout=None`, and `_call_tools.py` imposes no framework-level bound. The operator sees the sample stalled on a tool in `sample list` (activity `type: tool`, hours old), cancels the call, and the sample resumes with the model seeing an ordinary tool timeout.
- **Timeout configured but never fired.** The tool's own timeout machinery can be defeated: post-timeout teardown runs in shielded scopes (subprocess SIGTERM/SIGKILL grace, the shielded remote `kill()` RPC — which can itself hang against a dead sandbox), and docker-compose retries a timed-out command, multiplying wall time. The operator cancel is a second, outer lever on the same per-call cancel scope.
- **Watchdog remediation.** A script polls `ctl sample list --json`, spots samples whose current tool activity exceeds a threshold, and cancels those calls by id — keeping a long unattended run converging without killing samples. (This is the same watchdog shape `sample requeue --errored` serves for terminal failures; this directive serves the pre-terminal stall.)
- **Agent operators.** The control channel's primary programmatic consumer is an LLM agent babysitting a run via the CLI. "The sample is stuck on a tool call" is among the most common diagnoses such an agent reaches from `sample events` / `sample list`; today its only in-band remedies are destructive.

## What exists today (the primitive is already built)

The per-tool-call cancel is display/transport agnostic and lives in the core:

- Each tool call runs in its **own nested task group**, and the dispatcher installs `event._set_cancel_fn(tg.cancel_scope.cancel)` on the call's `ToolEvent` (`model/_call_tools.py`, `run_one`) — deliberately per-call so cancelling one doesn't disturb parallel siblings.
- `ToolEvent._cancel()` (`event/_tool.py`) fires that scope; it is idempotent (no-op when already cancelled or no fn installed) and `event.cancelled` reports post-state.
- On cancellation `run_one` synthesizes the model-visible result: a `ChatMessageTool` with `ToolCallError("timeout", "Command timed out before completing.")`, `failed=None` — the *same shape as a genuine tool timeout*, a deliberate reuse so the model's conversation stays well-formed and the agent loop continues normally. The transcript gets the finalized `ToolEvent` plus an `InfoEvent` ("Tool call '<fn>' was cancelled by operator.").
- **ACP** (`agent/_acp/connection.py`, `cancel_tool_call`): resolves the sample, scans `sample.transcript.pending_events` for a pending `ToolEvent` with matching id, calls `event._cancel()`, returns `{"cancelled": event.cancelled}`. Pending events are never evicted from a bounded transcript, and nested sub-agent tool calls (`task` dispatch / `as_tool` / `handoff`) record into the same sample transcript, so they are reachable; the per-call scope cancel propagates up through the enclosing sub-agent run (pinned by an ACP integration test).
- **TUI** (`_display/textual/widgets/samples.py`): the "timeout tool call" button fans `_cancel()` out over *every* pending `ToolEvent` — no per-id targeting.

So the directive is a thin new front door on `find_active_sample` + the ACP resolver's scan — no eval-runner changes.

## Surface

- **`POST /evals/<id>/sample/cancel-tool-call?sample_id=<sid>&epoch=<n>[&tool_call_id=<tcid>][&dry_run=true]`** — attempt-scoped like `sample/cancel` and `sample/requeue`. Sample addressing by **query param** (ids may contain URL-reserved characters); `epoch` **fails closed** (required, omitting it is a 400 — a defaulted epoch resolves to a different sample and must never be mutated silently); all params individual scalars so the strict-mutations dependency derives the allowed set. `tool_call_id` is the `ToolCall.id` from the model's assistant message (== `ToolEvent.id`), optional per the sole-pending rule below.
- **CLI: `inspect ctl sample cancel-tool-call TASK SID [EPOCH] [--tool-call-id ID] [--dry-run] [--json] [--terse]`.** Hyphenated verb under the `sample` noun (precedent: `task log-flush`), named after the ACP method it mirrors. `TASK` and `SID` required (mutation verbs get no sole-target default at the sample level); `EPOCH` required whenever the task runs more than one epoch (the standard mutation selector rule, same client-side gate as `sample cancel`). Wired through the shared `_run_sample_mutation` scaffold in `_cli/ctl/_sample.py`, so target resolution, the epoch gate, the uniform `--json` mutation envelope (`{target, applied, dry_run, detail}`), and `--terse` come for free. The tool-call id rides an option rather than a positional because `EPOCH` is an optional positional — a bare `TASK SID <id-ish>` must never silently bind a call id to the epoch slot.
- **No `CONTROL_API_VERSION` bump.** New route: an older server answers with the stock router 404, distinguishable from a handler's `{"error": ...}` 404, so the CLI passes a `_CANCEL_TOOL_CALL_ROUTE_MISSING` message via `not_found_missing_route` and reports "older inspect — restart the eval" definitively.
- **Security.** First-class mutation: rides the phase-3 hardening (SO_PEERCRED UID check) like every other directive.

## Targeting: `tool_call_id` optional, sole-pending fallback

The headline scenario is a sample stuck on **one** hung tool call, and digging the call id out of `sample messages --json` is real friction (the compact events projection doesn't currently expose it at all — see "Read-surface enablement"). So `tool_call_id` is optional with a fail-closed fallback, mirroring the sole-task fallback in `_resolve_scope`:

- **Exactly one pending tool call** → it is the target. The response echoes what was cancelled (`tool_call_id`, `function`, `started_at`, running time) so a wrong target — the hung call completing and a fresh call starting in the read-to-mutate window — is immediately visible rather than silent; the fallback re-resolves *at mutation time* on the eval's single loop, so within the request there is no race. ("Pending" counts only transcript-visible calls — a sibling parked awaiting approval is invisible to the scan, so the count can read one while two are in flight; see "Tool awaiting approval" under failure modes.)
- **Two or more pending** → **409 error** enumerating them (`{id, function, started_at}` each). A mutation must not guess among targets, and per the control channel's no-fan-out-mutations convention it must not cancel them all (the TUI's fan-out shape is explicitly not carried over; shell composition over explicit ids covers a sweep if ever needed, and an `--all` variant can follow demand).
- **Zero pending** → no-op, `changed: false`, with the sample's current activity in `detail` (e.g. a pending model generation or retry wait) — the operator learns in one round trip that the sample is stuck *elsewhere*, and which lever (`ctl config --timeout` / `--max-retries`) applies instead.

Watchdogs and repeat invocations should pass the explicit id; `--dry-run` without an id doubles as "show me the pending tool calls" (it reports the would-be target, or the ambiguity list, without mutating — all reject rows report under dry-run too, so an agent can probe safely).

## Decision table

Resolver contract per the control-server convention (`None` → 404, `{"ok": False}` → 409, else 200 with `changed`):

| Situation | Result | Why |
|---|---|---|
| Pending `ToolEvent` matches (explicit id, or sole-pending fallback), not yet cancelled | **applied** (`changed: true`; detail echoes id, function, started_at, running time) | The headline case. `event._cancel()` fires the per-call scope. |
| Same target, `cancelled` already true (repeat) | **no-op** (`changed: false`, reason "cancel already requested") | Idempotent — the cancel previously landed; the call is unwinding (or wedged past cancellation — see the escalation ladder). Checked *before* calling `_cancel()`, so the response distinguishes "this request cancelled it" from "already cancelled", which ACP's post-state-only return cannot. |
| Explicit id, no pending match, sample active | **no-op** (`changed: false`, reason "no pending tool call with that id"; detail lists currently pending calls) | The desired end state — this call is not running — already holds (completed, or never existed; the pending scan cannot cheaply distinguish, and materializing evicted history on a bounded transcript to try is not worth it). The pending list in `detail` makes a typo'd id visible and actionable rather than silently absorbed. |
| No id, ≥ 2 pending | **409 error** (enumerating pending calls) | Must not guess; must not fan out. |
| No id, 0 pending | **no-op** (`changed: false`, reason "no pending tool calls"; detail carries current activity) | End state holds trivially; the activity detail redirects the operator to the real stall. A still-queued sample falls out here too (it can have no pending tools). |
| Pending match but no `_cancel_fn` installed | **409 error** ("this tool call cannot be cancelled") | The desired end state will *not* come to pass — `_cancel()` would no-op. Defensive: production paths install `_cancel_fn` before the event reaches the transcript; the honest error beats a success-shaped no-op (the requeue design's honesty rule). |
| Sample terminal | **no-op** (`changed: false`, `status`, reason "sample already finished") | Mirrors `cancel_sample`'s terminal no-op (via `sample_error_detail`). |
| Unknown `(sample_id, epoch)` / unknown eval | **404** (`{"error": ...}`) | Handler 404, per convention. |

Everything runs on the eval's single loop and the resolver has no await between the pending scan and `_cancel()`, so there is no scan-to-fire race (the same argument as `cancel_sample`'s check-then-interrupt).

## What the model and the log see

Identical to the existing consumers, deliberately — one primitive, one semantics, whichever surface fires it:

- The model's conversation gets a `ChatMessageTool` with `ToolCallError("timeout", "Command timed out before completing.")` spliced in declared order; the next `generate()` proceeds normally. The `"timeout"` type (not `"cancelled"`, which marks sibling-exception and turn-level cancellations) is the established operator-cancel contract: from the model's perspective a hung-then-cancelled tool *is* a timeout, and preserving that shape keeps the eval's behavioral distribution closest to what a working timeout would have produced.
- The transcript's `ToolEvent` finalizes (`pending` cleared, the timeout error recorded, `failed=None` per the operator-cancel convention, `working_time` computed) and an `InfoEvent` records "Tool call '<fn>' was cancelled by operator." — so post-hoc log readers can distinguish an operator cancel from an organic timeout. Structured provenance (who/why, as `ctl config` records author/reason) is deliberately not added here: it belongs to the cross-cutting resolution-provenance question tracked in `stalled-samples.md`, and adding it for one surface would fork the event shape from the ACP/TUI paths.
- Nested tool calls (inside `task` dispatch / `as_tool` / `handoff` sub-agents) are cancellable exactly as via ACP — the pending scan reaches them, and the scope cancel propagates through the enclosing sub-agent run per the pinned propagation contract.

## Best-effort delivery and the escalation ladder

`changed: true` means the cancel was **delivered to the call's cancel scope**, not that the tool has stopped: anyio cancellation is cooperative, so the call unwinds at its next await checkpoint. The common hang — parked forever on an await that never resolves (dead sandbox RPC, quiet socket) — *is* at a checkpoint, so cancellation lands immediately. The residue of truly wedged calls is not cancellable by any scope: sync code running in a thread (`to_thread.run_sync` in tool bodies), or teardown already inside a shielded scope (subprocess kill-and-drain, the shielded remote `kill()` RPC). For those the event stays `pending` with `cancelled: true`, and the sample stays stuck.

That state must be *visible*, not mysterious: the read surface (below) reports `cancel_requested: true` on the pending call, so a repeat invocation's "cancel already requested" no-op plus the listing tells the operator the lever has been pulled and the call is unkillable from here. The escalation ladder is then explicit and already exists: `ctl sample cancel --action score|cancel` (the sample-level scope — same cooperative limits, but a wider net of checkpoints), then process-level remediation (`kill` + `inspect eval-retry` / eval-set re-invocation). The directive's job is to make the *first* rung available; it does not attempt sandbox-level force-kill (a tool-aware "terminate the underlying exec" is a different, tool-specific capability — out of scope, and the shielded-teardown pathologies it would need to solve are exactly the ones that defeat timeouts today).

A late natural completion racing the cancel is already handled below the directive: `run_one`'s synthesis only triggers when the call produced no result, so whichever of the two lands first wins cleanly. (`ToolEvent._set_result`'s sticky cancel markers are the *turn-level* cancel's analogue of this guard — they key on the `"cancelled"`+`failed` fingerprint that path stamps, which the per-call `_cancel()` never sets.)

## Read-surface enablement: discovering the tool call id

Today ctl can show *that* a sample is stuck on a tool and *which function* — but the cancellable id is only reachable via `sample messages --json` (assistant `tool_calls[].id`) or `sample events --full`. Three small read additions make the directive usable end-to-end from `ctl` alone:

1. **Compact events projection** (`_control/events.py`): the `tool` event projection gains `id` alongside `function`. (Trust-boundary note: tool-call ids are model/provider-generated tokens, and the messages projection already exposes them — precedent stands.)
2. **Activity payload** (`_control/state.py`, `_sample_activity`): the `tool`-type activity gains a per-call list `{id, function, started_at, cancel_requested}`, so `ctl sample list --json` alone powers the watchdog loop (spot stall → cancel by id) and surfaces a delivered-but-unheeded cancel.
3. **`--dry-run` without an id** enumerates pending calls (above) — the human path needs no `--json` round trip at all.

## Failure modes and edges worth naming

- **Tool awaiting approval.** A call parked in `apply_tool_approval` has `_cancel_fn` installed but its `ToolEvent` is not yet in the transcript (it is recorded only after approval), so the pending scan cannot see it — the same blind spot ACP has. The directive reports "no pending tool call"; the operator's actual lever there is the approval itself (or sample cancel). This blind spot also interacts with the sole-pending fallback: with parallel tool calls where one is executing and a sibling is parked pre-approval, the scan counts exactly one pending call while two are in flight, so a no-id request fires on the visible call instead of returning the ≥2-pending 409 — the response echo exposes the target after the fact, and approval-mode runs should pass explicit ids. Acceptable for v1 and shared with the existing consumers; if it bites, surfacing pre-approval calls is a shared fix for all three surfaces, not a ctl special case.
- **Cancel delivered during the sample's own teardown.** The sample-level interrupt and the per-call cancel compose without conflict — the per-call scope is nested inside the sample's task group, and `_cancel()` on an already-cancelled or finalized event no-ops.
- **Repeat storms** (a retrying agent): bounded by idempotence — every repeat lands in the "already requested" / "no pending match" no-op rows.
- **Race with the call completing.** Explicit-id: the id no longer matches pending → honest no-op. Sole-pending fallback: resolved at mutation time; the echo exposes the (unlikely) wrong-target case, and operators who cannot tolerate it pass the id.
- **Crash honesty.** Like every control-channel intent, nothing is persisted: a cancel delivered but not yet unwound at process death leaves the log showing whatever was last recorded (a pending tool event on a running sample record, per the usual crash shape). Recovery layers own durability.

## Alternatives considered

- **Status quo: use ACP.** Requires `--acp-server` at launch (default off), an ACP client, and per-sample session binding — unavailable exactly when the operator discovers a stuck sample mid-run on a default launch, and awkward for scripts/agents (JSON-RPC over a socket vs. the CLI's `--json`). Two surfaces for one operation is the control channel's founding gap.
- **`ctl sample cancel` + `sample requeue`.** Works today but discards all sample progress and re-runs from the start (checkpoint-less solvers) — disproportionate when one tool result is the only thing missing.
- **Fan out over all pending calls (TUI parity).** Rejected per the no-fan-out-mutations convention; the sole-pending fallback covers the common case and explicit ids compose in shell for the rest.
- **Fix the underlying timeouts instead.** Complementary, not sufficient: the hang causes are open-ended (no default timeout on `bash()`/`python()` and custom tools, shielded teardown that can itself hang, sync bodies in threads, retry multiplication in compose). However hard the timeout paths are tightened, an operator lever of last resort is still needed — that is precisely why the TUI button and ACP method exist.
- **A generic "unstick sample" verb** (also covering hung generates). Model-call stalls already have live levers (`ctl config --timeout / --attempt-timeout / --max-retries` reach in-flight retry loops); conflating the two would blur what was actually done to the eval. Separate diagnoses, separate verbs.

## Open questions

1. **Naming.** `cancel-tool-call` (mirroring `inspect/cancel_tool_call`) vs. something shorter (`cancel-tool`); `--tool-call-id` vs. `--call-id`. Settled at implementation: `cancel-tool-call` / `--tool-call-id` — the ACP-mirroring spellings.
2. **Should the synthesized error stay `"timeout"`?** Uniformity with the ACP/TUI paths and behavioral fidelity say yes (above); if structured operator-resolution provenance lands (`stalled-samples.md`), all three surfaces adopt it together.
3. **`--all` sweep.** Deferred until demand appears (the requeue `--errored` precedent: ship single-target, add the CLI-side sweep when a real babysit run proves the need).

## Implementation sketch (blast radius)

- `_control/cancel.py`: `cancel_tool_call(eval_id, sample_id, epoch, tool_call_id=None, dry_run=False)` resolver shaped like `cancel_sample` — `find_active_sample`, pending scan (the ACP resolver's loop, lifted), the decision table above.
- `_control/server.py`: `POST /evals/{eval_id}/sample/cancel-tool-call` route; `epoch` fails closed like `sample/cancel`.
- `_cli/ctl/_sample.py`: `sample cancel-tool-call` command through `_run_sample_mutation`; route-missing message alongside `_REQUEUE_ROUTE_MISSING` in the same module.
- `_control/state.py` / `_control/events.py`: the read-surface additions (activity per-call list; `id` in the compact tool projection).
- `agent/_acp/connection.py`: optionally refactor `cancel_tool_call`'s scan to share the new resolver's core (both are pending-scan + `_cancel()`; keep the return contracts distinct).
- Tests: `tests/_control/test_cancel.py` additions (decision table rows, sole-pending fallback, ambiguity 409, idempotent repeat, dry-run enumeration) — resolver rows against fake active samples as that file already does, plus a live-eval case (a genuinely pending tool call needs a running sample; the `control_probe` harness used by the eval-set integration tests is the fit). The ACP behavioral tests (`tests/agent/test_acp/test_action_methods.py`) pin the shared primitive's contract and stay untouched.
- Docs: `docs/control-channel.qmd`; CHANGELOG entry when the implementation lands.
