# Control Channel

A full-featured control plane for live evals and eval-sets. External processes — TUIs, monitoring agents, and CLI commands — connect to a running Inspect process to **observe** its state and **direct** it (cancel, modify config, drain, requeue, ...).

This is **separate from** the [`agent-acp`](acp/agent-acp.md) work, even though some plumbing overlaps. ACP is for per-sample agent conversation (sessions, prompts, cancels, updates). The control channel is for eval and eval-set management — a different shape that doesn't fit ACP's conversational vocabulary. The two coexist: the ACP server handles `session/prompt` and the existing per-sample `inspect/*` extensions (`inspect/cancel_sample`, `inspect/cancel_tool_call`, etc.); the control channel handles eval-level operations.

The rudimentary control surface that fell out of the ACP work (per-sample cancellation, socket discovery via `--acp-server`) is a useful precedent but not the foundation — the control channel deserves its own protocol choice.

## Goals

- Make eval and eval-set state **introspectable** from outside the running process without parsing logs.
- Make a running eval **directable** mid-flight: cancel, retry, requeue, throttle, adjust limits — operations that today require either killing the process or waiting for it to finish.
- Decouple the **Inspect TUI** from the eval process so the TUI can be opened, closed, and reattached without affecting the eval, and so a single TUI can observe multiple evals.
- Let **autonomous agents** monitor and react to running evals (eg. a watchdog that cancels samples violating a custom policy, or a dashboarding agent that surfaces metrics).
- Keep a **single coherent surface** — one socket per running Inspect process, one set of method names, one auth story — that all three consumer classes (TUI, agents, CLI) share.

## Scenarios

### 1. TUI in a separate process from the eval

Today `inspect eval --display full` runs a Textual TUI in the eval process itself. Closing the TUI requires killing the eval; running headless (`--display plain`) means giving up live state entirely.

The control channel makes the TUI a **client of the eval process**:

```
inspect eval --display none ...      # eval runs headless
inspect tui                          # separate terminal — attaches to the eval
```

The TUI observes eval / eval-set state, sample queue, in-flight samples, model usage, scoring progress; and can direct: cancel samples, cancel the eval, requeue failed samples, modify per-sample limits. Detaching the TUI doesn't disturb the eval.

**Combining multiple backends in one TUI** is a sub-scenario of this same capability — once the TUI is decoupled from the eval process, attaching to N evals (or an eval-set's worth) is the same thing extended: one TUI process holds N control-channel connections, with a top-level switcher across them. Single-eval and multi-eval differ only in how many connections the client holds; the underlying capability is identical. The existing in-process TUI can't do this because it lives inside one process — the moment the TUI becomes a client, multi-backend falls out.

### 2. Agent monitoring a running eval

Two distinct kinds of agent:

**Programmatic / scripted agents** — Python or shell scripts wired up by the user. Concrete shapes:

- **Watchdog** — cancel any sample that exceeds a custom token-cost budget, or that runs longer than expected for its task class.
- **Alerter** — Slack / PagerDuty on first error, or when error rate crosses a threshold.
- **Adaptive throttler** — back off model concurrency when API errors spike.
- **Dashboarder** — push live metrics (samples completed, tokens used, mean latency, scoring distribution so far) to an external dashboard.

**LLM-driven agents** — Claude Code, an Inspect-internal meta-agent, an editor's built-in agent. The user asks "are any evals stuck? cancel anything stalled for more than 10 minutes" and the agent figures it out.

Both kinds need a subscription surface (eval-level events) and a directable surface (the same `cancel` / `modify` methods the TUI uses). The primary integration path for both is the CLI with `--json` output — modern agents are excellent at shell use and JSON parsing, and the CLI is a surface humans want anyway. See "Programmatic / agent consumers" below for the four exposure paths and why CLI-first beats wrapping layers.

### 3. CLI commands to cancel or modify a running eval

Single-purpose CLI commands that wrap one control-channel call each:

```
inspect ls                              # list running evals
inspect cancel [<eval-id>]              # cancel an eval (current sample drains; scoring runs)
inspect cancel --force                  # cancel without draining
inspect cancel-sample <sample-id>       # delegate to the existing inspect/cancel_sample
inspect set-limit <eval-id> --time 600  # modify a running eval's per-sample time limit
inspect drain <eval-id>                 # stop accepting new samples; let in-flight finish
inspect requeue <eval-id> <sample-id>   # re-add a failed sample to the queue
```

Each is a thin wrapper — autocomplete-friendly, scriptable, composable with shell tooling. Same operations as the TUI, just one shot at a time.

## What exists today

Concentrated in `src/inspect_ai/agent/_acp/` and detailed in [`agent-acp.md`](acp/agent-acp.md):

| Piece | What it does |
|---|---|
| `--acp-server` flag on `inspect eval` | Opens a per-eval AF_UNIX socket (or TCP) and writes a discovery file under `<inspect_data_dir>/acp/<pid>.json` |
| `discovery.py` | `list_discovered_evals()` / `resolve_target()` — find a running eval by id, by socket, or via auto-discovery |
| `inspect/list_sessions` | Enumerate ACP-attachable samples (one per in-flight `react()` / `deepagent()`) |
| `inspect/cancel_sample` | Terminate one sample (score / error) |
| `inspect/cancel_tool_call` | Cancel one in-flight tool call |
| `inspect/event` (opt-in) | Raw transcript event firehose, per sample |
| `session/prompt`, `session/cancel`, `session/request_permission` | Per-sample ACP interaction — message the agent, interrupt it, answer approval requests |

**What's missing.** All of the above are *per-sample*; there's nothing at the eval or eval-set layer. Operations like "cancel the eval", "list eval-set state", "modify the eval's per-sample limit" don't exist. Discovery is per-eval — to attach to an eval-set you'd have to pick one of its child evals. The TUI runs in-process. CLI surface is limited to `inspect acp [--stdio]` (the editor bridge) — no `inspect cancel` etc.

**What's reusable.** Even though ACP isn't the right shape for the control channel, the *plumbing* developed for it is:

- The discovery file pattern (`<inspect_data_dir>/acp/<pid>.json` + PID-liveness cleanup) generalises to any per-process endpoint.
- The AF_UNIX-default-with-TCP-fallback transport story.
- The per-eval lifecycle hook the ACP server uses (open at eval start, close at eval end) can be shared by a control-channel server.

The protocol on the wire is the open question; the bind / discover / lifecycle scaffolding is reusable regardless.

## Operations

The conceptual surface, independent of wire protocol. Each operation becomes either a JSON-RPC method or an HTTP endpoint depending on the protocol choice below; the shape of *what* the operation does is the same either way.

**Read (eval-level)**
- List running evals (id, task, status, started_at, sample counts).
- Eval status detail (config, current limits, sample queue depth, in-flight samples, completed counts, model usage so far).
- List samples within an eval (status, started_at, current model/tool, token usage).

**Read (eval-set-level)**
- List eval-sets.
- Eval-set status (child evals: completed / running / pending; aggregate progress).

**Direct (eval-level)**
- Cancel eval (graceful: current samples drain, scoring runs; or force: immediate teardown).
- Drain (stop accepting new samples; in-flight ones finish naturally).
- Requeue sample (re-add a failed / cancelled sample to the queue).
- Modify limits (per-sample time / token / message limits, applied to samples not yet started).
- Modify concurrency (max-samples, max-tasks).

**Direct (eval-set-level)**
- Cancel eval-set.

**Subscribe (events)**
- Eval-level lifecycle events: sample queued, sample started, sample finished, sample errored, eval starting, eval finished.
- Eval-set-level lifecycle events: child eval starting / finished, eval-set finished.

### Shape constraints from agent consumers

Four constraints fall out of supporting LLM-driven agents (see "Programmatic / agent consumers" below) that don't apply to TUIs / human CLI:

1. **Every read operation needs a structured (JSON) output form.** Agents parse JSON reliably; agents parse human-formatted tables poorly. CLI commands ship `--json` as a first-class output mode, not an afterthought. The JSON schema is the canonical shape — human-formatted output is a rendering of it. Same shape serves shell-pipeline users (`inspect ls --json | jq ...`) and LLM agents.
2. **Read operations should return summaries by default, with drill-down for detail.** Returning a 200-sample status dump as JSON eats LLM context. The `list samples` shape should default to a summary (status histogram + the N most-recent / longest-running) with a separate `get_sample(id)` for the full picture. Humans paginate / `jq`; agents need the shape to be agent-shaped at the source.
3. **Events need both push and pull access.** TUIs want push (SSE notification, immediate render). LLM agents want pull (cursored read: "events for eval X since cursor Y") — their runtimes are request/response loops, not subscription loops. The control channel should expose both shapes regardless of which the underlying transport favours; the push shape is the natural one for the wire protocol, the pull shape is a thin server-side buffer + cursor on top.
4. **Directives should be idempotent and support dry-run.** Agents retry, get confused, and operate on stale state. `requeue_sample` called twice must not double-queue. `cancel_eval` on an already-cancelled eval must return cleanly. Destructive directives should accept a `dry_run` flag that returns "would do X" without doing it, so agents can reason before acting.

## Wire protocol options

Two viable wire protocols. Picking one shapes the CLI, the SDK story for clients, the subscription mechanism, and how cleanly we integrate with future tooling (web dashboards, generated SDKs, ad-hoc shell scripts).

### Option A: JSON-RPC 2.0 over AF_UNIX / loopback TCP

Same protocol family as the existing ACP socket. Each operation becomes a method (`inspect/eval_status`, `inspect/cancel_eval`, ...). Notifications carry events (`inspect/eval_event`, `inspect/eval_set_event`); clients opt in at connection setup.

**Pros**
- **Plumbing already exists.** The discovery files, AF_UNIX bind, connection handling, and `MessageRouter` from the ACP work are reusable with no protocol change. We can ship a meaningful slice in a small diff.
- **Bidirectional notifications are native.** Subscribing to eval events is a normal JSON-RPC notification — no extra framing.
- **One coherent IPC story.** The Inspect process speaks one wire dialect across all its surfaces.
- **Same security model as ACP.** Loopback-only is straightforward; no port-exposure surprises.

**Cons**
- **Bad CLI ergonomics.** Writing `inspect cancel <id>` requires a JSON-RPC client; no `curl` story. Every CLI command becomes an internal-RPC-call wrapper.
- **No off-the-shelf tooling.** No browsers, no Postman-style debuggers, no generated SDKs across languages. JSON-RPC has libraries but the ecosystem is narrow compared to HTTP.
- **Coupling temptation.** Sharing the ACP server's process / socket makes it easy to drift back into "the control channel is an ACP extension" — exactly the framing we just rejected. Even if logically separate, code locality invites entanglement.
- **Hard to evolve toward a web UI.** A future Inspect web dashboard would need a JSON-RPC↔HTTP gateway.

### Option B: HTTP / REST + SSE (or WebSocket) for events

A small HTTP server on loopback (`127.0.0.1:<port>`) or AF_UNIX (HTTP over UDS is well-supported by `httpx`, `curl --unix-socket`, etc). Read operations are `GET`; directives are `POST` / `PATCH` / `DELETE`. Event subscriptions use Server-Sent Events (`GET /evals/<id>/events` with `Accept: text/event-stream`) or WebSocket for bi-directional cases.

| Operation | Endpoint |
|---|---|
| List evals | `GET /evals` |
| Eval status | `GET /evals/<id>` |
| List samples | `GET /evals/<id>/samples` |
| Cancel eval | `POST /evals/<id>/cancel` |
| Drain | `POST /evals/<id>/drain` |
| Requeue sample | `POST /evals/<id>/samples/<sid>/requeue` |
| Modify limits | `PATCH /evals/<id>` |
| Eval event stream | `GET /evals/<id>/events` (SSE) |
| List eval-sets | `GET /eval-sets` |
| Cancel eval-set | `POST /eval-sets/<id>/cancel` |

**Pros**
- **Excellent CLI ergonomics.** `inspect cancel <id>` is one `httpx` call; `inspect status <id>` is the same. Shell users can hit endpoints directly with `curl`. Easy to write small monitoring scripts in any language.
- **Universal tooling.** Browsers, Postman, generated OpenAPI clients, HTTP-level proxies / logging / debugging — all off the shelf.
- **Natural fit for the operation shape.** "Cancel an eval" is request/response with optional payload — the canonical HTTP pattern. Resource-oriented URLs (`/evals/<id>/samples/<sid>`) describe what they target.
- **Future web UI is free.** Browser-based dashboards consume HTTP and SSE directly; no gateway.
- **Clear separation from ACP.** Different protocol, different endpoint, different `_data_dir` subfolder — the boundary is structural, not just naming.

**Cons**
- **Two protocols in the project.** ACP stays JSON-RPC; control plane is HTTP. Reviewers and maintainers have to context-switch.
- **Bigger initial footprint.** Need an HTTP server (likely `starlette` / `uvicorn` or `aiohttp`), URL routing, SSE plumbing. The ACP socket got `acp.Connection` for free; HTTP needs a deliberate framework choice.
- **Subscriptions are less symmetric.** SSE is one-way (server → client); a directive *during* a subscription requires a second HTTP call. JSON-RPC's bidirectional notifications make "subscribe then nudge" cleaner.
- **Port-vs-socket policy.** Loopback TCP needs port allocation (and a port collision story); AF_UNIX HTTP needs every client to support it (`httpx` does; `curl` does with `--unix-socket`; some libraries don't). One more decision than the ACP socket required.
- **Auth at the door becomes more salient.** HTTP servers on loopback are still loopback-only, but the convention of "an HTTP endpoint" invites mistakes (binding 0.0.0.0, exposing through Docker port-mapping). The discipline that keeps the ACP socket safe needs explicit codification here.

### Comparison at a glance

| Dimension | JSON-RPC 2.0 | HTTP / REST + SSE |
|---|---|---|
| Reuse of existing ACP plumbing | High (same `Connection`, router, discovery) | Discovery reusable; transport / server new |
| CLI / `curl` ergonomics | Poor | Excellent |
| Subscription shape | Bidirectional notifications native | SSE one-way; WebSocket if bidirectional needed |
| Cross-language clients | Narrow ecosystem | Universal |
| Browser / web UI integration | Requires gateway | Direct |
| New dependencies | None | An HTTP server framework |
| Coupling risk with ACP | High (same socket / module) | Low (separate endpoint) |
| Auth-mistake surface | Small | Larger (HTTP conventions invite binding wider) |
| Schema / contract tooling | Ad-hoc Pydantic | OpenAPI off the shelf |

### Endpoint layout (orthogonal to protocol choice)

Regardless of wire protocol, the control channel needs its own endpoint distinct from the ACP socket — they have different lifecycles (eval-set lifecycle vs per-eval lifecycle; see below) and different consumer classes:

- **JSON-RPC variant**: a separate AF_UNIX socket (eg. `<inspect_data_dir>/control/<pid>.sock`) for the control channel, alongside the existing ACP socket. Same process binds both. Discovery file pattern reused.
- **HTTP variant**: HTTP server bound to a loopback port (or an HTTP-over-UDS socket). Same discovery-file pattern — the file records `{transport: "http", host, port}` (or `{transport: "http+unix", socket_path}`) so clients can locate it.

Sharing the ACP socket is technically possible for the JSON-RPC variant but ill-advised (couples the two surfaces' lifecycles and re-invites the "control channel is ACP" framing).

### Architecture diagram (protocol-agnostic)

```
+------------------+      ACP socket (existing)         +-----------------+
| inspect process  |  <-----------------------------    | inspect acp     |
|                  |    per-sample agent interaction    | (editor bridge) |
|                  |                                    +-----------------+
|                  |
|                  |      control endpoint (new)        +-----------------+
|                  |  <-----------------------------    | inspect tui     |
|                  |    eval / eval-set management      +-----------------+
|                  |    + event subscription            | inspect cancel  |
|                  |                                    | (CLI commands)  |
|                  |                                    +-----------------+
|                  |                                    | watchdog agent  |
+------------------+                                    +-----------------+
```

### Discovery extended for eval-sets

Today's discovery file is per-eval (`<pid>.json` keyed by the eval's `run_id`). An eval-set is N sequential evals in one parent process; only one is alive at a time, so the existing per-pid file already points at the currently-running child eval.

What's missing for the eval-set scenarios:

- The discovery file needs an `eval_set_id` field so consumers can group child evals.
- The control channel needs to **persist across child-eval boundaries** within one eval-set — when a child eval finishes and the next one starts, the same socket should serve the new eval. (Today the per-eval `acp_server()` context manager re-binds on each child; we'd shift to a parent-process lifecycle for eval-sets.)

### Subscription model for monitoring agents

The new eval-scoped events need their own subscription mechanism, with the shape determined by the wire protocol choice:

- **JSON-RPC variant**: `inspect/eval_event` and `inspect/eval_set_event` notifications, same opt-in pattern as the existing `inspect/event` (client signals interest at connection setup, server starts forwarding).
- **HTTP variant**: SSE streams at `GET /evals/<id>/events` and `GET /eval-sets/<id>/events`.

Either way, the streams coexist with the per-sample ACP subscriptions — a TUI attached to one sample sees eval events (via the control channel) AND per-sample updates (via the ACP socket); a watchdog agent might subscribe only to eval events and never touch ACP.

### Programmatic / agent consumers

Three exposure paths an external agent (Claude Code, scripted watchdog, custom agent runtime) might use. **Path A is the primary integration story; Path C is a deliberate "only if needed" follow-on.**

**Path A: CLI subprocess with `--json` output (primary).** Any agent that can run shell commands uses `inspect ls --json`, `inspect status <id> --json`, `inspect cancel <id>`, `inspect events <id> --since <cursor> --json` directly. Works with Claude Code's Bash tool, with shell scripts, with any subprocess-capable runtime.

Modern LLMs are demonstrably excellent at:
- Reading `inspect --help` and discovering subcommands.
- Parsing JSON output and composing follow-up calls.
- Pipe composition (`inspect ls --json | jq '.[] | select(.status=="stuck")' | xargs -I{} inspect cancel {}`).

Concrete benefits over a wrapping layer:
- **Single source of truth** — no drift between CLI behaviour and a parallel tool surface.
- **User-debuggable** — the agent's "thinking" is reproducible by hand at the shell.
- **Zero per-host config** — no MCP server to install, configure, or version.
- **Universal** — any agent runtime that can spawn a subprocess can integrate.

This is the integration story we'd build to first and probably the only one needed. The bar is "a great CLI with `--json` everywhere" — that's it.

**Path B: HTTP endpoint hit directly (HTTP variant only).** If the wire protocol is HTTP, agents with built-in HTTP fetch tools (Claude Code's WebFetch, etc.) can hit endpoints directly. Brittle in practice (agent has to guess URL shapes) but available "for free" with HTTP. Small point in HTTP's favour, not a path we'd recommend.

**Path C: MCP server wrapper (optional follow-on).** `inspect mcp` would run an MCP server translating MCP tool calls into control-channel calls. Worth building **only** if a specific gap emerges that Path A can't close:

- A host that doesn't allow shell access (rare for engineering tooling — Claude Code, Cursor, Zed all do).
- Per-tool permission gating that the host's shell allowlist can't express (Claude Code already supports per-command Bash allowlists, so the gap is narrow).
- A user base that strongly prefers MCP config over CLI installation.

Most claimed MCP benefits erode under scrutiny against a good CLI:

| Claimed MCP benefit | Reality with a JSON-first CLI |
|---|---|
| Structured returns | `--json` solves this. |
| LLM-friendly descriptions | Well-written `--help` and command docstrings work fine. |
| Server-side cursor state | `--since <cursor>` from the last event the agent saw, or a `~/.config/inspect/cursors/` file. |
| Per-tool permissions | Claude Code's Bash allowlist (`inspect cancel*` vs `inspect ls`) covers most of the granularity gap. |
| Tool discovery | `inspect --help` is enumerable; agents read it natively. |

Costs of building / maintaining an MCP wrapper, on the other hand, are real: extra process to spawn / configure / debug, second surface to keep in lockstep with the CLI, two vocabularies (`inspect_list_evals` vs `inspect ls`) for the same operations, failure modes invisible to the user.

If we ever build it, the JSON output schemas already in place make the MCP wrapper incremental rather than a parallel surface — the schemas are the same artifact.

**Path D: Native Python client library.** For agents written in Python (a watchdog scaffold wired up as a solver, or a separate Python script using `inspect` programmatically), a Python client library calls the control channel directly. No CLI / MCP indirection.

```python
from inspect_ai.control import ControlClient
async with ControlClient.attach() as client:
    async for event in client.eval_events(eval_id):
        if some_policy_violation(event):
            await client.cancel_sample(event.sample_id, action="error")
```

Lowest-overhead path for Python-native agents. Also the natural implementation substrate for the CLI commands (and for an MCP wrapper if one is ever built).

**Implications for the wire protocol choice.** Agent support doesn't tip JSON-RPC vs HTTP strongly — both are reachable via subprocess CLI (Path A). HTTP gives Path B for free but it's a small benefit. The bigger implication is that **CLI quality + JSON-first output is the agent integration story**; the wire protocol is one layer down and largely invisible to agent consumers.

### Direct surface for modifying running evals

The trickiest part of "more full featured". Cancel is easy (a flag the eval loop checks). Modifying limits or sample selection mid-flight needs the eval runner to support live config mutation, which today it doesn't.

Open question: which knobs are realistically directable mid-flight without rearchitecting the sample runner? Plausible initial set:

- **Per-sample time / token / message limits** — applied to samples *not yet started*; in-flight samples keep their current limits.
- **Concurrency caps** (`--max-samples`, `--max-tasks`) — the queue / dispatcher can honour a new value on the next dispatch tick.
- **Drain mode** — stop dispatching new samples; in-flight ones finish naturally.
- **Requeue** of failed / cancelled samples — re-add to the queue with the same id.

Each is a small surgical addition to the eval runner; the control channel is the wire that triggers them.

## Non-goals (v1)

- **Multi-machine / remote control.** Loopback-only socket today; remote attach is a separate auth/transport problem.
- **Resuming a finished eval over the channel.** Eval-retry is a CLI workflow that runs a fresh process; the channel is for live processes only.
- **Mutating an eval's task definition mid-flight.** Solvers, scorers, dataset are fixed at eval start.
- **A general-purpose RPC framework.** Methods are added deliberately; this is not "expose every internal as a remote call".

## Open questions

1. **Wire protocol (JSON-RPC 2.0 vs HTTP/REST + SSE).** See the tradeoffs table above. The decision shapes CLI ergonomics, dependency footprint, subscription mechanics, and how cleanly this evolves toward web tooling. Not blocked on consumer requirements — both can serve all three scenarios — but the answer rewrites most of the implementation surface.
2. **Eval-set lifecycle.** Does the control channel server live in the parent eval-set process and survive child-eval boundaries, or does each child eval restart it? The former is what consumers need but requires hoisting the server lifecycle up the call stack.
3. **Which directable knobs land in v1?** Cancel + drain + requeue is the minimum; modify-limits and modify-concurrency are bigger eval-runner changes.
4. **Auth.** Loopback today is fine for one-machine TUIs and CLI; agents that run on the same machine inherit the trust model. Anything remote needs explicit design. HTTP makes the "didn't I bind to loopback?" mistake easier — explicit codification needed if we go that route.
5. **Subscription replay.** A TUI that attaches to an in-progress eval needs to catch up on history — same problem as ACP's replay-on-attach, but at eval scope (event counts could be much larger). What's the bound and elision policy?
6. **Discovery for multi-process eval-sets.** Eval-sets that spawn worker processes (if/when) need a story for which process the discovery file points at.
7. **Risky operations.** Some directives are dangerous (`cancel --force`, `set-limit` to a higher value). Worth thinking about a confirmation / dry-run layer even on the loopback case. Doubly relevant for LLM-driven agents that retry on confusion — dry-run + idempotence aren't optional once agents are first-class consumers.
8. **CLI ergonomics for one-of-many.** When more than one eval is running, what's the disambiguation default — error and require `--eval-id`, or pick the newest (matching `inspect acp --stdio`'s behaviour)?
9. **Self-targeting from an LLM-agent inside an eval.** An LLM-driven agent monitoring an eval might itself be running *inside* an Inspect eval (a meta-solver). Should it be able to control its own parent eval? Probably not by default — worth a "no self-targeting" guard if/when this comes up.

## Implementation

To be planned in phases once the wire protocol is chosen. Likely first cuts (protocol-agnostic):

1. **Read-only eval status + list-evals.** No directives yet. Wire up a tiny eval-level state struct + a way to publish to it from the eval runner. Bind the chosen endpoint. Summary-shaped responses from the start (per the agent shape constraints).
2. **`inspect ls` / `inspect status` CLI with `--json` from day one.** Validates discovery + read path end-to-end before adding write paths. JSON output is a first-class mode, not an afterthought — the schema is the canonical shape and human-formatted output is a rendering of it. This phase makes the CLI usable by both human operators and shell-capable agents (Claude Code via Bash).
3. **Cancel-eval + `inspect cancel` CLI.** First directive. Idempotent and supporting `--dry-run` from day one.
4. **Eval event subscription stream + cursored pull endpoint.** Push for TUIs (`session/update`-style notifications or SSE), pull for agents (`inspect events <id> --since <cursor> --json`). Unlocks watchdog agents.
5. **TUI separation** — `inspect tui` as a standalone client. Largest piece; depends on the read + event-stream surfaces being in place.
6. **Modify-limits / drain / requeue.** Bigger eval-runner changes.
7. **Eval-set scope** — server lifecycle hoisted to the parent process; eval-set-level operations + events.

**Optional follow-on (only if a specific gap emerges):**

- **MCP server wrapper (`inspect mcp`).** Curated tool surface for LLM agents in hosts that can't / won't use shell access, or that need finer per-tool permissions than a Bash allowlist provides. Wraps the Python client library; reuses the JSON schemas from phases 1–4. We do NOT build this preemptively — Path A (CLI + JSON) should cover the agent integration story; this is the escape hatch if it doesn't.

Phase 1 is small enough to be a forcing function on the namespace decisions. Phases 1–4 give shell-capable agents (Claude Code via Bash) a complete read + direct + monitor surface. Phase 5 is the TUI payoff.
