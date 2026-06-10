# Control Channel

Part of a broader effort to make Inspect a first-class platform for **LLM-agent-driven eval workflows** — agents like Claude Code launching evals, monitoring them, intervening when needed, and reading results back. The control channel is one piece of that surface (live-eval observation and direction); other pieces — an inspect agent, agent-friendly `inspect eval` launching, `inspect log` for reading finished evals, CLI-wide JSON output conventions — are being developed alongside this work and are referenced in "Related work" at the bottom of the doc.

Within that scope, this doc covers the **control plane for live evals and eval-sets**: external processes (LLM agents, scripted watchdogs, TUIs, CLI commands) connecting to a running Inspect process to **observe** its state and **direct** it (cancel, modify config, drain, requeue, ...).

This is **separate from** the [`agent-acp`](acp/agent-acp.md) work, even though some plumbing overlaps. ACP is for per-sample agent conversation (sessions, prompts, cancels, updates). The control channel is for eval and eval-set management — a different shape that doesn't fit ACP's conversational vocabulary. The two coexist: the ACP server handles `session/prompt` and the existing per-sample `inspect/*` extensions (`inspect/cancel_sample`, `inspect/cancel_tool_call`, etc.); the control channel handles eval-level operations.

The rudimentary control surface that fell out of the ACP work (per-sample cancellation, socket discovery via `--acp-server`) is a useful precedent but not the foundation — the control channel deserves its own protocol choice.

> **Status (phases 1–2 shipped).** The read surface, per-sample events, and process keep-alive are implemented: the embedded FastAPI server on AF_UNIX, discovery, the `GET /evals` / `GET /evals/<id>/samples` (with an `active_since` recency delta) / `GET /evals/<id>/sample` / `GET /evals/<id>/sample/events` read endpoints, `POST /release`, the `inspect ctl tasks` / `samples` / `sample` / `errors` / `events` / `release` commands, and the `--ctl-server` flag (on by default; `false` disables, `keep-alive` parks the process after the eval). **Phase 2** added the cursored-pull per-sample transcript `events` API plus the recency-delta filter on `samples`. **Phase 3** adds the state-mutating directives (cancel / drain / requeue / modify-limits); **phase 4** adds the push (SSE / `--follow`) shape, including the eval-wide fan-in. Much of the prose below describes the full target surface — see [Implementation](#implementation) for what's built vs planned, which is the source of truth for phasing.

## Goals

Listed in priority order — the agent enablement goal is the primary motivator; the others fall out of it or support it.

- **Let LLM agents drive eval workflows.** Claude Code (and similar) should be able to use Inspect end-to-end: launch evals (via the surrounding CLI work), monitor live progress, cancel stalled samples, modify limits, intervene when policy-violating behavior occurs, then read results — all without humans in the loop on the mechanical operations. The control channel is the live-eval-management piece of that workflow. Concretely: this means JSON-first output, summary-shaped reads, idempotent + dry-runnable directives, and cursored event pull — see the "Shape constraints from agent consumers" section, which is **first-order** requirements driven by this goal, not derived ones.
- **Let programmatic / scripted agents do the same.** Python watchdogs, alerters, throttlers, dashboarders. Same surface, different runtime — anything an LLM agent does via the CLI, a script can do via the HTTP API (or a Python client library).
- Make eval and eval-set state **introspectable** from outside the running process without parsing logs.
- Make a running eval **directable** mid-flight: cancel, drain, requeue, throttle, adjust limits — operations that today require either killing the process or waiting for it to finish.
- Decouple the **Inspect TUI** from the eval process so the TUI can be opened, closed, and reattached without affecting the eval, and so a single TUI can observe multiple evals.
- Keep a **single coherent surface** — one HTTP endpoint per running Inspect process, one URL scheme, one auth story — that all consumer classes (LLM agents, scripted agents, TUIs, CLI) share.

## Scenarios

### 1. LLM agent driving evals end-to-end

The headline scenario. Claude Code (or similar) used to launch evals, monitor live progress, react to problems, and read results — with the user describing intent in natural language rather than driving each step by hand:

```
User: "Run my new task against gpt-5 and claude-opus. Cancel anything stalled
       past 10 minutes. When both runs finish, summarize results and tell me
       which model did better."

Agent (via Bash):
  inspect eval my_task --model gpt-5  --log-dir ./logs/gpt5  --detach --ctl-server=keep-alive --json
  inspect eval my_task --model claude --log-dir ./logs/opus  --detach --ctl-server=keep-alive --json
  inspect ctl tasks --json                                                      # watch progress
  inspect ctl samples <id> --active-since <ts> --json                        # poll for what changed / stalls
  inspect ctl cancel-sample <eval-id> <sample-id> --action error --dry-run   # check before acting
  inspect ctl cancel-sample <eval-id> <sample-id> --action error
  inspect ctl release --pid <pid>                                           # release the processes
  inspect ctl release --pid <pid>                                           # ...one for each
  (log summary and analysis TBD)
```

The `--ctl-server=keep-alive` value is load-bearing for this workflow: without it, each eval process exits the instant the eval body returns, taking its discovery file and control endpoint with it. The agent's later "inspect results" / "compare" / "decide" steps would race the process teardown and intermittently find no control surface to query. With keep-alive the process parks after the eval body completes, the control endpoint stays bound, and `inspect ctl release` is the explicit teardown signal the agent issues when it's done.

The control channel provides the **middle four** of those commands (the live-eval surfaces — `tasks`, `events`, `cancel-sample`); the surrounding commands come from the broader agent-enablement work (see Related work). For this scenario to work, every surface must be:

- JSON-output capable (`--json` everywhere).
- Summary-shaped by default — agents have limited context; full dumps don't fit.
- Idempotent + dry-runnable on destructive ops — agents retry on confusion.
- Discoverable via `--help` — agents read help text.

These constraints aren't TUI-friendly nice-to-haves; they're the primary surface requirements driven by this scenario.

### 2. Programmatic / scripted agents

Python watchdogs, alerters, throttlers, dashboarders wired up by the user:

- **Watchdog** — cancel any sample that exceeds a custom token-cost budget, or that runs longer than expected for its task class.
- **Alerter** — Slack / PagerDuty on first error, or when error rate crosses a threshold.
- **Adaptive throttler** — back off model concurrency when API errors spike.
- **Dashboarder** — push live metrics (samples completed, tokens used, mean latency, scoring distribution so far) to an external dashboard.

Same surface as scenario 1 — either via the CLI (Bash from a shell script) or via the Python client library (`from inspect_ai.control import ControlClient`). The Python library is also the implementation substrate for the CLI commands.

### 3. CLI commands to cancel or modify a running eval

Single-purpose human-driven CLI commands, all under the `inspect ctl` subcommand (see "CLI grouping" below). Phase-1 and phase-2 commands are shipped; the rest land with their phases (the directives → phase 3):

```
# phase 1 (shipped)
inspect ctl tasks                              # list running tasks
inspect ctl samples [TASK] [--active-since TS]  # per-sample table (status / retries / score / timing / idle)
inspect ctl sample TASK SID [EPOCH] [-t]    # one sample's error history (--traceback for full)
inspect ctl errors [TASK]                   # triage: samples that errored or were retried
inspect ctl release [--pid PID]            # release a lingering keep-alive process

# phase 2 (shipped)
inspect ctl events TASK SID [EPOCH]         # one sample's transcript events (cursored pull)
                                            #   --since CURSOR / --tail N / --type / --full / --since-time / --until
                                            #   (-f / --follow push is phase 4)

# phase 3 (directives)
inspect ctl cancel <eval-id> [--force]      # cancel an eval (current sample drains; scoring runs)
inspect ctl cancel-sample <eval-id> <sid>   # cancel one sample
inspect ctl drain <eval-id>                 # stop accepting new samples; let in-flight finish
inspect ctl requeue <eval-id> <sid>         # re-add a failed sample to the queue
inspect ctl set-limit <eval-id> --time N    # modify a running eval's per-sample time limit
```

Note the read commands take a **task** selector (task-id prefix or task name), not a raw eval-id: a task id is stable across retries, whereas a per-attempt eval id is not. Directives (phase 3) are shown above with `<eval-id>` as in the original sketch; their final selector is settled when they're built.

Each is a thin wrapper — autocomplete-friendly, scriptable, composable with shell tooling. Same operations as the TUI; same operations agents call. The CLI is the canonical surface — humans use it directly; agents use it via Bash.

#### CLI grouping: `inspect ctl`

All live-eval management commands live under a single `inspect ctl` subcommand rather than as flat top-level verbs (`inspect tasks`, `inspect cancel`, ...). The choice is deliberate:

- **Conceptual coherence.** Every command in the group operates on a running Inspect process via the control endpoint; they share infrastructure (discovery, auth, lifecycle) and a mental model. That's a real subsystem, not an arbitrary bag of verbs.
- **Namespace pressure.** Inspect's top-level CLI is already crowded (`eval`, `eval-set`, `eval-retry`, `view`, `log`, `score`, `cache`, `sandbox`, `acp`). Adding 7–8 new verbs there crowds discovery for everyone; grouping under `ctl` keeps the top level uncluttered.
- **Discoverability.** `inspect ctl --help` is the natural entry point for "what can I do with a running eval?" Both humans and agents read it once and have the whole surface.
- **Precedent.** `kubectl`, `systemctl`, `journalctl`, `etcdctl` — `ctl` reads as "control" instantly for anyone who's done ops work. The convention is established.
- **No alias.** `inspect control` does *not* exist as a long-form alias; `inspect ctl` is the only canonical form. Two names introduce documentation drift, "which is canonical?" ambiguity, and grep friction without paying for themselves.

`inspect tui` stays at the top level rather than under `ctl` — it's an *application* (like `inspect view`) that happens to be a control-channel client, not an operation on a running eval.

### 4. TUI in a separate process from the eval

Today `inspect eval --display full` runs a Textual TUI in the eval process itself. Closing the TUI requires killing the eval; running headless (`--display plain`) means giving up live state entirely.

The control channel makes the TUI a **client of the eval process**:

```
inspect eval --display none ...      # eval runs headless
inspect tui                          # separate terminal — attaches to the eval
```

The TUI observes eval / eval-set state, sample queue, in-flight samples, model usage, scoring progress; and can direct: cancel samples, cancel the eval, requeue failed samples, modify per-sample limits. Detaching the TUI doesn't disturb the eval.

**Combining multiple backends in one TUI** is a sub-scenario of this same capability — once the TUI is decoupled from the eval process, attaching to N evals (or an eval-set's worth) is the same thing extended: one TUI process holds N control-channel connections, with a top-level switcher across them. Single-eval and multi-eval differ only in how many connections the client holds; the underlying capability is identical. The existing in-process TUI can't do this because it lives inside one process — the moment the TUI becomes a client, multi-backend falls out.

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

**What was missing (the gap this work fills).** Everything ACP provides is *per-sample*; before the control channel there was nothing at the eval or eval-set layer. Operations like "cancel the eval", "list eval-set state", "modify the eval's per-sample limit" didn't exist. Discovery was per-eval. The TUI ran in-process. CLI surface was limited to `inspect acp [--stdio]` (the editor bridge). Phases 1–2 (shipped) now provide the eval-level **read** layer (`inspect ctl tasks` / `samples` / `sample` / `errors` / `events`, the `control/` discovery dir, eval-level `EvalState`, and the cursored per-sample transcript `events` pull); the eval-level **direct** operations and eval-set-level surface remain future work (phases 3 / later).

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

**Subscribe**
- Per-sample transcript **events**: the fine-grained `model` / `tool` / `error` / `score` / … firehose for one running sample (sourced from its `Transcript`). The one genuine stream.
- Eval-level lifecycle (sample queued / started / finished / errored, eval finished) is **not** a stream — current state is served by the reads (`tasks` / `samples`), with a recency delta on `samples`. An *ordered* lifecycle transition log is a later audit/TUI item.
- Eval-set-level lifecycle (child eval starting / finished, eval-set finished): same — served by eval-set reads (later), not a dedicated stream.

### Shape constraints from agent consumers

Four constraints fall out of supporting LLM-driven agents (see "Programmatic / agent consumers" below) that don't apply to TUIs / human CLI:

1. **Every read operation needs a structured (JSON) output form.** Agents parse JSON reliably; agents parse human-formatted tables poorly. CLI commands ship `--json` as a first-class output mode, not an afterthought. The JSON schema is the canonical shape — human-formatted output is a rendering of it. Same shape serves shell-pipeline users (`inspect ctl tasks --json | jq ...`) and LLM agents.
2. **Read operations should return summaries by default, with drill-down for detail.** Returning a 200-sample status dump as JSON eats LLM context. The `list samples` shape should default to a summary (status histogram + the N most-recent / longest-running) with a separate `get_sample(id)` for the full picture. Humans paginate / `jq`; agents need the shape to be agent-shaped at the source.
3. **Events need both push and pull access.** TUIs want push (SSE notification, immediate render). LLM agents want pull (cursored read: "events for eval X since cursor Y") — their runtimes are request/response loops, not subscription loops. The control channel should expose both shapes regardless of which the underlying transport favours; the push shape is the natural one for the wire protocol, the pull shape is a thin server-side buffer + cursor on top.
4. **Directives should be idempotent and support dry-run.** Agents retry, get confused, and operate on stale state. `requeue_sample` called twice must not double-queue. `cancel_eval` on an already-cancelled eval must return cleanly. Destructive directives should accept a `dry_run` flag that returns "would do X" without doing it, so agents can reason before acting.

## Architecture

The control channel runs as an **HTTP server embedded directly in the eval process** (FastAPI + uvicorn), exposing read, direct, and event-subscription operations. The eval process binds its own server distinct from `inspect view`'s server; the two run independently (see "Alternatives considered" below for why we're not folding them together yet).

### Why HTTP

- **Excellent CLI ergonomics.** `inspect ctl cancel <id>` is one `httpx` call; shell users can hit endpoints directly with `curl`. Pipe composition works (`inspect ctl tasks --json | jq ... | xargs inspect ctl cancel`). Easy to write small monitoring scripts in any language.
- **No new dependencies.** FastAPI, uvicorn, and starlette are already hard dependencies in `requirements.txt` (used by the `inspect view` server). Picking HTTP costs zero framework footprint.
- **Already a pattern in the codebase.** `src/inspect_ai/_view/fastapi_server.py` shows the FastAPI-server-in-Inspect template — including the bits we need: streaming responses, live in-progress reads (`api_pending_samples`, `api_sample_events`), and an OpenAPI generation pipeline (`_view/_openapi.py`). The control channel reuses the same shape.
- **Universal tooling.** Browsers, Postman, generated OpenAPI clients, HTTP-level proxies / logging / debugging — all off the shelf.
- **Natural fit for the operation shape.** "Cancel an eval" is request/response with optional payload — the canonical HTTP pattern. Resource-oriented URLs (`/evals/<id>/samples/<sid>`) describe what they target.
- **Future web UI is straightforward.** Browser-based dashboards consume HTTP and SSE directly; no gateway needed.
- **Clear separation from ACP.** Different protocol, different endpoint, different `_data_dir` subfolder — the boundary is structural, not just naming.

### Tradeoffs accepted

- **SSE is one-way** (server → client). A directive *during* a subscription requires a second HTTP call. Acceptable for our use cases — we don't have "subscribe then nudge" patterns where the latency of a parallel request matters.
- **Port-vs-socket policy.** Loopback TCP needs port allocation; AF_UNIX HTTP works (`httpx`, `curl --unix-socket`) but not universally across clients. We'll likely default to AF_UNIX and provide a TCP fallback flag, mirroring how `--acp-server` works.
- **Auth-mistake surface.** HTTP convention invites accidentally binding 0.0.0.0 or exposing through Docker port-mapping. We codify "loopback-only by default; remote binding requires explicit opt-in + auth" in the bind logic.

### Endpoint layout

The eval process binds **its own FastAPI server** on AF_UNIX (default) or loopback TCP. Discovery file at `<inspect_data_dir>/control/<pid>.json` records the bound address so clients can locate it — today the AF_UNIX `socket_path` (alongside `pid` / `run_id` / `started_at`); a `transport` tag distinguishing `unix` from `tcp` (`host` / `port`) arrives with the planned TCP fallback. Discovery follows the same PID-liveness cleanup pattern as the existing ACP discovery files.

This endpoint is **separate from** both the existing ACP socket (`<inspect_data_dir>/acp/<pid>.sock`) and the existing `inspect view` server (which runs as a separate process serving log files). Three endpoints, three concerns:

| Endpoint | Process | Protocol | Purpose |
|---|---|---|---|
| `inspect view` server | Standalone `inspect view` process | HTTP (FastAPI) | Read historical / live log files from disk |
| ACP socket | Eval process | JSON-RPC 2.0 | Per-sample agent conversation |
| **Control endpoint (new)** | **Eval process** | **HTTP (FastAPI)** | **Eval / eval-set management** |

### Endpoint table

Phase annotations reflect the [Implementation](#implementation) plan; phases 1–2 are built.

| Operation | Endpoint | Phase |
|---|---|---|
| List evals (folded per task) | `GET /evals` | 1 ✅ |
| List samples (running + completed + pending) | `GET /evals/<id>/samples` | 1 ✅ |
| Sample error detail | `GET /evals/<id>/sample?sample_id=<sid>&epoch=<n>` | 1 ✅ |
| Release a `--ctl-server=keep-alive` park | `POST /release` | 1 ✅ |
| Samples changed since (recency delta) | `GET /evals/<id>/samples?active_since=<ts>` | 2 ✅ |
| Sample transcript events (pull) | `GET /evals/<id>/sample/events?sample_id=<sid>&epoch=<n>&since=<cursor>` (JSON) | 2 ✅ |
| Sample transcript events (push) | `GET /evals/<id>/samples/<sid>/events` (SSE) | 4 |
| Eval-wide transcript fan-in (push only) | `GET /evals/<id>/samples/events` (SSE) | 4 |
| Cancel eval | `POST /evals/<id>/cancel` | 3 |
| Drain | `POST /evals/<id>/drain` | 3 |
| Requeue sample | `POST /evals/<id>/samples/<sid>/requeue` | 3 |
| Modify limits | `PATCH /evals/<id>` | 3 |
| List eval-sets | `GET /eval-sets` | later |
| Eval-set status | `GET /eval-sets/<id>` | later |
| Cancel eval-set | `POST /eval-sets/<id>/cancel` | later |

Notes on the built shape vs the original plan:

- **Eval status detail** was folded into `GET /evals` rather than a separate `GET /evals/<id>` — the list is already per-task (folded across retry attempts) and small, so the CLI fetches it and resolves a target client-side.
- **Sample detail** is keyed by `(sample_id, epoch)` (epochs make that the real identity) and is scoped to **error** detail (current error + `error_retries`) rather than a full sample dump. `sample_id` is a **query parameter**, not a path segment: sample ids are arbitrary strings and may contain `/`, `?`, `#`, etc., which a path segment can't carry — a query param is URL-encoded end to end.
- **`POST /release`** is process-scoped (no eval id) — it releases the keep-alive park for the whole process.

Destructive endpoints (phase 3+) accept `?dry_run=true` to return "would do X" without doing it (per the agent shape constraints).

### Architecture diagram

```
+------------------+      ACP socket (existing)         +-----------------+
| eval process     |  <-----------------------------    | inspect acp     |
|                  |    per-sample agent interaction    | (editor bridge) |
|                  |    (JSON-RPC 2.0)                  +-----------------+
|                  |
|                  |      control endpoint (new)        +-----------------+
|                  |  <-----------------------------    | inspect tui     |
|                  |    eval / eval-set management      +-----------------+
|                  |    (HTTP + SSE)                    | inspect ctl ... |
|                  |                                    | (CLI commands)  |
|                  |                                    +-----------------+
|                  |                                    | watchdog agent  |
+------------------+                                    +-----------------+

       (separate, today)

+------------------+      view server (existing)        +-----------------+
| inspect view     |  <-----------------------------    | browser         |
| process          |    log files (historical + live    +-----------------+
|                  |    via sample buffer)
|                  |    (HTTP + SSE)
+------------------+
```

### Discovery extended for eval-sets

Today's discovery file is per-eval (`<pid>.json` keyed by the eval's `run_id`). An eval-set is N sequential evals in one parent process; only one is alive at a time, so the existing per-pid file already points at the currently-running child eval.

What's missing for the eval-set scenarios:

- The discovery file needs an `eval_set_id` field so consumers can group child evals.
- The control channel needs to **persist across child-eval boundaries** within one eval-set — when a child eval finishes and the next one starts, the same socket should serve the new eval. (Today the per-eval `acp_server()` context manager re-binds on each child; we'd shift to a parent-process lifecycle for eval-sets.)

### Subscription model for monitoring agents

The one true *stream* is **per-sample transcript events** — fine-grained, sample-scoped, high-volume: the firehose of `model` / `tool` / `error` / `score` / … events sourced from a sample's `Transcript` (the same live subscription the ACP raw-event extension uses — see [Phase 2](#phase-2--per-sample-events--samples-deltas)). It's the one thing polling can't reconstruct, so it gets a real subscription, in two shapes by phase:

- **Pull (cursored) for agent clients** — *phase 2 (shipped)*: `GET /evals/<id>/sample/events?sample_id=<sid>&since=<cursor>`, returning a page plus a `next` cursor. Agent runtimes are request/response loops; SSE is awkward from a Bash tool call.
- **Push (SSE) for TUIs and long-lived clients** — *phase 4*: the same URL with `Accept: text/event-stream`, reusing the phase-2 cursor (stamped per event) for resumable reconnect.

**Eval-*level* monitoring does not need its own event stream.** Current state — which samples are running / done / errored, what's stalled (`last_activity_at`), retry history, whether the eval finished — is already a poll of the phase-1 reads (`tasks`, `samples`, `errors` / `sample`). The only thing a poll lacks is a cheap *delta*, which a recency filter on `samples` supplies (`?active_since=<ts>` — "samples started or updated since T"; see Phase 2). An *ordered* eval-level transition log (every intermediate state, in order) is an audit / replay / TUI need, not an agent-monitoring one — deferred to [later](#later-beyond-phase-4).

Both coexist with the per-sample ACP subscriptions — a TUI might use ACP for conversational interaction with one sample AND the control channel for eval-level lifecycle; a watchdog agent might use only cursored lifecycle pull and never touch ACP.

### Programmatic / agent consumers

Three exposure paths an external agent (Claude Code, scripted watchdog, custom agent runtime) might use. **Path A is the primary integration story; Path C is a deliberate "only if needed" follow-on.**

**Path A: CLI subprocess with `--json` output (primary).** Any agent that can run shell commands uses `inspect ctl tasks --json`, `inspect ctl samples <id> --json`, `inspect ctl cancel <id>`, `inspect ctl events <id> <sid> --since <cursor> --json` directly. Works with Claude Code's Bash tool, with shell scripts, with any subprocess-capable runtime.

Modern LLMs are demonstrably excellent at:
- Reading `inspect ctl --help` and discovering subcommands.
- Parsing JSON output and composing follow-up calls.
- Pipe composition (`inspect ctl tasks --json | jq '.[] | select(.status=="stuck")' | xargs -I{} inspect ctl cancel {}`).

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
| Per-tool permissions | Claude Code's Bash allowlist (`inspect ctl cancel*` vs `inspect ctl tasks`) covers most of the granularity gap. |
| Tool discovery | `inspect ctl --help` is enumerable; agents read it natively. |

Costs of building / maintaining an MCP wrapper, on the other hand, are real: extra process to spawn / configure / debug, second surface to keep in lockstep with the CLI, two vocabularies (`inspect_list_evals` vs `inspect ctl tasks`) for the same operations, failure modes invisible to the user.

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

### Security model

The control endpoint is default-on and unauthenticated. That's a deliberate trade-off — given the threat model it's the right one, but it deserves a written account.

**Network exposure: zero by construction.** The endpoint binds an AF_UNIX socket at `<inspect_data_dir>/control/<pid>.sock`. AF_UNIX is a filesystem object, not a network socket — it has no IP, no port, doesn't traverse any network stack. It is structurally impossible to reach from another machine. It also isn't reachable from inside containers (Docker, Inspect's sandboxes) unless the user explicitly bind-mounts `inspect_data_dir` into the container — which Inspect's own sandbox setups do not do.

**Local threat model.** On the same machine the relevant question is "who can talk to the socket?":

| Caller | Can connect? | Why |
|---|---|---|
| Same user, same machine | Yes | Trust model — same as your shell history, SSH agent socket, browser cookies. |
| Other users on the same machine | **No** | The directory permissions block them (see below). |
| Sandboxed eval processes | No | Sandboxes don't see the host's `inspect_data_dir`. |
| Remote attackers | No | AF_UNIX, no network path. |
| Root on the same machine | Yes | Filesystem perms can't constrain root. Not in scope — if you don't trust root, no Inspect setting helps. |

**What we do today** (implemented by `prepare_discovery_dir` and `write_discovery_file` in `_util/discovery.py`):

| Object | Mode | Rationale |
|---|---|---|
| `<inspect_data_dir>/control/` directory | **0700** | **Principal protection.** Without `x` permission on the directory, other users can't traverse into it — the socket and discovery JSON can't even be `stat()`'d, much less opened. |
| `<pid>.sock` (AF_UNIX socket) | 0600 | Defence-in-depth — closes the gap if the directory ever gets loosened. |
| `<pid>.json` (discovery file) | 0600 | Same — prevents the socket path / run_id leaking via a world-readable JSON. |

The directory and socket modes are applied via `chmod` on every server start (idempotent), so a directory created before the hardening landed gets locked down on the next bind. The discovery JSON is handled differently: it's created owner-only at `open()` time (the mode is passed to `os.open`, capped by the umask) and published with an atomic temp-write-then-rename, so it is never *momentarily* more permissive than 0600 (no post-write `chmod` window) and a concurrent `inspect ctl tasks` reader never observes a torn / partial-JSON file. Some filesystems ignore Unix permissions (FUSE, certain network mounts); the fallback is benign — everything still lives under `inspect_data_dir`, which is user-scoped, so the loss of defence-in-depth is bounded.

**What this buys us.** With the directory at 0700, an attempted connection from another user's process fails at the directory-traversal step (`EACCES`) before the socket file's own permissions are even consulted. The socket and JSON 0600 modes are belt-and-suspenders: they protect against a misconfigured umask, a future code path that lowers the directory perms, or a user running Inspect under different identities (sudo etc.) that accidentally widen perms.

**What this does NOT buy us:**

- **Same user, different process.** Filesystem perms can't distinguish "your Inspect eval" from "an untrusted script you ran as yourself" — both run with your UID. To enforce "only the launching eval can be controlled" would require an application-layer secret (cookie, capability token). Not in scope for v1 — trust model matches every other user-local IPC (D-Bus session bus, X11 socket, ssh-agent).
- **Sandboxed self-targeting.** Today sandboxes don't see the host data dir, so an LLM agent inside an eval can't reach the control channel. If a future scenario mounts the host data dir into a sandbox (eg. a meta-eval that watches other evals), that protection vanishes and we need a server-side "no self-targeting" guard (open question #8).
- **Filesystems that ignore Unix permissions.** Some FUSE / network filesystems don't enforce perms correctly. If a user places `inspect_data_dir` on such a filesystem, all bets are off — but that's also true of their ssh-agent socket, browser cookies, etc.

**Future hardening (when write endpoints land):**

- **SO_PEERCRED / `LOCAL_PEERCRED` UID check.** When `POST /evals/<id>/cancel` / `PATCH /evals/<id>` arrive (phase 3+), the server should verify the connecting process's UID matches our own and reject otherwise. Redundant with filesystem perms in the normal case, but cheap defence-in-depth.
- **Self-targeting guard.** Server-side rejection of any operation whose target eval is the caller's own process. Belongs in the bind-time check + each write handler. Tracked as open question #8.
- **Authenticated remote attach.** If/when remote-attach is in scope, design needed: bearer tokens, mTLS, or a more domain-specific mechanism. Out of scope for v1 (loopback-only is the only supported transport).

## Non-goals (v1)

- **Multi-machine / remote control.** Loopback-only socket today; remote attach is a separate auth/transport problem.
- **Resuming a finished eval over the channel.** Eval-retry is a CLI workflow that runs a fresh process; the channel is for live processes only.
- **Mutating an eval's task definition mid-flight.** Solvers, scorers, dataset are fixed at eval start.
- **A general-purpose RPC framework.** Methods are added deliberately; this is not "expose every internal as a remote call".

## Open questions

1. ~~**Eval-set lifecycle.**~~ **Resolved (phase 1).** The server runs on the eval's loop (not hoisted to a long-lived parent process). For eval-set with `retry_immediate=True` one server covers the whole run, and keep-alive parks afterward via a fresh sequential binding over the same registry — see "Server lifecycle aligned with `eval()`". `retry_immediate=False` is the documented exception (per-attempt servers; incompatible with keep-alive).
2. **Which directable knobs land in phase 3?** Cancel + drain + requeue is the minimum; modify-limits and modify-concurrency are bigger eval-runner changes.
3. **Auth.** Loopback today is fine for one-machine TUIs and CLI; agents that run on the same machine inherit the trust model. Anything remote needs explicit design. HTTP makes the "didn't I bind to loopback?" mistake easier — codify "loopback-only default; explicit opt-in + auth for remote" in the bind logic. (Phase 1 binds AF_UNIX only, so there's no remote surface yet; the explicit-opt-in TCP path arrives with the planned `--ctl-server=<port>` value.)
4. **Subscription replay.** A TUI that attaches to an in-progress eval needs to catch up on history — same problem as ACP's replay-on-attach, but at eval scope (event counts could be much larger). What's the bound and elision policy? (Framed by the phase-2 cursor — `--tail` seeding over the provider-backed history; replay-on-attach over push is phase 4.)
5. **Discovery for multi-process eval-sets.** Eval-sets that spawn worker processes (if/when) need a story for which process the discovery file points at.
6. **Risky operations.** Some directives are dangerous (`cancel --force`, `set-limit` to a higher value). Worth thinking about a confirmation / dry-run layer even on the loopback case. Doubly relevant for LLM-driven agents that retry on confusion — dry-run + idempotence aren't optional once agents are first-class consumers. (Phase 3.)
7. ~~**CLI ergonomics for one-of-many.**~~ **Resolved (phase 1).** Read commands take a task selector that matches a task-id prefix, then a task name (anchored at the start or after a `/`); when exactly one task is running it's the default, and ambiguous matches error with the candidate list. Targeting by stable task-id (not per-attempt eval-id) was the key choice.
8. **Self-targeting from an LLM-agent inside an eval.** An LLM-driven agent monitoring an eval might itself be running *inside* an Inspect eval (a meta-solver). Should it be able to control its own parent eval? Probably not by default — worth a "no self-targeting" guard if/when this comes up. (Becomes relevant with the phase-3 write endpoints.)

## Implementation notes

Cross-cutting details that apply across all phases.

### Process keep-alive: `--ctl-server=keep-alive` on `inspect eval` / `inspect eval-set`

Without help from the process lifecycle, LLM-agent workflows have a race condition: the eval process exits the instant the eval body returns, taking its control endpoint and discovery file with it. The agent's next step — read results, compare, decide what to do next — runs against a vanished surface. With many agents this manifests intermittently (sometimes the agent gets to `ctl tasks` before teardown, sometimes not) and degrades trust in the surface.

The fix is an explicit handoff: `--ctl-server=keep-alive` parks the process after the eval body completes, and `inspect ctl release` is the signal the agent issues when it's done. (Keep-alive is a *value* of the `--ctl-server` flag rather than a flag of its own because it presupposes the server — a parked process with no control endpoint could never be released. See "Flags" below.)

**What the value does.**

- `inspect eval <task> --ctl-server=keep-alive` — after the eval body returns (including scoring + log write), the process blocks on the control endpoint's shutdown event. The control server stays bound. `inspect ctl tasks` continues to show the eval (with `samples.completed == total` and a final status), and the log files are present at their final paths. `POST /release` (issued by `inspect ctl release` or any HTTP client) releases the block; the process tears down its server and exits.
- `inspect eval-set <tasks> --ctl-server=keep-alive` — same. With `retry_immediate=True` (the default), eval-set makes exactly one `eval()` call; per-task retries happen inside that one call, so the control server and the keep-alive park both live in the same single async context.

**Why this isn't always-on.** Most invocations don't need it; the cost is "process doesn't exit on its own." For batch / CI workflows that explicitly want the process to die when done, no keep-alive is correct. The park is opt-in (the *server* is on by default; only the park needs asking for).

### Server lifecycle aligned with `eval()` (and why no threads)

The control server runs on the eval's own anyio loop — same as the existing `task_display().run_task_app(...)` async boundary — with no daemon threads, no cross-loop synchronisation, and no per-thread state. Each binding is one `async with control_server(...)` on a single loop; where a second binding is needed (the eval-set keep-alive park) it's a *sequential* `anyio.run`, never a concurrent second loop. This keeps the control-channel code aligned with the rest of the (anyio-native, single-loop) codebase.

This works because in the common case `eval_set` is *also* a single `eval()` call:

- **`retry_immediate=True` (the default).** Eval-set invokes `eval()` exactly once. Per-task retries happen *inside* that single `eval()` call (via `task_retry_attempts` and the failed-sample-reuse path), so one control server bound for the duration of that `eval()` wraps the entire eval-set's actual work. Keep-alive then parks in a separate, sequential step *after* the display closes (a fresh control server over the same registry — see the Implementation sketch), rather than inside the run's server. Identical effective behaviour to a "threaded eval-set-scoped server" but without any threads.
- **`retry_immediate=False` (legacy batch-retry mode).** Eval-set invokes `eval()` repeatedly via tenacity. Each attempt is its own `eval()` call → its own `anyio.run` → its own control server. Between attempts the server is briefly torn down (`inspect ctl tasks` returns "no running evals" for that window). This is a documented limitation of the legacy mode.

**`--ctl-server=keep-alive` is incompatible with `retry_immediate=False`.** The post-retry-loop park would need its own async context outside any single `eval()`, which is exactly the multi-loop bridging problem the alignment chooses to avoid. Eval-set raises `PrerequisiteError` at startup if both are set, with a message pointing at `--retry-immediate` (or dropping the `keep-alive` value).

**Implementation sketch.**

- **Loop-native shutdown event.** `ControlServer` holds a `shutdown_event: anyio.Event` (not a `threading.Event`). The `POST /release` route sets it; `wait_for_shutdown_async(server)` is just `await server.shutdown_event.wait()`. Both the route and the waiter run on the same eval loop, so no thread or cross-loop bridge is needed. Release also **latches process-wide** (a module-level flag reset at the outermost run boundary): received while the eval is still running it means "exit when done", so both parks check the latch and skip — necessary for the eval-set park in particular, whose fresh server (and fresh event) couldn't otherwise see a release received by the run's server. (An earlier design parked on a `threading.Event` via `anyio.to_thread.run_sync`; that left an abandoned non-daemon worker thread blocked on `Event.wait()` after a Ctrl-C, which is why the loop-native event replaced it.)
- **Registry lifecycle: register on start, clear at the run boundary.** `task_run.py` *always* `register_eval`s a task and never unregisters it per-task — so a completed eval stays visible to `ctl tasks` for the rest of the run (including any keep-alive park) without a special "keep-alive active" flag. `clear_all_eval_states()` is called once at the outermost run boundary: `_eval_async_inner`'s `finally` when `eval_set_id is None` (standalone eval), or `eval_set`'s `finally` (eval-set). This replaced the earlier `keep_alive_active()` flag + per-task `unregister_eval` + `keep_alive_session` helper, which were removed.
- **Standalone eval parks inline.** `_eval_async_inner` opens `control_server(...)` + `acp_server(...)`, runs the eval body, then — still inside those contexts — prints the keep-alive notice and `await wait_for_shutdown_async(server)` when `ctl_server="keep-alive"`. One control server, parked while it's still bound.
- **Eval-set parks *after* the task display closes.** Eval-set runs its single inner `eval()` (which binds its own control server for the duration of the run, with `eval_set_id` set so that `eval()` does **not** park or clear). After the display tears down and the console summary prints, `eval_set` calls `run_coroutine(_keep_alive_park(eval_set_id))`: a fresh `control_server` is bound on a new loop and parked on its shutdown event. Two sequential server bindings (one during the run, one during the park), both serving the **same** process-global `EvalState` registry — so the surface is continuous across the brief gap while the summary prints. (Doing the park *after* the display closes is deliberate: otherwise the "keeping alive" notice lands inside the live task-display pane instead of the console.) The all-reused short-circuit — every task satisfied by a prior successful log, so `eval()` is never called — reaches the same `_keep_alive_park` with the reused logs already in the registry, so the parked surface looks identical.

**Failure modes worth naming.**

- **Forgotten release.** Agent crashes / loses track of the pid. The process lingers indefinitely. Mitigation: a future idle timeout on the park could auto-shutdown after N minutes. Not in v1.
- **Multiple lingering processes.** Several agents each run their own keep-alive eval. `inspect ctl release` with no args errors and lists pids; the agent disambiguates with `--pid`.
- **External kill.** Operator kills the process while keep-alive is active. The discovery file is left behind; the next `prepare_discovery_dir` sweep picks it up and removes it (pid-liveness check fails).
- **`retry_immediate=False` + keep-alive.** Rejected at startup with a clear error rather than silently giving a broken keep-alive experience.

### Server lifecycle: default on, opt-out

The control endpoint is bound by default whenever `inspect eval` runs. Every running eval benefits from being controllable, and the agent-enablement story falls apart if agents or TUIs can't discover evals launched without a special flag (per-launch opt-in defeats the whole "Claude Code uses Inspect by default" framing).

**Graceful degradation on bind failure.** If the AF_UNIX bind fails (read-only filesystem, restricted sandbox, permissions on `inspect_data_dir`), log a warning and continue without the surface. The eval runs normally; only the control surface is missing. Bind failures are *never* fatal — eval results don't depend on the control channel coming up.

This also covers *partial* startup failures. `start()` binds the socket and launches the server task *before* writing the discovery file, so a later-stage failure (eg. the discovery write) would otherwise leave a running server task and a live socket node behind. The startup path tears that partial state down (the same teardown used on normal shutdown) before degrading to "no surface", so a failed start never leaks a server or socket.

### Flags

One flag, `--ctl-server`, mirroring `--acp-server`'s overloaded-value shape (`ctl_server: bool | str | None` on `eval()` / `eval_set()` / `eval_retry()`):

```
(omitted)                       # control on, default AF_UNIX at <inspect_data_dir>/control/<pid>.sock
--ctl-server / --ctl-server=true   # control on (the explicit form of the default)
--ctl-server=false              # control off
--ctl-server=keep-alive         # control on + park the process after the eval finishes
```

An earlier draft split "whether" from "where" into separate flags (`--no-ctl` / `--ctl-port` / `--ctl-socket`) and kept keep-alive as its own orthogonal `--keep-alive` flag. Review feedback reversed that: one discoverable knob that matches the established `--acp-server` shape beats a family of flags, and folding keep-alive in as a value makes its dependency on the server *structural* — a parked process with no control endpoint could never be released, and `--ctl-server=false --keep-alive` is now unrepresentable rather than a configuration error to detect.

The transport "where" values (`--ctl-server=4444` for a TCP loopback port, `--ctl-server=/path/to.sock` for a custom AF_UNIX path) are **planned** — the same value space `--acp-server` already accepts. Until they land, any string other than `keep-alive` is rejected (more likely a typo of `keep-alive` than an intentional choice).

### Environment-variable mirror

`INSPECT_EVAL_CTL_SERVER` mirrors the flag (same values: `false` / `true` / `keep-alive`), following the `INSPECT_EVAL_ACP_SERVER` precedent. This lets a test runner or CI config globally suppress the surface (`INSPECT_EVAL_CTL_SERVER=false`) without modifying each `inspect eval` invocation.

### Relationship to `--acp-server`

The control channel defaults **on**; the ACP server defaults **off**. The asymmetry is intentional:

- ACP serves a narrow audience (editor-driven per-sample interaction) — most evals don't need it, so opt-in is right.
- Control serves every running eval — opt-out is right.

The flag shapes match (one overloaded-value flag each: `--acp-server=false|true|<port>|<host:port>|<path>`, `--ctl-server=false|true|keep-alive` with the transport values planned). The remaining difference is just the default (`--ctl-server` omitted means on; `--acp-server` omitted means off), which follows from the audience asymmetry above.

### Test-suite cost

Pytest runs that spawn many evals will each try to bind. AF_UNIX is cheap and discovery files self-clean via PID-liveness, but per-eval bind overhead is worth measuring in phase 1. Mitigations if it matters:

- Set `INSPECT_EVAL_CTL_SERVER=false` globally for the test session.
- Make the bind lazy (allocate only when something asks via discovery).

The graceful-fallback policy means worst-case is "test logs have warning lines"; eval correctness is unaffected.

## Implementation

Phased delivery, with HTTP/H1 as the chosen wire. **Phases 1 (read surface + keep-alive) and 2 (per-sample events + `samples` deltas) are implemented**; phase 3 (modification) and phase 4 (push / SSE) are planned.

### Phase 1 — read surface + keep-alive (done)

The always-on read surface plus the process-lifecycle plumbing agents need. Gives shell-capable agents (Claude Code via Bash) a complete read surface today.

- **`EvalState` aggregate** (`_control/eval_state.py`). A process-global registry of per-eval terminal-sample counters (`total` and the terminal buckets `completed` / `errored` / `cancelled`), cumulative usage (`total_tokens` / `total_messages`), task/model metadata, planned sample ids, log location, and a live `summaries_provider`. Registered when a task starts; folded by `(run_id, task_id)` so retry attempts of the same task collapse into one logical row (the latest registered attempt). Each sample bumps exactly one terminal bucket at its final outcome — `cancelled` (sibling-failure / eval-cancel teardown) is separate from `errored` so it doesn't read as a failure but still counts toward `total`, so the eval is marked finished (`completed_at`) and isn't stuck "running". A zero-sample eval (eg. `--limit` slices past the dataset — a valid success) is likewise not stuck: with `total == 0` it's marked finished the moment it registers, since there's no sample whose terminal outcome would otherwise stamp `completed_at`. Counters and usage survive a sample leaving `active_samples`, so completed / keep-alive-parked evals stay visible. Cleared at the outermost run boundary (the `eval()` call for standalone eval, the eval-set for eval-set).
- **FastAPI server on AF_UNIX** (default; bind failures log a warning and degrade gracefully). Discovery file at `<inspect_data_dir>/control/<pid>.json`; security hardening (0700 dir, 0600 socket + json) per the Security model.
- **Read endpoints:**
  - `GET /evals` — folded per-task summaries (subsumes the originally-planned `GET /evals/<id>` status detail; the CLI reads the whole list and resolves a task client-side).
  - `GET /evals/<id>/samples` — all of an eval's samples (running + completed + pending), merged from `active_samples` + the recorder's live summaries (falling back to the on-disk log) + the planned `(sample_id, epoch)` set. Running samples carry `last_activity_at` (unix ts of the sample's most recent transcript event) and `events` (a live event count) so a consumer can tell "stalled" from "working" — `now - last_activity_at` is the sample's idle time — without diffing successive polls. (Caveat: a single in-flight model generation emits no event until it returns, so neither field advances *within* one long call — the per-sample `events` stream has the same blind spot; closing it needs streaming token deltas or a "current operation" indicator via the `execution_observer`, out of scope here.)
  - `GET /evals/<id>/sample?sample_id=<sid>&epoch=<n>` — one sample's error detail: current error + prior-attempt `error_retries` (running samples sourced from `active_samples`, terminal ones from the log). `sample_id` is a query param so string ids with reserved chars (`/`, `?`, `#`) address correctly.
- **`POST /release`** — releases a `--ctl-server=keep-alive` park. The only write endpoint in phase 1, and it acts on the process, not on eval state.
- **CLI (`inspect ctl`, `--json` throughout):** `tasks` (running tasks), `samples [TASK]` (per-sample table: status / retries / score / timing / idle / tokens), `sample TASK SAMPLE_ID [EPOCH] [--traceback]` (one sample's error history), `errors [TASK]` (triage list of errored / retried samples), `release [--pid]`. `TASK` resolves by task-id prefix, then task-name (anchored at the name start or after a `/`); a sole running task is the default.
- **Retry + cancellation surfacing.** Sample retry counts — both sample-level `retry_on_error` and task-level retries (the latter seeded onto the re-run via the sample source, and carried across attempts that tear a sample down before it re-runs) — appear in `samples`; prior-attempt errors in `sample` / `errors`. A cancellation (a sibling failure tore the attempt down) is **not** a genuine error: it renders as `pending` when a retry will re-run the sample, `cancelled` when terminal — never `error`. This avoids the misleading "all samples error" snapshot during a retry teardown.
- **`--ctl-server`** on `inspect eval` / `inspect eval-set` — on/off plus the `keep-alive` park value (see Implementation notes).

### Phase 2 — per-sample events + `samples` deltas (done)

Two additions, both **cursored-pull** (push / `--follow` is deferred to [phase 4](#phase-4--push-sse) — pull is the agent-primary shape, needs no streaming infrastructure, and the cursor designed here is exactly what phase-4 push reuses):

- **Per-sample transcript `events`** — `GET /evals/<id>/sample/events?sample_id=<sid>&epoch=<n>` (`sample_id` a query param, as in `sample`, so ids with reserved chars address correctly). The firehose of `model` / `tool` / `error` / `score` / … events for one running sample. This is the genuine stream — the one thing polling the reads can't reconstruct.
- **A recency delta on `samples`** — `GET /evals/<id>/samples?active_since=<ts>`. "Samples started or updated since T," so a monitoring agent gets *what changed* in one read without diffing snapshots client-side. This subsumes what a separate eval-level "lifecycle updates" stream would have provided (see below).

There is deliberately **no** eval-level lifecycle event stream. Eval-level current state is already a poll of the phase-1 reads (`tasks` counts + status, `samples` status + `last_activity_at`, `errors` / `sample` retry history); the `samples` recency delta covers the "what changed" gap. An *ordered* eval-level transition log is an audit / replay / TUI concern, deferred to [later](#later-beyond-phase-4) — see "Why no lifecycle stream" below.

CLI: `inspect ctl events TASK SAMPLE_ID [EPOCH]` (transcript stream) and `inspect ctl samples TASK --active-since T` (the delta). Event-stream flags: `--since <cursor>`, `--tail N`, `--type`, `--full`, `--since-time/--until`, `--json`. (`-f/--follow` arrives with phase-4 push.)

#### Why no lifecycle stream

Building a dedicated eval-lifecycle event stream would mean a control-owned, hook-fed, ordered buffer per task (with its own cursor) — and for the agent monitoring loop it's largely redundant. An agent acts on *current state* ("sample 5 errored", "this one's idle 8m"), which is a poll away: status and counts from `tasks` / `samples`, stalls from `last_activity_at`, retry history from `retries` + `errors` / `sample`, "eval finished" from `tasks` `completed_at`. The only thing a poll lacks is a cheap delta — supplied by the `samples` recency filter. The sole thing a transition *log* uniquely adds is the *ordered intermediate history* (every flip, in order), which is an audit/replay/TUI need; deferring it avoids building (and cursoring) a second buffer until a real consumer wants it.

#### Event source

Every running sample owns a `Transcript` that is already a live, cursored event store: `_notify_subscribers(event)` fires registered callbacks on each append (push); `history.events_from(idx, limit)` reads from an index, `recent_events(n)` is the tail, `event_count` is the position (pull). The `TranscriptHistory` accessors are memory-aware: a bounded transcript keeps only a resident tail of events in memory, and reads below that window are materialized page-sized from the history provider (the realtime sample buffer) — so the cursored pull serves large transcripts gap-free without holding them resident. The ACP raw-event extension (`inspect/event` / `RawEventSubscriber`) is **one consumer** of this — it `subscribe_transcript_events(...)`, filters by an event-type set, replays the last N, serializes, and forwards as ACP notifications. The control channel is a **second consumer of the same source**, not layered on ACP and not requiring `--acp-server`: same subscription + cursored read, different transport (HTTP/SSE), different framing (raw transcript JSON vs ACP's semantic message mapping). Factor the subscribe + filter + serialize + cursor core into a shared helper so the two don't drift into separate serializers.

Completed samples have no live transcript — serve their events from the on-disk log (the same running-vs-terminal split as `samples` / `sample`).

#### Event types and projection

The per-sample `Event` union (each carries an `event:` discriminator, the filter key) splits into a **high-signal** tier (`model`, `tool`, `error`, `score`, `approval`, `input`, `sandbox`, `logger`, `info`, `sample_limit`, `interrupt`) and a **structural / high-volume** tier (`state`, `store`, `step`, `span_begin` / `span_end`, `sample_init`, `subtask`, `checkpoint`, `compaction`, `anchor`, `branch`, `score_edit`).

Raw transcript events are large (a `ModelEvent` carries full input messages + output + logprobs) and the structural tier fires constantly, so — mirroring the `samples` / `sample` summary-vs-detail pattern — the default is a **compact projection** per type (`model` → model name + token usage + stop reason + truncated text; `tool` → function + truncated args/result; `error` → message), with `--full` / `?full=true` for raw events. Default `--type` set is the high-signal tier; `--type model,tool` narrows, `--type '*'` includes everything.

#### Cursor

A cursor's one job is exactly-once incremental resume, so it must be a monotonic, gap-free, tie-broken position. That's the transcript's integer **append index**, not a timestamp and not an event uuid:

- **Not a uuid** — locating an event by uuid is an O(n) scan, and once an event is evicted (bounded transcripts) you can't compute how far behind you are. The index makes "how many did I miss" arithmetic.
- **Not a timestamp** — wall-clock `timestamp`s collide across concurrent samples (exclusive `>` skips boundary events, inclusive `>=` duplicates them) and aren't strictly monotonic (NTP), so they can't guarantee no-skip/no-dup resume. Timestamps are a *filter*, not a cursor (below).

Wire it as an **opaque token** (core = the index) carrying the sample's **attempt identity**: the sample uuid (`EvalSample.uuid` == `TaskState.uuid`) plus the attempt count (the number of prior failed attempts, read off `error_retries`). The running source and the terminal (logged) source derive this identically, so a cursor handed out *while the sample runs* stays valid once it's logged — the running→terminal transition does not look like a different run. A retry, on the other hand, runs on a **fresh transcript**: a task-level retry mints a fresh uuid, and an in-process `retry_on_error` reuses the uuid but increments the attempt count — so a cursor carried across either no longer matches and the server signals a reset instead of silently applying a stale index to unrelated events. The client round-trips the token (`--since <token>`); opaque also lets the encoding evolve. Response is an **envelope**:

```json
{ "events": [...], "next": "<cursor>", "done": false }
```

- `next` — pass to the next call. `since` is **exclusive** (events with index > cursor; `next` = index of the last event *scanned*).
- `done` — sample has terminated; no more events will come, so a polling agent knows to stop.

A served page is **always contiguous** from the cursor — there is deliberately no "gap" / `missed` field. A bounded transcript's evicted events are re-materialized transparently from its history provider (the realtime sample buffer, read page-sized via `TranscriptHistory.events_from(start, limit)`), so eviction never gaps a page. The one theoretical exception — events evicted with *no* provider — is not a production configuration (bounded mode is only enabled together with the buffer, which is the provider) and surfaces as a hard error (structured 500), never as a silently-gapped stream. An earlier draft carried a soft `missed` count for this case; it was dropped as dead surface once provider-backed reads made the gap unreachable.

**The cursor indexes the unfiltered sequence; `--type` is applied to the page after slicing.** So `next` reflects the last event *scanned*, not the last *matched* — a sparse filter (or changing `--type` between calls) still advances correctly and never re-walks or skips. Starting points are flags, not magic cursor values: no `--since`/`--tail` → start from now (follow) or a small default tail; `--tail N` → seed from `recent_events(N)`; `--since <token>` → resume.

This cursor is exactly what the phase-4 push path reuses: each SSE event is stamped with its index, so a dropped `--follow` reconnects with `--since <last index>`. Pull is built first; push layers on without a new cursor model.

#### Multiple samples

Each sample's transcript has its **own** independent index — there is no eval-wide monotonic sequence (events are created in separate sample tasks; nothing assigns a global counter). So a single scalar cursor can't span samples. Split by consumer rather than forcing one:

- **Agents** compose **the reads + per-sample drill-down**: poll `samples` (with `?active_since` for the delta) to spot a sample that errored or stalled, then read *that* sample's transcript `events`. This covers the monitoring loop with no multi-sample transcript cursor — and it's all cursored pull / poll, so it's fully available in phase 2.
- **TUIs / dashboards** that want the merged firehose want it *live*, which is push: an **eval-wide SSE fan-in** (`GET /evals/<id>/samples/events`) merging every running sample's subscription — live tail, no cursor. Being push, it lands in [phase 4](#phase-4--push-sse).

A multi-sample *cursored pull* of transcript events is intentionally **not** built unless a concrete need appears (lifecycle + drill-down serves agents). If it ever is, the cursor is a **composite vector of per-sample indices** encoded into one opaque token — never a timestamp.

#### Time as a filter, not a cursor

A wall-clock window is a snapshot query (no exactly-once requirement), which is genuinely useful and cheap: on the event stream, `--since-time T1 [--until T2]` filters the page after the cursor slice; the `samples` recency delta (`?active_since=<ts>`) is the same family — "current state of whatever changed since T," not a resume position. Both are timestamp-as-*filter*, which is fine precisely because they don't promise exactly-once. The right home for "by time" without ever being load-bearing for resumption.

Unlocks watchdog agents (cursored polling). Live-render TUIs follow once phase-4 push lands.

### Phase 3 — modification (direct) methods

The first endpoints that **mutate eval state**, each idempotent and supporting `?dry_run=true` / `--dry-run` from day one:

- `POST /evals/<id>/cancel` + `inspect ctl cancel` — graceful drain vs `--force`.
- `POST /evals/<id>/drain`, `POST /evals/<id>/samples/<sid>/requeue`, `PATCH /evals/<id>` (modify per-sample limits / concurrency) + their CLI wrappers.

These are the bigger eval-runner changes (live config mutation, requeue). The Security model's "future hardening" (SO_PEERCRED UID check, self-targeting guard) lands with this phase, since it introduces the first state-mutating writes.

### Phase 4 — push (SSE)

Adds the **push** shape on top of the phase-2 per-sample event stream — for TUIs, dashboards, and other long-lived clients that render live rather than poll. No new data model: it reuses the phase-2 cursor and projections.

- **`--follow` on the per-sample event stream.** `GET /evals/<id>/samples/<sid>/events` with `Accept: text/event-stream` streams the same items as the pull path. Each SSE event is stamped with its cursor index, so a dropped connection reconnects with `--since <last index>` — i.e. follow is just "pull, kept open," with the same `--type` / `--full` / `--since-time` filters.
- **Eval-wide transcript fan-in** — `GET /evals/<id>/samples/events` (SSE only). Server-merges every *running* sample's transcript subscription into one stream, each event tagged with `sample_id` / `epoch`, so a dashboard watches the whole eval over one connection. No cursor (no eval-wide monotonic sequence — see phase 2). The wrinkle is **dynamic membership**: it must subscribe to newly-started samples and drop finished ones mid-stream. It's the most optional piece — a client can open one per-sample SSE per running sample and merge client-side meanwhile — so it lands last.

Splitting push out from phase 2 keeps the agent-primary (cursored pull) surface shippable without committing to streaming infrastructure, and lets directives (phase 3) land first.

### Later (beyond phase 4)

- **Ordered eval-level lifecycle log** — a control-owned, hook-fed, cursored transition history (sample queued / started / finished / errored, eval finished, in order). Deliberately deferred from phase 2: the agent monitoring loop is served by the reads + the `samples` recency delta, so this is for audit / replay / a live-render TUI. When built it gets its own monotonic cursor (a sequence into the buffer, same opaque-token contract as the event stream) and feeds phase-4 push. Build it only when a concrete consumer needs the *ordered* history.
- **TUI separation** — `inspect tui` as a standalone HTTP client of the control endpoint (plus an ACP client of the ACP socket for per-sample drill-down). Depends on the read + pull (phase 2) surfaces and, for live rendering, the phase-4 push surface (and, for an eval-level activity feed, the lifecycle log above).
- **Eval-set-level read/direct** — an `EvalSetState` aggregate (doesn't exist today), `GET /eval-sets`, `GET /eval-sets/<id>`, `POST /eval-sets/<id>/cancel`. Note eval-set *keep-alive* already works in phase 1 via the single-`eval()` lifecycle.
- **MCP server wrapper (`inspect mcp`)** — optional, built **only** if a specific gap emerges that Path A (CLI + `--json`) can't close. Reuses the phase 1–2 JSON schemas, so it's incremental rather than a parallel surface.

## Alternatives considered

Recording the paths we evaluated and rejected (for now) so future maintainers see the reasoning rather than re-litigating.

### JSON-RPC 2.0 on a separate socket

The original "obvious" choice given the existing ACP socket also speaks JSON-RPC. Each operation would become a method (`inspect/eval_status`, `inspect/cancel_eval`, ...); notifications carry events.

**Why we didn't pick it:**

- **CLI ergonomics are poor.** `inspect ctl cancel <id>` needs a JSON-RPC client wrapper; no `curl` story; harder to script ad-hoc.
- **No off-the-shelf tooling.** Browsers can't speak it; no Postman equivalent; cross-language client ecosystem is narrow.
- **Coupling temptation.** Sharing or echoing the ACP socket's module / process layout makes it easy to drift back into "the control channel is an ACP extension" — exactly the framing we rejected up front.
- **Doesn't evolve toward a web UI.** A future browser-based dashboard would need a JSON-RPC↔HTTP gateway.

**What it would have given us:**

- High reuse of ACP plumbing (same `Connection`, router, discovery scaffolding).
- Native bidirectional notifications (no SSE-vs-WebSocket question).
- Stricter "loopback only" feel — HTTP convention invites accidental wider binding.

The ACP plumbing reuse was the strongest argument and it turned out to be a wash: FastAPI + uvicorn + starlette are already hard deps, and the `_view/fastapi_server.py` template provides equivalent reuse on the HTTP side. Once that became clear the JSON-RPC case collapsed.

### H2: Extend the existing `inspect view` server to handle live state + control

Rather than running a separate HTTP server in the eval process (H1, chosen), one could imagine **the view server** absorbing the control role: `inspect view` already reads live in-progress sample state via the sample-buffer files; extending it to also expose control operations would unify "live observation" and "log viewing" at one endpoint.

**Why we deferred:**

- **Different process identity.** The view server is cross-eval, multi-log, optionally remote-accessible. A control endpoint is per-eval-process, lifecycle-tied to one eval (or eval-set), strictly loopback. Folding them mixes lifecycle and access-control concerns.
- **Different IPC story.** The view server today is *read-only* and gets live data via files (the sample buffer). Adding *write* operations means adding a path back to the eval process anyway — which is just H1 with extra hops.
- **Risk of premature unification.** We don't yet know the right schemas / endpoints for the control surface; coupling them now to a server with a different evolution trajectory makes both harder to iterate on.

**What it might give us later.** Once both surfaces stabilise, sharing code between them is plausible: the view server could become a client of the eval process's control endpoint for live data (replacing the file-buffer read), keeping its standalone-process identity but unifying the "live state" wire format. That's a follow-on worth revisiting once H1 has shipped and the schemas are settled — not a v1 concern.

### MCP wrapper as the primary agent integration

Considered making `inspect mcp` the primary surface for LLM-agent consumers. Rejected in favour of CLI + `--json` (Path A in "Programmatic / agent consumers") because modern LLMs are excellent at shell use, MCP adds a second surface to keep in lockstep with the CLI, and most claimed MCP benefits (structured returns, tool descriptions, cursor state, permissions) erode against a well-designed JSON-first CLI. Kept as an optional follow-on if a specific gap emerges that the CLI can't close.

## Related work

The control channel is one slice of a broader effort to make Inspect a first-class platform for LLM-agent-driven eval workflows. The pieces below are out of scope for this doc but are being designed / built alongside it; they share the same JSON-first, agent-friendly conventions:

- **Agent-friendly `inspect eval`.** Launching an eval as an agent: `--json` output reporting the started run_id / log path / control-channel address; `--detach` so the agent can fire-and-monitor rather than block; structured pre-flight estimates (cost, sample count). The handoff from "launched" to "monitored via control channel" depends on this.
- **Agent-friendly `inspect log`.** Reading finished evals as an agent: `inspect log summary <file> --json`, `inspect log sample <file> <id> --json`, `inspect log compare <a> <b> --json`. The control channel handles live evals; `inspect log` handles finished ones. The handoff between them is part of the agent workflow.
- **CLI-wide ergonomics push.** Every `inspect` subcommand the agent might use needs `--json` and agent-friendly defaults. Help text written verb-first, with examples, no option-vs-flag ambiguity. The "Shape constraints" in this doc (summary-shaped, idempotent, dry-runnable, JSON-first) are CLI-wide conventions, not control-channel-specific ones.
- **Cost / budget visibility.** Agents making scope decisions need to see pre-run estimates and live spend. The control channel exposes live spend (via `EvalState` model usage); pre-run estimates and budget enforcement live in `inspect eval`'s launch surface.
- **Self-targeting guard hardening.** Open question #8 in this doc — an LLM agent running *inside* an eval shouldn't be able to control its own parent eval. The guard logically belongs in the control channel's bind / authorisation layer, but the broader story (sandbox network egress, capability gating, eval-time vs scaffold-time boundaries) is part of the larger agent-enablement effort.
- **"Using Inspect from an LLM agent" documentation.** A guide that walks through the full workflow (launch, monitor, manage, inspect, compare, iterate) and points at every relevant CLI command. Lives in `docs/`, not `design/`.

Where this doc's design touches one of those surfaces (eg. the `EvalState` model that powers `inspect ctl tasks`), we describe what the control channel does and reference the broader work for the surrounding context.
