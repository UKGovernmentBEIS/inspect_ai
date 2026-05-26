# Control Channel

Part of a broader effort to make Inspect a first-class platform for **LLM-agent-driven eval workflows** — agents like Claude Code launching evals, monitoring them, intervening when needed, and reading results back. The control channel is one piece of that surface (live-eval observation and direction); other pieces — agent-friendly `inspect eval` launching, `inspect log` for reading finished evals, CLI-wide JSON output conventions — are being developed alongside this work and are referenced in "Related work" at the bottom of the doc.

Within that scope, this doc covers the **control plane for live evals and eval-sets**: external processes (LLM agents, scripted watchdogs, TUIs, CLI commands) connecting to a running Inspect process to **observe** its state and **direct** it (cancel, modify config, drain, requeue, ...).

This is **separate from** the [`agent-acp`](acp/agent-acp.md) work, even though some plumbing overlaps. ACP is for per-sample agent conversation (sessions, prompts, cancels, updates). The control channel is for eval and eval-set management — a different shape that doesn't fit ACP's conversational vocabulary. The two coexist: the ACP server handles `session/prompt` and the existing per-sample `inspect/*` extensions (`inspect/cancel_sample`, `inspect/cancel_tool_call`, etc.); the control channel handles eval-level operations.

The rudimentary control surface that fell out of the ACP work (per-sample cancellation, socket discovery via `--acp-server`) is a useful precedent but not the foundation — the control channel deserves its own protocol choice.

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
  inspect eval my_task --model gpt-5         --log-dir ./logs/gpt5   --detach --json
  inspect eval my_task --model claude-opus   --log-dir ./logs/opus   --detach --json
  inspect ctl ls --json                                                      # watch progress
  inspect ctl events <id> --since <cursor> --json                            # poll for stalls
  inspect ctl cancel-sample <eval-id> <sample-id> --action error --dry-run   # check before acting
  inspect ctl cancel-sample <eval-id> <sample-id> --action error
  inspect log summary ./logs/gpt5 --json                                     # after completion
  inspect log compare ./logs/gpt5 ./logs/opus --json                         # diff
```

The control channel provides the **middle four** of those commands (the live-eval surfaces — `ls`, `events`, `cancel-sample`); the surrounding commands come from the broader agent-enablement work (see Related work). For this scenario to work, every surface must be:

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

Single-purpose human-driven CLI commands, all under the `inspect ctl` subcommand (see "CLI grouping" below):

```
inspect ctl ls                              # list running evals
inspect ctl status <eval-id>                # eval status detail
inspect ctl events <eval-id> [--since X]    # event stream (push or cursored pull)
inspect ctl cancel <eval-id> [--force]      # cancel an eval (current sample drains; scoring runs)
inspect ctl cancel-sample <eval-id> <sid>   # cancel one sample
inspect ctl drain <eval-id>                 # stop accepting new samples; let in-flight finish
inspect ctl requeue <eval-id> <sid>         # re-add a failed sample to the queue
inspect ctl set-limit <eval-id> --time N    # modify a running eval's per-sample time limit
```

Each is a thin wrapper — autocomplete-friendly, scriptable, composable with shell tooling. Same operations as the TUI; same operations agents call. The CLI is the canonical surface — humans use it directly; agents use it via Bash.

#### CLI grouping: `inspect ctl`

All live-eval management commands live under a single `inspect ctl` subcommand rather than as flat top-level verbs (`inspect ls`, `inspect cancel`, ...). The choice is deliberate:

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

1. **Every read operation needs a structured (JSON) output form.** Agents parse JSON reliably; agents parse human-formatted tables poorly. CLI commands ship `--json` as a first-class output mode, not an afterthought. The JSON schema is the canonical shape — human-formatted output is a rendering of it. Same shape serves shell-pipeline users (`inspect ctl ls --json | jq ...`) and LLM agents.
2. **Read operations should return summaries by default, with drill-down for detail.** Returning a 200-sample status dump as JSON eats LLM context. The `list samples` shape should default to a summary (status histogram + the N most-recent / longest-running) with a separate `get_sample(id)` for the full picture. Humans paginate / `jq`; agents need the shape to be agent-shaped at the source.
3. **Events need both push and pull access.** TUIs want push (SSE notification, immediate render). LLM agents want pull (cursored read: "events for eval X since cursor Y") — their runtimes are request/response loops, not subscription loops. The control channel should expose both shapes regardless of which the underlying transport favours; the push shape is the natural one for the wire protocol, the pull shape is a thin server-side buffer + cursor on top.
4. **Directives should be idempotent and support dry-run.** Agents retry, get confused, and operate on stale state. `requeue_sample` called twice must not double-queue. `cancel_eval` on an already-cancelled eval must return cleanly. Destructive directives should accept a `dry_run` flag that returns "would do X" without doing it, so agents can reason before acting.

## Architecture

The control channel runs as an **HTTP server embedded directly in the eval process** (FastAPI + uvicorn), exposing read, direct, and event-subscription operations. The eval process binds its own server distinct from `inspect view`'s server; the two run independently (see "Alternatives considered" below for why we're not folding them together yet).

### Why HTTP

- **Excellent CLI ergonomics.** `inspect ctl cancel <id>` is one `httpx` call; shell users can hit endpoints directly with `curl`. Pipe composition works (`inspect ctl ls --json | jq ... | xargs inspect ctl cancel`). Easy to write small monitoring scripts in any language.
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

The eval process binds **its own FastAPI server** on AF_UNIX (default) or loopback TCP. Discovery file at `<inspect_data_dir>/control/<pid>.json` records `{transport: "unix", socket_path}` or `{transport: "tcp", host, port}` so clients can locate it. Discovery follows the same PID-liveness cleanup pattern as the existing ACP discovery files.

This endpoint is **separate from** both the existing ACP socket (`<inspect_data_dir>/acp/<pid>.sock`) and the existing `inspect view` server (which runs as a separate process serving log files). Three endpoints, three concerns:

| Endpoint | Process | Protocol | Purpose |
|---|---|---|---|
| `inspect view` server | Standalone `inspect view` process | HTTP (FastAPI) | Read historical / live log files from disk |
| ACP socket | Eval process | JSON-RPC 2.0 | Per-sample agent conversation |
| **Control endpoint (new)** | **Eval process** | **HTTP (FastAPI)** | **Eval / eval-set management** |

### Endpoint table

| Operation | Endpoint |
|---|---|
| List evals | `GET /evals` |
| Eval status | `GET /evals/<id>` |
| List samples (summary) | `GET /evals/<id>/samples` |
| Sample detail | `GET /evals/<id>/samples/<sid>` |
| Cancel eval | `POST /evals/<id>/cancel` |
| Drain | `POST /evals/<id>/drain` |
| Requeue sample | `POST /evals/<id>/samples/<sid>/requeue` |
| Modify limits | `PATCH /evals/<id>` |
| Eval event stream (push) | `GET /evals/<id>/events` (SSE) |
| Eval events (pull) | `GET /evals/<id>/events?since=<cursor>` (JSON) |
| List eval-sets | `GET /eval-sets` |
| Eval-set status | `GET /eval-sets/<id>` |
| Cancel eval-set | `POST /eval-sets/<id>/cancel` |

Destructive endpoints accept `?dry_run=true` to return "would do X" without doing it (per the agent shape constraints).

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

Eval-scoped events expose **two shapes** of the same data:

- **Push (SSE) for TUIs and long-lived clients**: `GET /evals/<id>/events` with `Accept: text/event-stream`. The TUI opens this once on attach and renders events as they arrive. Same for eval-set events: `GET /eval-sets/<id>/events`.
- **Pull (cursored) for agent clients**: `GET /evals/<id>/events?since=<cursor>` returning a JSON array of events plus a `next` cursor. Agent runtimes are request/response loops; SSE is awkward to consume from a Bash tool call. The pull shape is a thin server-side buffer + cursor on top of the same event source the SSE stream uses.

Both shapes coexist with the per-sample ACP subscriptions — a TUI attached to one sample sees eval events (via the control channel SSE) AND per-sample updates (via the ACP socket); a watchdog agent might subscribe only to eval events via cursored pull and never touch ACP.

### Programmatic / agent consumers

Three exposure paths an external agent (Claude Code, scripted watchdog, custom agent runtime) might use. **Path A is the primary integration story; Path C is a deliberate "only if needed" follow-on.**

**Path A: CLI subprocess with `--json` output (primary).** Any agent that can run shell commands uses `inspect ctl ls --json`, `inspect ctl status <id> --json`, `inspect ctl cancel <id>`, `inspect ctl events <id> --since <cursor> --json` directly. Works with Claude Code's Bash tool, with shell scripts, with any subprocess-capable runtime.

Modern LLMs are demonstrably excellent at:
- Reading `inspect ctl --help` and discovering subcommands.
- Parsing JSON output and composing follow-up calls.
- Pipe composition (`inspect ctl ls --json | jq '.[] | select(.status=="stuck")' | xargs -I{} inspect ctl cancel {}`).

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
| Per-tool permissions | Claude Code's Bash allowlist (`inspect ctl cancel*` vs `inspect ctl ls`) covers most of the granularity gap. |
| Tool discovery | `inspect ctl --help` is enumerable; agents read it natively. |

Costs of building / maintaining an MCP wrapper, on the other hand, are real: extra process to spawn / configure / debug, second surface to keep in lockstep with the CLI, two vocabularies (`inspect_list_evals` vs `inspect ctl ls`) for the same operations, failure modes invisible to the user.

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

1. **Eval-set lifecycle.** Does the control channel server live in the parent eval-set process and survive child-eval boundaries, or does each child eval restart it? The former is what consumers need but requires hoisting the server lifecycle up the call stack.
2. **Which directable knobs land in v1?** Cancel + drain + requeue is the minimum; modify-limits and modify-concurrency are bigger eval-runner changes.
3. **Auth.** Loopback today is fine for one-machine TUIs and CLI; agents that run on the same machine inherit the trust model. Anything remote needs explicit design. HTTP makes the "didn't I bind to loopback?" mistake easier — codify "loopback-only default; explicit opt-in + auth for remote" in the bind logic from phase 1.
4. **Subscription replay.** A TUI that attaches to an in-progress eval needs to catch up on history — same problem as ACP's replay-on-attach, but at eval scope (event counts could be much larger). What's the bound and elision policy?
5. **Discovery for multi-process eval-sets.** Eval-sets that spawn worker processes (if/when) need a story for which process the discovery file points at.
6. **Risky operations.** Some directives are dangerous (`cancel --force`, `set-limit` to a higher value). Worth thinking about a confirmation / dry-run layer even on the loopback case. Doubly relevant for LLM-driven agents that retry on confusion — dry-run + idempotence aren't optional once agents are first-class consumers.
7. **CLI ergonomics for one-of-many.** When more than one eval is running, what's the disambiguation default — error and require `--eval-id`, or pick the newest (matching `inspect acp --stdio`'s behaviour)?
8. **Self-targeting from an LLM-agent inside an eval.** An LLM-driven agent monitoring an eval might itself be running *inside* an Inspect eval (a meta-solver). Should it be able to control its own parent eval? Probably not by default — worth a "no self-targeting" guard if/when this comes up.

## Implementation notes

Cross-cutting details that apply across all phases.

### Server lifecycle: default on, opt-out

The control endpoint is bound by default whenever `inspect eval` runs. Every running eval benefits from being controllable, and the agent-enablement story falls apart if agents or TUIs can't discover evals launched without a special flag (per-launch opt-in defeats the whole "Claude Code uses Inspect by default" framing).

**Graceful degradation on bind failure.** If the AF_UNIX bind fails (read-only filesystem, restricted sandbox, permissions on `inspect_data_dir`), log a warning and continue without the surface. The eval runs normally; only the control surface is missing. Bind failures are *never* fatal — eval results don't depend on the control channel coming up.

### Flags

Three flags, each doing one thing:

```
(omitted)                       # control on, default AF_UNIX at <inspect_data_dir>/control/<pid>.sock
--no-ctl                        # control off
--ctl-port N                    # control on, force TCP on port N (implies enabled)
--ctl-socket /path/to.sock      # control on, custom AF_UNIX path (implies enabled)
```

`--no-ctl` + `--ctl-port` (or `--ctl-socket`) is a configuration error — the flags conflict.

Splitting "whether" from "where" into separate flags (rather than overloading one flag with `bool | int | str` values, as `--acp-server` does) is deliberate: it makes flag intent obvious at a glance and avoids "false" reading as a magic value.

### Environment-variable mirrors

For CI / test isolation, every flag has an env-var equivalent:

```
INSPECT_CTL=false               # disable globally
INSPECT_CTL_PORT=N              # force TCP
INSPECT_CTL_SOCKET=PATH         # force AF_UNIX path
```

This lets a test runner globally suppress the surface without modifying each `inspect eval` invocation.

### Relationship to `--acp-server`

The control channel defaults **on**; the ACP server defaults **off**. The asymmetry is intentional:

- ACP serves a narrow audience (editor-driven per-sample interaction) — most evals don't need it, so opt-in is right.
- Control serves every running eval — opt-out is right.

Flag shapes also differ (`--acp-server` uses overloaded values; `--no-ctl` / `--ctl-port` / `--ctl-socket` split into separate flags). Retrofitting `--acp` / `--no-acp` / `--acp-port` to match the newer pattern is plausible later but out of scope here.

### Test-suite cost

Pytest runs that spawn many evals will each try to bind. AF_UNIX is cheap and discovery files self-clean via PID-liveness, but per-eval bind overhead is worth measuring in phase 1. Mitigations if it matters:

- Set `INSPECT_CTL=false` globally for the test session.
- Make the bind lazy (allocate only when something asks via discovery).

The graceful-fallback policy means worst-case is "test logs have warning lines"; eval correctness is unaffected.

## Implementation

Phased plan, with HTTP/H1 as the chosen wire:

1. **`EvalState` aggregate + read-only HTTP endpoint.** Add a lightweight `EvalState` container in the eval runner (queued / in-flight / completed counts, model usage rollup, started_at) updated at sample lifecycle transitions — per-sample state already lives in `ActiveSample` and is always-on. Bind a FastAPI server on AF_UNIX (default) with a TCP fallback flag; write the discovery file. Implement `GET /evals`, `GET /evals/<id>`, `GET /evals/<id>/samples` (summary), `GET /evals/<id>/samples/<sid>`. Loopback-only by default; no auth surface yet.
2. **`inspect ctl ls` / `inspect ctl status` CLI with `--json` from day one.** Validates discovery + read path end-to-end before adding write paths. JSON output is a first-class mode, not an afterthought — the response schema is the canonical shape and human-formatted output is a rendering of it. This phase makes the CLI usable by both human operators and shell-capable agents (Claude Code via Bash). Establishes the `inspect ctl` subcommand group (`inspect ctl --help` shows the surface from day one).
3. **`POST /evals/<id>/cancel` + `inspect ctl cancel` CLI.** First directive. Idempotent and supporting `?dry_run=true` / `--dry-run` from day one.
4. **Eval event SSE stream + cursored pull endpoint.** Push (SSE) for TUIs at `GET /evals/<id>/events`; pull (cursored JSON) for agents at `GET /evals/<id>/events?since=<cursor>`. CLI helper: `inspect ctl events <id> --since <cursor> --json`. Unlocks watchdog agents.
5. **TUI separation** — `inspect tui` as a standalone client (HTTP client of the control endpoint, plus an ACP client of the ACP socket for per-sample drill-down). Largest piece; depends on the read + event-stream surfaces being in place.
6. **Modify-limits / drain / requeue.** Bigger eval-runner changes.
7. **Eval-set scope** — server lifecycle hoisted to the parent process; eval-set-level `EvalSetState` aggregate designed from scratch (doesn't exist today); `GET /eval-sets`, `GET /eval-sets/<id>`, `POST /eval-sets/<id>/cancel`, eval-set event streams.

**Optional follow-on (only if a specific gap emerges):**

- **MCP server wrapper (`inspect mcp`).** Curated tool surface for LLM agents in hosts that can't / won't use shell access, or that need finer per-tool permissions than a Bash allowlist provides. Wraps the Python client library; reuses the JSON schemas from phases 1–4. We do NOT build this preemptively — Path A (CLI + JSON) should cover the agent integration story; this is the escape hatch if it doesn't.

Phase 1 is small enough to be a forcing function on the namespace + state-model decisions. Phases 1–4 give shell-capable agents (Claude Code via Bash) a complete read + direct + monitor surface. Phase 5 is the TUI payoff.

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

Where this doc's design touches one of those surfaces (eg. the `EvalState` model that powers `inspect ctl ls`), we describe what the control channel does and reference the broader work for the surrounding context.
