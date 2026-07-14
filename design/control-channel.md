# Control Channel

Part of a broader effort to make Inspect a first-class platform for **LLM-agent-driven eval workflows** — agents like Claude Code launching evals, monitoring them, intervening when needed, and reading results back. The control channel is one piece of that surface (live-eval observation and direction); other pieces — an inspect agent, agent-friendly `inspect eval` launching, `inspect log` for reading finished evals, CLI-wide JSON output conventions — are being developed alongside this work and are referenced in "Related work" at the bottom of the doc.

Within that scope, this doc covers the **control plane for live evals and eval-sets**: external processes (LLM agents, scripted watchdogs, TUIs, CLI commands) connecting to a running Inspect process to **observe** its state and **direct** it (cancel, modify config, drain, requeue, ...).

This is **separate from** the [`agent-acp`](acp/agent-acp.md) work, even though some plumbing overlaps. ACP is for per-sample agent conversation (sessions, prompts, cancels, updates). The control channel is for eval and eval-set management — a different shape that doesn't fit ACP's conversational vocabulary. The two coexist: the ACP server handles `session/prompt` and the existing per-sample `inspect/*` extensions (`inspect/cancel_sample`, `inspect/cancel_tool_call`, etc.); the control channel handles eval-level operations.

The rudimentary control surface that fell out of the ACP work (per-sample cancellation, socket discovery via `--acp-server`) is a useful precedent but not the foundation — the control channel deserves its own protocol choice.

> **Status (phases 1–2 shipped).** The read surface, per-sample events, and process keep-alive are implemented: the embedded FastAPI server on AF_UNIX, discovery, the `GET /tasks` / `GET /evals/<id>/samples` (with an `active_since` recency delta) / `GET /evals/<id>/sample` / `GET /evals/<id>/sample/events` read endpoints, `POST /release`, the `inspect ctl` CLI (organized into resource-noun groups — `ctl task` / `ctl sample` / `ctl config` / `ctl process`; see "CLI command hierarchy" below), and the `--ctl-server` flag (on by default; `false` disables, `keep` parks the process after the eval). **Phase 2** added the cursored-pull per-sample transcript `events` API plus the recency-delta filter on `samples`. **Phase 3** (in progress) adds the state-mutating directives — the log-flush directive (`ctl task log-flush`), the dynamic-config directive (`ctl config` — the `max_samples` / `max_sandboxes` / `max_subprocesses` / `max_connections` concurrency knobs plus the `log_buffer` / `log_shared` buffer params), and the cancel directives (`ctl task cancel` / `ctl sample cancel`) are shipped; adding a task to a running eval, then drain / requeue and the per-sample time/token/message limits follow; **phase 4** adds the push (SSE / `--follow`) shape, including the eval-wide fan-in. Much of the prose below describes the full target surface — see [Implementation](#implementation) for what's built vs planned, which is the source of truth for phasing.

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
  inspect eval my_task --model gpt-5  --log-dir ./logs/gpt5  --detach --ctl-server=keep --json
  inspect eval my_task --model claude --log-dir ./logs/opus  --detach --ctl-server=keep --json
  inspect ctl task list --json                                              # watch progress
  inspect ctl sample list <task> --active-since <ts> --json                 # poll for what changed / stalls
  inspect ctl sample cancel <task> <sample-id> <epoch> --dry-run            # check before acting
  inspect ctl sample cancel <task> <sample-id> <epoch>
  inspect ctl process release <pid>                                         # release the processes
  inspect ctl process release <pid>                                         # ...one for each
  (log summary and analysis TBD)
```

The `--ctl-server=keep` value is load-bearing for this workflow: without it, each eval process exits the instant the eval body returns, taking its discovery file and control endpoint with it. The agent's later "inspect results" / "compare" / "decide" steps would race the process teardown and intermittently find no control surface to query. With keep-alive the process parks after the eval body completes, the control endpoint stays bound, and `inspect ctl process release` is the explicit teardown signal the agent issues when it's done.

The control channel provides everything after the two launch commands (`task list`, `sample list`, `sample cancel`, `process release`); the launch commands come from the broader agent-enablement work (see Related work). For this scenario to work, every surface must be:

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

Single-purpose human-driven CLI commands, all under the `inspect ctl` subcommand and organized into resource-noun groups (see "CLI grouping" and "CLI command hierarchy" below). Phase-1 and phase-2 commands are shipped; the rest land with their phases (the directives → phase 3):

```
# reads + lifecycle (phases 1-2, shipped)
inspect ctl task list                       # list running tasks (bare `ctl task` also works)
inspect ctl sample list [TASK] [--active-since TS]  # per-sample table (status / retries / score / timing / idle)
inspect ctl sample show TASK SID [EPOCH]    # one sample's summary + error history (--traceback for full)
inspect ctl sample errors [TASK]            # triage: samples that errored or were retried
inspect ctl sample events TASK SID [EPOCH]  # one sample's transcript events (cursored pull)
                                            #   --cursor CURSOR / --tail N / --type / --full / --since-time / --until
                                            #   (-f / --follow push is phase 4)
inspect ctl process list                    # running Inspect processes (pid / keep-alive / tasks)
inspect ctl process keep [PID]              # keep a running process alive after its eval finishes
inspect ctl process release [PID]           # release a lingering keep-alive process

# directives (phase 3; first slices shipped)
inspect ctl config [TASK] [--max-samples N] [--max-connections N] [--max-sandboxes N]
                   [--max-subprocesses N] [--log-buffer N] [--log-shared S] [--model M] [--dry-run]
                                            # view / retune launch config mid-flight (shipped)
inspect ctl task log-flush [TASK]           # write a running eval's buffered samples to the log now (shipped)
inspect ctl task cancel TASK [--dry-run]    # cancel an eval — in-flight samples interrupted, log finalized (shipped)
inspect ctl sample cancel TASK SID [EPOCH] [--error] [--dry-run]  # cancel one sample (shipped)
inspect ctl task add SPEC [--model M] [-T k=v] [--dry-run]  # add a task to a running --ctl-server=keep eval
inspect ctl task drain TASK                 # stop accepting new samples; let in-flight finish
inspect ctl sample requeue TASK SID EPOCH   # re-add a failed sample to the queue
inspect ctl config TASK --time-limit N     # modify per-sample time/token/message limits (planned)
```

Note the commands take a **task** selector (task-id prefix or task name), not a raw eval-id: a task id is stable across retries, whereas a per-attempt eval id is not. Process-lifecycle commands take a `PID` (optional when a single process is running).

Each is a thin wrapper — autocomplete-friendly, scriptable, composable with shell tooling. Same operations as the TUI; same operations agents call. The CLI is the canonical surface — humans use it directly; agents use it via Bash.

#### CLI grouping: `inspect ctl`

All live-eval management commands live under a single `inspect ctl` subcommand rather than as flat top-level verbs (`inspect tasks`, `inspect cancel`, ...). The choice is deliberate:

- **Conceptual coherence.** Every command in the group operates on a running Inspect process via the control endpoint; they share infrastructure (discovery, auth, lifecycle) and a mental model. That's a real subsystem, not an arbitrary bag of verbs.
- **Namespace pressure.** Inspect's top-level CLI is already crowded (`eval`, `eval-set`, `eval-retry`, `view`, `log`, `score`, `cache`, `sandbox`, `acp`). Adding 7–8 new verbs there crowds discovery for everyone; grouping under `ctl` keeps the top level uncluttered.
- **Discoverability.** `inspect ctl --help` is the natural entry point for "what can I do with a running eval?" Both humans and agents read it once and have the whole surface.
- **Precedent.** `kubectl`, `systemctl`, `journalctl`, `etcdctl` — `ctl` reads as "control" instantly for anyone who's done ops work. The convention is established.
- **No alias.** `inspect control` does *not* exist as a long-form alias; `inspect ctl` is the only canonical form. Two names introduce documentation drift, "which is canonical?" ambiguity, and grep friction without paying for themselves.

`inspect tui` stays at the top level rather than under `ctl` — it's an *application* (like `inspect view`) that happens to be a control-channel client, not an operation on a running eval.

#### CLI command hierarchy: noun groups

> **Status: implemented** (for the shipped surface — the planned verbs land with their phases). Docs, help, and this doc use only the noun spellings; the original flat names survive as hidden, deprecation-noted aliases per the Migration section below (except `sample`, whose name is claimed by the group).

The `ctl` surface originally shipped **flat**: ten verbs, heading for ~17 once the remaining phase-3 directives, phase-4 `--follow`, and the eval-set surface landed. Two problems were already visible at ten:

- **Near-collisions that encode nothing.** `samples` vs `sample` differed by one character but took different selectors and answered different questions; `events` sounded eval-scoped but took a sample. Which commands took `TASK`, which took `TASK SAMPLE_ID [EPOCH]`, and which took `--pid` was pure memorization — the flat namespace carried no scope signal.
- **Compound verbs.** Without a noun axis, a verb that applies at two scopes needs a minted compound (`cancel` vs `cancel-sample`); `requeue`, `set-limit`, and every future two-scope directive would have repeated the problem.

The fix — implemented as the current surface — groups commands by **resource noun**, mirroring the object model the HTTP API already has (task-scoped `/tasks/<task-id>/…`, attempt-scoped `/evals/<eval-id>/…` and its sample subresources, process-scoped `/config` / `/keep` / `/release`):

```
inspect ctl
├── task                        # a logical task in a running process (stable across retries)
│   ├── list                        # was: tasks (implied: bare `ctl task` ≡ `ctl task list`)
│   ├── log-flush [TASK]            # was: flush (renamed: the object is the task's *log*)
│   ├── cancel TASK                 # shipped (abort semantics; a graceful-drain variant is future work)
│   ├── add SPEC [...]              # planned: add
│   └── drain TASK                  # planned: drain
├── sample                      # one sample (TASK SAMPLE_ID [EPOCH]) or a task's samples
│   ├── list [TASK]                 # was: samples (implied by bare `ctl sample`; no TASK = all tasks)
│   ├── show TASK SID [EPOCH]       # was: sample
│   ├── errors [TASK]               # was: errors (no TASK = across all tasks)
│   ├── events TASK SID [EPOCH]     # was: events (phase-4 --follow lands here unchanged)
│   ├── cancel TASK SID [EPOCH]     # shipped (EPOCH required when the task runs >1 epoch)
│   └── requeue TASK SID [EPOCH]    # planned: requeue
├── config [TASK] [...]         # was: limits + buffer; view/retune launch config, scope per knob
├── process                     # the running Inspect process itself (PID selector)
│   ├── list                        # new: pids / keep-alive / hosted tasks (implied by bare `ctl process`)
│   ├── keep [PID]                  # was: keep [--pid]
│   └── release [PID]               # was: release [--pid]
└── eval-set                    # later, with the eval-set surface
    └── list / show / cancel
```

In the sketch, `[]` marks an optional argument. What an omitted selector *means* differs by verb class — see "Selector conventions" below. `[EPOCH]` defaults to 1 on reads; sample *mutations* require it whenever the task runs more than one epoch (also in "Selector conventions").

**Naming rules.**

- **Singular nouns**, verb second — the `gh` / `docker` shape (`gh pr list`, `docker container ls`), not kubectl's verb-first. Singular dissolves the `samples`/`sample` near-collision: the plural form simply no longer exists.
- **The noun is the thing read or mutated; the selector follows the noun.** Every command in a group shares one selector vocabulary (`task …` takes a task selector; `sample …` takes `TASK` or `TASK SAMPLE_ID [EPOCH]`; `process …` takes `[PID]`) — the group *is* the scope signal the flat list lacks. Whether the selector may be *omitted* differs by verb class; see "Selector conventions" below. `config` is the one top-level *command* among the groups: its object is the running configuration, whose scope is per-knob rather than per-resource (see "Scope is a property of the knob" below), so it takes options rather than verbs — bare `ctl config` is the view.
- **Symmetric verbs across nouns.** `list` / `show` / `cancel` mean the same thing wherever they appear, so a consumer who has learned one group can predict the others.
- **Implied `list` on the bare noun — and only there.** `ctl task` ≡ `ctl task list`, `ctl sample` ≡ `ctl sample list` (git precedent: bare `git branch` / `git tag` / `git remote` list). This recovers the brevity the reorg costs on the hottest reads (`ctl task` is shorter than today's `ctl tasks`) without hurting discovery — `--help` is handled before the default fires, so `ctl task --help` still shows the verbs. The boundary is strict: the default **never** fires once a positional argument is present. Selectors are arbitrary strings, so `ctl sample my-task` implying `list` would make a task named `errors` or `cancel` unaddressable — and adding a new verb later would silently change the meaning of existing invocations. With the bare-only rule the failure mode is a clean "no such command" and the fix (spell `list`) is obvious. The `list` options (`--json`, `--active-since`, ...) are mirrored onto the group so `ctl task --json` works — without that, agents (who always want `--json`) would have to spell `list` anyway and the default would serve humans only. Applies to all three groups: `process list` shipped with the reorg (its sibling verbs take a `PID` selector, so pids must be enumerable in-group), so bare `ctl process` lists processes. Mild tension with the no-alias rule, accepted: this is a default, not a second name — the explicit `list` form stays canonical in docs and examples.
- **`task`, not `eval`, as the headline noun.** The CLI deliberately targets tasks (task-id prefix / task name — stable across retries; resolved open question #7), and the limits directive already settled on `/tasks/<task-id>/…` for the same reason. An `eval` noun would re-import the attempt-vs-task confusion the selectors were designed to avoid — and `inspect ctl eval` reads badly against the top-level `inspect eval`. `eval` stays an HTTP-API concept (attempt-scoped resources under `/evals/<id>/…`), resolved client-side as today.
- **No permanent aliases.** Consistent with the "no `inspect control` alias" stance above: two names for one command is documentation drift and grep friction. The flat spellings survive only as hidden, deprecation-noted, time-boxed shims (see Migration) — never as a documented second form.

**Selector conventions.**

- **Reads: the selector is a filter, and an omitted filter means unfiltered.** `ctl sample errors` with no `TASK` reports errored samples across *all* running tasks (rows carry a task column when they span tasks); same for `sample list`. This is the standard list-command shape (`gh pr list`, `kubectl get pods`): narrow by adding an argument, don't widen by adding a flag. It changed the originally-shipped reads — which errored as "ambiguous" when several tasks ran and no `TASK` was given — but the reorg was a clean break anyway, and it makes the eval-set triage question ("what's erroring anywhere in this run?") the zero-argument spelling. Output stays summary-shaped per the shape constraints, so an unscoped read over a large eval-set doesn't dump everything.
- **Mutations: an omitted selector must resolve to exactly one target.** Sole running task → it's the default (the shipped `limits` / `flush` / `buffer` behavior); several running → error with the candidate list, never fan-out. Destructive verbs (`task cancel`, `task drain`) require the selector outright. (`process keep` / `release` are *not* in that class: they're idempotent, last-write-wins lifecycle toggles whose worst case is letting an already-finished process exit with its logs written — so they get the sole-target default, and the common single-process case types no selector at all.) The rule extends to `EPOCH` on sample mutations: agents drop trailing optional positionals, and a defaulted epoch doesn't error — it *resolves to a different sample* (`sample cancel TASK SID` on an epoch-2 sample silently cancels the healthy epoch-1 attempt). So `sample cancel` / `requeue` require `EPOCH` whenever the task runs more than one epoch; reads keep the epoch-1 default but echo the resolved `{sample_id, epoch}` so a wrongly defaulted target is visible in the agent's context.
- **Scope is a property of the knob, not of the command path — `config` is top-level.** (Reshaped on review feedback from JJ.) An earlier draft nested the retune surface under the resource nouns (`task limits` / `process limits`) with a write guard so a task-shaped command couldn't mutate process-global knobs — a patch for a hazard the nesting itself created, since putting a global knob under `task` asserts a scope the knob doesn't have. Top-level `ctl config [TASK] [...]` dissolves the hazard at the root: the command makes no scope claim, so there is nothing to guard. Each knob carries its own scope — task-scoped knobs (`--max-samples`, `--log-buffer` / `--log-shared`, later `--time-limit` / `--token-limit` / `--message-limit`) follow the mutation selector rule (sole running task default; explicit `TASK` in an eval-set); process-scoped knobs (`--max-connections`, `--max-sandboxes`) take no selector and apply process-wide. Scope is reported *structurally*: the view and the mutation result envelope label every knob `"scope": "task" | "process"`, and `--dry-run` reports blast radius ("--max-connections applies process-wide — every active task in this process is affected") — fixing the flat CLI's print-only note that vanished under `--json`. Non-retunable options error as "fixed at launch". Precedent: `git config` is one command with mixed scopes resolved per setting. The unifying sentence for agents: **any `inspect eval` launch flag that can be retuned mid-flight is settable via `ctl config`, under the same spelling.** The trade accepted: an agent can no longer read a knob's blast radius off the command shape — it reads it from help / the scope labels / dry-run instead; honest-in-the-output beats misleading-in-the-path. The HTTP endpoints keep their scope-explicit split (`/tasks/<task-id>/config` and `/config`, renamed from `…/limits` on the same break) — scope-explicitness lives at the API layer; the CLI routes to it. (Keep-alive intent is technically config too — a last-write-wins boolean — but `process keep` / `release` stay verbs: release has an immediate unpark action, and the scenario-1 ergonomics are better.)
- **No fan-out mutations.** The process-wide knobs (`--max-connections` / `--max-sandboxes`) already reach every task in the process because the *knob* is process-scoped — scope is a property of the knob, not of the command. Per-task fan-out ("set `--max-samples 4` on every task") is shell composition, already the first-class agent path (Path A): `ctl task list --json | jq -r '.tasks[].task_id' | xargs -n1 -I{} inspect ctl config {} --max-samples 4`. If real demand appears, that's the moment to design a multi-target selector, against a concrete case. (An `--all` flag was considered and rejected: in `ctl sample errors --all` it's ambiguous whether it widens over tasks or samples, and it puts scope in a flag when the scope selector is positional.)
- **Parsing exception.** `TASK` is required wherever `SAMPLE_ID` follows (`sample show` / `events` / `cancel` / `requeue`): with two positionals the first can't be optional — `ctl sample show foo` couldn't tell a task from a sample id.
- **A group's own id is positional; other objects' ids are flags.** The selector path to the group's object sits right after the verb (`task cancel TASK`, `sample show TASK SID [EPOCH]`, `process release [PID]`); identifiers of *other* object kinds appear as flags that filter or disambiguate (`--model` on `config`, a possible `--pid` scope on task/sample reads). `config`'s optional positional `TASK` fits the rule rather than bending it: for its task-scoped knobs the task *is* the object being configured. The shipped `keep [--pid]` / `release [--pid]` predate this rule — the flag was a historical accident of the flat CLI, not a parsing constraint (nothing follows `PID`) — and the reorg moves the pid to the positional slot.

The read/write asymmetry — reads widen when unscoped, mutations refuse to — is deliberate, not an inconsistency: reading everything is safe; mutating everything through dropped arguments (an agent retrying in confusion) is exactly the failure mode the agent-shape constraints guard against.

**Agent output contract.** These fell out of pressure-testing the proposal by role-playing an LLM agent driving scenario 1 end-to-end (launch two evals with keep-alive, discover via `--help`, poll, diagnose a stall and an error, intervene, hand off to logs, release) and asking at every step where each selector, cursor, pid, and timestamp would come from. The structure held; the gaps were almost all in the output contract:

- **Outputs feed inputs.** Every `--json` row carries the exact identifiers other commands take as selectors: `task_id` on **every** sample row, unconditionally (today's sample-row schema has no task identity at all, and "a task column when rows span tasks" is a human-table rendering choice — presence-conditional fields break an agent's `jq` the moment rows collapse back to one task); `pid` / `socket_path` on task rows (kept even with `process list` — saves a join); `log_location` on task rows (the live→`inspect log` handoff hinge); the resolved `{sample_id, epoch}` echoed on sample reads.
- **Envelope the list reads.** `{"as_of": <ts>, "samples": [...]}` rather than a bare array, so the next `--active-since` value comes from the server. Otherwise the agent mints wall-clock timestamps itself — and mints them *after* parsing the response, silently missing anything that changed during the read. This is the pattern the events envelope already follows; the reorg's clean break is the moment to make the list reads match.
- **Cap the samples listing; keep the aggregate complete.** (Shipped as a follow-up to the reorg — issue #42.) `sample list` rows are otherwise linear in sample count: a 10k-sample eval-set is ~10k rows in one response, exactly the context bomb constraint 2 exists to prevent. The listing defaults to 100 rows per eval (`DEFAULT_SAMPLE_LIST_LIMIT`) — the head of the existing running → terminal → pending sort, so the most relevant rows survive — and the envelope becomes `{as_of, counts, samples, truncated}`: `counts` is the status histogram over *all* the eval's samples (stable keys `running` / `completed` / `error` / `cancelled` / `pending` / `queued`, always present, computed before the `active_since` / `status` filters and the cap, so the aggregate answer stays complete), and `truncated: true` marks a capped response structurally — no silent truncation (the human table prints a `listing capped` footer). `--limit N` / `--all` adjust the cap, `--status` filters rows (never `counts`); `--all` with `--limit` errors rather than picking silently. `sample errors` and `sample show`'s row lookup explicitly request the full listing (`all=true`): a default-capped read would silently hide errors from triage or drop the target row (`sample errors` also sends `filter=errors`, so "full" means every errored/retried row, not the whole grid). Version skew around the cap is handled asymmetrically, by explicit decision. New CLI → old server: the old endpoint ignores the `status`/`limit`/`all` params and returns a histogram-less envelope, so the CLI derives `counts` from the rows and applies the filter and cap client-side — the flags' contract holds (with one unavoidable gap: on an `active_since` delta poll only the delta's rows exist to count, so the derived histogram covers the delta, not the whole eval). Old CLI (≤ 0.3.245) → new server: the default cap applies to a client that doesn't understand `counts`/`truncated`, so its listing is silently capped at 100 rows and its errors view — which filters client-side without requesting `all=true` — can miss errors past the cap. Accepted: the cap has to be enforced at the endpoint (the source) or every consumer that omits it re-opens the unbounded read constraint 2 exists to prevent — making it opt-in and relying on each client to send its own cap would trade a permanent guarantee for a transient, one-direction skew window. The supported pairing is matched CLI/server versions (upgrading only the CLI is always safe).
- **`--json` on every verb, mutations included.** The shape constraints cover reads; the shipped `keep` / `release` print prose. Agents branch on directive results — applied vs already-in-that-state (the idempotent no-op) vs dry-run-would-do — and parsing prose is exactly what the JSON-first rule exists to prevent. One uniform result envelope for all mutations (e.g. `{"target": ..., "applied": bool, "dry_run": bool, "detail": ...}`) so a schema learned once covers every group.
- **Structure the error path too** (issue #44, from PR #35 feedback). The success envelopes alone still left failures as stderr prose or a raw traceback — sending agents straight back to string-scraping (the launch-and-babysit skill was regexing httpx exception types out of traceback text to tell starvation from rate-limiting). On a `--json` invocation any terminal failure emits `{"error": {kind, exception, message, status}}` on stdout, all four fields always present; the exit code stays non-zero (click-level usage errors — unknown option, missing argument — fire before the command callback and still exit 2 with no envelope, distinguishable by that exit code), the stderr prose stays as narration, and human (non-`--json`) output is untouched. `kind` is the branch field, a small closed vocabulary: `busy` (retry-exhausted timeouts — alive but starved, retry shortly; distinct from the single-shot `connect_timeout` / `read_timeout`), `connect_error` (refused/reset — the process is likely gone), `not_found` / `ambiguous` (selector resolution; HTTP 404 also maps to `not_found` with `status`), `http_error` (other non-2xx, `status` carries the code), `invalid_request` (client-side argument/target errors and server 400s), `invalid_response` (undecodable body), and `internal` (unexpected exception — its traceback stays on stderr). `exception` carries the package-qualified class (`httpx.ReadTimeout`) for whatever `kind` is too coarse for, and `message` is self-contained — the ambiguity error folds its candidate ids in, since the candidate table is stderr-only rendering. Implementation-wise every terminal error site raises one structured failure type under the shared transport/error policy, so the shape can't drift per command.
- **Document the terminal predicate.** "Is it finished?" has three candidate signals (`status`, `completed_at`, `completed == total`) and no stated canonical one; an agent will pick `completed == total`, which is wrong for a cancelled or errored eval. Canonical: terminal ⇔ `completed_at != null`; the `status` enum belongs in `task list --help`.
- **`sample events` never serves an empty first page.** The unseeded default is a recent tail (e.g. the last 20 events), stated in `--help` ("first call returns the recent tail; resume with `--cursor`"). "Start from now" returns `{events: [], done: false}` forever on exactly the sample an agent is diagnosing — a stalled one — and an empty page reads as "transcript broken", not "pass `--tail`".
- **Rename the cursor flag `--since` → `--cursor`.** The `--since` (opaque cursor) / `--since-time` (timestamp) pair is precisely the near-collision this reorg exists to dissolve; "since" reads temporally, and an agent will pass `--since $(date +%s)`. A non-decodable cursor should still error helpfully: "this looks like a timestamp — did you mean `--since-time`?".
- **Teach through the error.** `ctl sample my-task` fails (the bare-noun default never fires past a positional — correct), but click's stock "No such command 'my-task'" reads as "the group doesn't do this". A group-level unknown-command handler answers instead: "No such command 'my-task'. To list a task's samples: `inspect ctl sample list my-task`." The analogy that causes the mistake is one the surface itself teaches, so it will recur; the error message is where to correct it.
- **Busy is not absent.** The control server shares the eval's event loop, so a busy eval can miss reads entirely; the sample commands degrade rather than die (warn-and-skip a process whose reads stay busy through the retries), but every terminal outcome must stay honest: if the skips leave *no* tasks visible, exit 1 with a stderr note ("No tasks visible: pid N busy — try again shortly.") and, on `--json`, the `kind: "busy"` *error* envelope rather than an empty success envelope — which, with exit 0, would be a false "nothing running" claim; a not-found selector error and the ambiguity candidate table are qualified with the busy pids (the target or further candidates may live on the skipped process); and a successful match looser than an exact id or a truncated-display-length id prefix carries a stderr caveat that it matched among responsive processes only (same-named tasks across processes are the norm and a short hand-typed prefix could collide, where the pasted truncated id can't name a different task and stays quiet). A sole discovered server rides the full retry budget — the degraded budget protects a fan-out from an unrelated wedged sibling, and a single server is no fan-out. An exact full-`task_id` selector short-circuits the summaries fan-out at the server that holds it — ids are unique and an exact match wins resolution outright, so the uncontacted servers could neither add candidates nor create ambiguity (prefix and name selectors still see every server to detect it); probing is newest-first, so a steady-state `sample events --cursor` poll against the page's echoed `task_id` skips the retry budgets of busy siblings started before the target (those started after are still contacted). A polling agent should treat the exit-1/empty-stdout outcome as "retry shortly", not "no evals".
- **`sample show` grows into its verb.** The shipped `ctl sample` is error detail only; an agent calling `show` expects the sample's summary. Expand it to status / timing / token usage / score / error history, pairing with `events` as summary-vs-transcript drill-down — the same summary-then-detail shape the constraints already mandate.
- **Name-selector ambiguity in the headline scenario.** One task × two models means `my_task` matches both rows from the first command, so every name attempt costs an ambiguity-error turn and the agent falls back to opaque `task_id`s (workable — they're in `task list --json`). A `--model` disambiguator on task-selecting commands (the matching rule already exists on the shipped `limits --model`, carried into `config`) is a cheap fix; lower priority.
- **The launch handoff is load-bearing.** Right after launch, `task list` returning `[]` is indistinguishable from a failed launch (the socket may not be bound yet); without the planned agent-friendly `inspect eval --json` output (run_id / log path / control address — see Related work) the agent must invent a sleep-and-retry loop. Not a ctl-surface item, but the workflow's first step depends on it. **Shipped (minimal slice):** `inspect eval --json` (implies `--display none` so stdout stays parseable) emits a `launch` JSON line — `run_id` / `pid` / `log_dir` / `control.socket_path` — only after the control server is bound, with `control: null` when the surface is definitively absent (disabled or bind failed), plus a `done` line with per-task log locations and statuses on exit. The contract: a seen `launch` line with non-null `control` guarantees the surface exists; a process that exits without one failed before the control server came up. Stdout carries these records exclusively — the eval runs with stdout redirected to stderr at the file-descriptor level, so bare `print`s inside the run (scan status, task/solver code) and subprocesses spawned without capturing output surface as stderr diagnostics instead of corrupting the stream — and pre-flight failures (`PrerequisiteError`: bad task path, missing API key, ...) are re-rendered to stderr rather than swallowed by the quiet `--display none` console, so a launch that dies before `launch` still says why. `inspect eval-set --json` carries the identical contract with three eval-set wrinkles: the records also report `eval_set_id` (the launch record carries it on plain `eval` too, as `null`), the `done` record adds overall `success` (mirroring the exit code), and two documented deviations from "exactly one `launch` then one `done`" — a set whose tasks are all already complete runs no eval (stdout is just the `done` record; agents must not read a missing `launch` line as a failed launch once `done` arrived), and the legacy `--no-retry-immediate` mode emits a fresh `launch` record per batch-retry bind (the `done` record then carries the *last* launch's `run_id` — the run that produced the final state). Not yet covered: the keep-alive park after an all-reused eval-set binds a control server without emitting a `launch` record (discoverable via the ordinary `inspect ctl` discovery files, and the reused logs are registered so `ctl task list` shows them).

Known accepted edge in the busy handling: the sole-server rule counts *discovered* servers, so a sibling that is discovered but instantly unreachable (version-skewed `/tasks`, exited after discovery) demotes the one live server to the degraded budget. The failure is honest and actionable ("pid N busy — try again shortly"), and closing it needs an escalation re-read whose complexity isn't warranted — the durable fix is server-side (answer reads off the eval loop — issue #48).

**Mapping (flat → noun), as implemented.** The "original" column is what shipped before the reorganization and survives as the hidden aliases; "status" is each command's state at the time of the reorg.

| Original (flat) | Status | Current | Notes |
|---|---|---|---|
| `ctl tasks` | shipped | `ctl task list` | keep-alive footer unchanged |
| `ctl samples [TASK]` | shipped | `ctl sample list [TASK]` | keeps `--active-since`; no `TASK` now spans all tasks (was: sole task, or error) |
| `ctl sample TASK SID [EPOCH]` | shipped | `ctl sample show TASK SID [EPOCH]` | `show` frees `sample` to be the group; scope grows from error detail to a full sample summary (see agent output contract) |
| `ctl errors [TASK]` | shipped | `ctl sample errors [TASK]` | output is sample rows → sample group; no `TASK` now spans all tasks. Alt: fold into `sample list --errors` |
| `ctl events TASK SID [EPOCH]` | shipped | `ctl sample events TASK SID [EPOCH]` | cursor flag renamed `--since` → `--cursor`; other flags unchanged; phase-4 `-f/--follow` lands here |
| `ctl flush [TASK]` | shipped | `ctl task log-flush [TASK]` | renamed: the object is the task's *log* — bare `flush` under a task noun misreads ("flush the task"?). Acts on the live attempt's recorder, but task keying already fits (see "task-keyed read aliases") |
| `ctl buffer [TASK] [...]` | shipped | absorbed into `ctl config` | `--log-buffer` / `--log-shared` are launch flags being retuned — that's exactly what `config` is |
| `ctl limits [TASK] [...]` | shipped | `ctl config [TASK] [...]` | top-level, not nested under a resource noun; scope is per-knob and labeled in output — see "Scope is a property of the knob" |
| `ctl keep [--pid]` | shipped | `ctl process keep [PID]` | pid becomes an optional positional; defaults to the sole running process |
| `ctl release [--pid]` | shipped | `ctl process release [PID]` | same |
| `ctl add SPEC [...]` | planned | `ctl task add SPEC [...]` | |
| `ctl cancel <id> [--force]` | **shipped** (as noun form only) | `ctl task cancel TASK` | selector settles on task, per the limits precedent; shipped with abort semantics — see "Cancel a task / a sample" |
| `ctl drain <id>` | planned | `ctl task drain TASK` | |
| `ctl cancel-sample <id> <sid>` | **shipped** (as noun form only) | `ctl sample cancel TASK SID [EPOCH]` | compound verb dissolves; `EPOCH` required when the task runs >1 epoch |
| `ctl requeue <id> <sid>` | planned | `ctl sample requeue TASK SID [EPOCH]` | `EPOCH` required when the task runs >1 epoch |
| `ctl set-limit <id> --time N` | planned | fold into `ctl config TASK --time-limit/--token-limit/--message-limit` | all retunable launch flags in one surface, same spellings as `inspect eval`; task-scoped knobs, so `TASK` follows the mutation selector rule |
| — | new | `ctl process list` | pids, keep-alive status, hosted task_ids; shipped with the reorg — the group's other verbs take a `PID` selector, so pids must be enumerable in-group |
| — | later | `ctl eval-set list / show / cancel` | group slot ready-made |

The hierarchy also leaves natural slots that the flat namespace couldn't have expressed without more minted names: `task show TASK` (single-task detail, if `task list` ever grows past a screen), for example.

**What this buys (and costs).**

For the agent-discoverability goal, the win is *structured* help, not shorter help: `inspect ctl --help` shows three groups plus `config`; `inspect ctl sample --help` shows six verbs sharing one selector shape. An agent learns the object model from the shape of the tree rather than from reading seventeen one-line summaries and inferring scopes. Verb symmetry means it can predict `sample cancel` after seeing `task cancel`. (Bash-allowlist granularity is unchanged either way — prefix rules like `inspect ctl task cancel*` work in both layouts, and read-vs-write doesn't align with nouns in either.)

Costs, honestly stated: the hot reads get one word longer (`ctl tasks` → `ctl task list`); discovery takes two help invocations instead of one; and it renames a shipped surface. On raw count alone the flat list would survive — seventeen one-liners still fit a help screen — so the case rests on the scope signal and the dissolved near-collisions/compounds, which are real at ten commands already.

**Migration (implemented).** The reorg landed immediately rather than waiting: the `ctl` surface was weeks old and pre-announcement, phase 3 was mid-flight (so half the planned verbs would otherwise have shipped flat and then moved), and every release the flat names survived as the canonical form would have raised the cost of the rename. The noun surface is canonical from day one — help, docs, and this doc's examples show only the new spellings. The old flat commands remain as **hidden aliases** (click `hidden=True`) for a transition window, with three deliberate properties:

- **Except `sample`, which breaks immediately** — the name is claimed by the group, so the old `ctl sample TASK SID [EPOCH]` invocation can't coexist with `ctl sample <verb>`. A fallback ("first token not a known verb → treat as the old form") is rejected for the same reason the implied-`list` default never fires past a positional: selector capture, and verbs added later silently changing the meaning of old invocations. Ironically the command that motivated the reorg (the `samples`/`sample` near-collision) is the one that must break at once; its error message should point at `sample show`. The other nine flat commands (`tasks`, `samples`, `errors`, `events`, `keep`, `release`, `flush`, `buffer`, `limits`) collide with nothing and alias cleanly.
- **Aliases preserve spellings, not output.** Each alias is a thin delegation to the new implementation — new behavior (unscoped reads widen), new JSON (the `{as_of, ...}` envelopes, unconditional `task_id`, `--since` → `--cursor`). A script parsing the old bare-array output breaks even through the alias; preserving the old shapes would mean maintaining two surfaces in lockstep, which is exactly the drift cost the no-alias principle exists to avoid. The aliases buy muscle-memory continuity for humans and command-spelling continuity for scripts — no more, and that's stated up front.
- **Deprecation-noted and time-boxed.** Each alias prints a one-line pointer to **stderr** (stderr so `--json` stdout stays parseable) — e.g. "`inspect ctl tasks` is now `inspect ctl task list`" — and is removed after a stated window (say two releases). Hidden means agents reading `--help` never discover the old names, so new consumers learn only the new surface; the stderr note teaches old consumers the new spelling on every use.

The agent-output-contract items that break shipped `--json` shapes ride the same release — one migration, not two.

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

**What was missing (the gap this work fills).** Everything ACP provides is *per-sample*; before the control channel there was nothing at the eval or eval-set layer. Operations like "cancel the eval", "list eval-set state", "modify the eval's per-sample limit" didn't exist. Discovery was per-eval. The TUI ran in-process. CLI surface was limited to `inspect acp [--stdio]` (the editor bridge). Phases 1–2 (shipped) now provide the eval-level **read** layer (`inspect ctl task list` / `sample list` / `sample show` / `sample errors` / `sample events`, the `control/` discovery dir, eval-level `EvalState`, and the cursored per-sample transcript `events` pull); the eval-level **direct** operations and eval-set-level surface remain future work (phases 3 / later).

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
- Eval-level lifecycle (sample queued / started / finished / errored, eval finished) is **not** a stream — current state is served by the reads (`task list` / `sample list`), with a recency delta on the samples read. An *ordered* lifecycle transition log is a later audit/TUI item.
- Eval-set-level lifecycle (child eval starting / finished, eval-set finished): same — served by eval-set reads (later), not a dedicated stream.

### Shape constraints from agent consumers

Four constraints fall out of supporting LLM-driven agents (see "Programmatic / agent consumers" below) that don't apply to TUIs / human CLI:

1. **Every read operation needs a structured (JSON) output form.** Agents parse JSON reliably; agents parse human-formatted tables poorly. CLI commands ship `--json` as a first-class output mode, not an afterthought. The JSON schema is the canonical shape — human-formatted output is a rendering of it. Same shape serves shell-pipeline users (`inspect ctl task list --json | jq ...`) and LLM agents.
2. **Read operations should return summaries by default, with drill-down for detail.** Returning a 200-sample status dump as JSON eats LLM context. The `list samples` shape should default to a summary (status histogram + the N most-recent / longest-running) with a separate `get_sample(id)` for the full picture. Humans paginate / `jq`; agents need the shape to be agent-shaped at the source.
3. **Events need both push and pull access.** TUIs want push (SSE notification, immediate render). LLM agents want pull (cursored read: "events for eval X since cursor Y") — their runtimes are request/response loops, not subscription loops. The control channel should expose both shapes regardless of which the underlying transport favours; the push shape is the natural one for the wire protocol, the pull shape is a thin server-side buffer + cursor on top.
4. **Directives should be idempotent and support dry-run.** Agents retry, get confused, and operate on stale state. `requeue_sample` called twice must not double-queue. `cancel_eval` on an already-cancelled eval must return cleanly. Destructive directives should accept a `dry_run` flag that returns "would do X" without doing it, so agents can reason before acting.

## Architecture

The control channel runs as an **HTTP server embedded directly in the eval process** (FastAPI + uvicorn), exposing read, direct, and event-subscription operations. The eval process binds its own server distinct from `inspect view`'s server; the two run independently (see "Alternatives considered" below for why we're not folding them together yet).

### Why HTTP

- **Excellent CLI ergonomics.** `inspect ctl task cancel <task>` is one `httpx` call; shell users can hit endpoints directly with `curl`. Pipe composition works (`inspect ctl task list --json | jq ... | xargs inspect ctl task cancel`). Easy to write small monitoring scripts in any language.
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

The URL scheme has one rule — **three scopes, three roots**: process-scoped operations live at the root (`/config`, `/keep`, `/release` — the bound socket already identifies the process), task-scoped ones under `/tasks/<task-id>/…` (plus the folded task list at `GET /tasks`; task ids are stable across retries), attempt-scoped ones under `/evals/<eval-id>/…` (a specific attempt's samples / events — they belong to that attempt's log). This mirrors the CLI's noun groups: `ctl task` / `ctl config` / `ctl process` compose task- and process-rooted URLs; `ctl sample` resolves its task selector to the latest attempt and reads the attempt-rooted ones.

| Operation | Endpoint | Phase |
|---|---|---|
| List tasks (attempts folded per task) | `GET /tasks` | 1 ✅ |
| List samples (running + completed + pending) | `GET /evals/<id>/samples` | 1 ✅ |
| Sample summary + error detail | `GET /evals/<id>/sample?sample_id=<sid>&epoch=<n>` | 1 ✅ |
| Release a `--ctl-server=keep` park | `POST /release` | 1 ✅ |
| Set keep-alive on a running process | `POST /keep` | 1 ✅ |
| Samples changed since (recency delta) | `GET /evals/<id>/samples?active_since=<ts>` | 2 ✅ |
| Errored/retried samples only (skips pending-row synthesis) | `GET /evals/<id>/samples?filter=errors` (`filter` is an extensible enum; unrecognized values are rejected with 422) | 2 ✅ |
| Sample transcript events (pull) | `GET /evals/<id>/sample/events?sample_id=<sid>&epoch=<n>&since=<cursor>` (JSON) | 2 ✅ |
| Sample transcript events (push) | the pull URL with `Accept: text/event-stream` (SSE) | 4 |
| Eval-wide transcript fan-in (push only) | `GET /evals/<id>/samples/events` (SSE) | 4 |
| Flush buffered samples to the log | `POST /tasks/<task-id>/log-flush` | 3 ✅ |
| Read / modify retunable config (concurrency limits, buffer params) | `GET`+`PATCH /config` (process) and `/tasks/<task-id>/config` (task) | 3 ✅ (max-samples / max-sandboxes / max-subprocesses / max-connections / named `concurrency()` keys via `--key` / log-buffer / log-shared) |
| Add a task to a running eval | `POST /tasks` (task spec → new sibling eval under this run) | 3 |
| Cancel task | `POST /tasks/<task-id>/cancel` | 3 ✅ |
| Cancel sample | `POST /evals/<id>/sample/cancel?sample_id=<sid>&epoch=<n>&action=score\|error` | 3 ✅ |
| Drain | `POST /tasks/<task-id>/drain` | 3 |
| Requeue sample | `POST /evals/<id>/sample/requeue?sample_id=<sid>&epoch=<n>` | 3 |
| Modify per-sample limits (time / token / message) | `PATCH /tasks/<task-id>/config` (as further config knobs) | 3 |
| List eval-sets | `GET /eval-sets` | later |
| Eval-set status | `GET /eval-sets/<id>` | later |
| Cancel eval-set | `POST /eval-sets/<id>/cancel` | later |

Notes on the built shape vs the original plan:

- **Eval status detail** was folded into `GET /tasks` rather than a separate per-eval status endpoint — the list is already per-task (folded across retry attempts) and small, so the CLI fetches it and resolves a target client-side. (Shipped as `GET /evals`; renamed to `/tasks` alongside the CLI noun reorg, since the rows' identity is `task_id`.)
- **Planned directives are keyed to match their CLI verbs**: `task cancel` / `task drain` / `task add` compose task-rooted URLs (a task-keyed handle never dangles across a retry — the `config` precedent), the per-sample limits ride `PATCH /tasks/<task-id>/config` as ordinary knobs, and `sample requeue` uses the query-param sample addressing below — **never** a `/samples/<sid>/` path segment.
- **Sample detail** is keyed by `(sample_id, epoch)` (epochs make that the real identity) and is scoped to **summary + error** detail (the listing's summary fields plus current error + `error_retries`) rather than a full sample dump. `sample_id` is a **query parameter**, not a path segment: sample ids are arbitrary strings and may contain `/`, `?`, `#`, etc., which a path segment can't carry — a query param is URL-encoded end to end.
- **`POST /release`** and **`POST /keep`** are process-scoped (no eval id) — they release / set the keep-alive park for the whole process. `keep` is the inverse of `release`: it latches keep-alive on a process launched without it, so the process parks (and stays inspectable) after its eval finishes.

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

**Eval-*level* monitoring does not need its own event stream.** Current state — which samples are running / done / errored, what's stalled (`last_activity_at`), retry history, whether the eval finished — is already a poll of the phase-1 reads (`task list`, `sample list`, `sample errors` / `sample show`). The only thing a poll lacks is a cheap *delta*, which a recency filter on `samples` supplies (`?active_since=<ts>` — "samples started or updated since T"; see Phase 2). An *ordered* eval-level transition log (every intermediate state, in order) is an audit / replay / TUI need, not an agent-monitoring one — deferred to [later](#later-beyond-phase-4).

Both coexist with the per-sample ACP subscriptions — a TUI might use ACP for conversational interaction with one sample AND the control channel for eval-level lifecycle; a watchdog agent might use only cursored lifecycle pull and never touch ACP.

### Programmatic / agent consumers

Three exposure paths an external agent (Claude Code, scripted watchdog, custom agent runtime) might use. **Path A is the primary integration story; Path C is a deliberate "only if needed" follow-on.**

**Path A: CLI subprocess with `--json` output (primary).** Any agent that can run shell commands uses `inspect ctl task list --json`, `inspect ctl sample list <task> --json`, `inspect ctl task cancel <task>`, `inspect ctl sample events <task> <sid> --cursor <cursor> --json` directly. Works with Claude Code's Bash tool, with shell scripts, with any subprocess-capable runtime.

Modern LLMs are demonstrably excellent at:
- Reading `inspect ctl --help` and discovering subcommands.
- Parsing JSON output and composing follow-up calls.
- Pipe composition (`inspect ctl task list --json | jq '.tasks[] | select(.status=="stuck") | .task_id' | xargs -I{} inspect ctl task cancel {}`).

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
| Server-side cursor state | `--cursor <cursor>` from the last event the agent saw, or a `~/.config/inspect/cursors/` file. |
| Per-tool permissions | Claude Code's Bash allowlist (`inspect ctl task cancel*` vs `inspect ctl task list`) covers most of the granularity gap. |
| Tool discovery | `inspect ctl --help` is enumerable; agents read it natively. |

Costs of building / maintaining an MCP wrapper, on the other hand, are real: extra process to spawn / configure / debug, second surface to keep in lockstep with the CLI, two vocabularies (`inspect_list_evals` vs `inspect ctl task list`) for the same operations, failure modes invisible to the user.

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

The directory and socket modes are applied via `chmod` on every server start (idempotent), so a directory created before the hardening landed gets locked down on the next bind. The discovery JSON is handled differently: it's created owner-only at `open()` time (the mode is passed to `os.open`, capped by the umask) and published with an atomic temp-write-then-rename, so it is never *momentarily* more permissive than 0600 (no post-write `chmod` window) and a concurrent `inspect ctl task list` reader never observes a torn / partial-JSON file. Some filesystems ignore Unix permissions (FUSE, certain network mounts); the fallback is benign — everything still lives under `inspect_data_dir`, which is user-scoped, so the loss of defence-in-depth is bounded.

**What this buys us.** With the directory at 0700, an attempted connection from another user's process fails at the directory-traversal step (`EACCES`) before the socket file's own permissions are even consulted. The socket and JSON 0600 modes are belt-and-suspenders: they protect against a misconfigured umask, a future code path that lowers the directory perms, or a user running Inspect under different identities (sudo etc.) that accidentally widen perms.

**What this does NOT buy us:**

- **Same user, different process.** Filesystem perms can't distinguish "your Inspect eval" from "an untrusted script you ran as yourself" — both run with your UID. To enforce "only the launching eval can be controlled" would require an application-layer secret (cookie, capability token). Not in scope for v1 — trust model matches every other user-local IPC (D-Bus session bus, X11 socket, ssh-agent).
- **Sandboxed self-targeting.** Today sandboxes don't see the host data dir, so an LLM agent inside an eval can't reach the control channel. If a future scenario mounts the host data dir into a sandbox (eg. a meta-eval that watches other evals), that protection vanishes and we need a server-side "no self-targeting" guard (open question #8).
- **Filesystems that ignore Unix permissions.** Some FUSE / network filesystems don't enforce perms correctly. If a user places `inspect_data_dir` on such a filesystem, all bets are off — but that's also true of their ssh-agent socket, browser cookies, etc.

**Future hardening (when write endpoints land):**

- **SO_PEERCRED / `LOCAL_PEERCRED` UID check.** When the destructive directives arrive (phase 3+ — `POST /tasks/<task-id>/cancel` / `drain`, sample requeue), the server should verify the connecting process's UID matches our own and reject otherwise. Redundant with filesystem perms in the normal case, but cheap defence-in-depth.
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

### Process keep-alive: `--ctl-server=keep` on `inspect eval` / `inspect eval-set`

Without help from the process lifecycle, LLM-agent workflows have a race condition: the eval process exits the instant the eval body returns, taking its control endpoint and discovery file with it. The agent's next step — read results, compare, decide what to do next — runs against a vanished surface. With many agents this manifests intermittently (sometimes the agent gets to `ctl task list` before teardown, sometimes not) and degrades trust in the surface.

The fix is an explicit handoff: `--ctl-server=keep` parks the process after the eval body completes, and `inspect ctl process release` is the signal the agent issues when it's done. (Keep-alive is a *value* of the `--ctl-server` flag rather than a flag of its own because it presupposes the server — a parked process with no control endpoint could never be released. See "Flags" below.)

Keep-alive can also be set **at runtime** on an already-running process via `inspect ctl process keep` (`POST /keep`) — the inverse of `release`. This covers the "I launched it normally, but now I want to inspect it after it finishes" case without relaunching. Both the launch flag and the runtime commands feed one **process-global keep-alive intent**: the launch path sets it before the control server binds; `POST /keep` (on) and `POST /release` (off) toggle it any time before the eval finishes; both parks gate on it (so a runtime request is honoured), and the `GET /tasks` summaries report its live value so `inspect ctl task list` / `ctl process list` show the current keep-alive status (`on` / `off` / `mixed` across processes). The intent is **last-write-wins** — keep → release → keep while the eval is still running leaves the process in the keep state — rather than "release is sticky"; the park re-checks the intent on every keep/release, so a keep that follows a release re-arms the park. The intent resets at the outermost run boundary, and for an eval-set the *eval-set* owns it — it sets the intent before its inner `eval()` binds the run's server, so that server reports keep-alive and the inner `eval()` doesn't reset it (its standalone reset is gated on `eval_set_id is None`).

**What the value does.**

- `inspect eval <task> --ctl-server=keep` — after the eval body returns (including scoring + log write), the process blocks on the control endpoint's shutdown event. The control server stays bound. `inspect ctl task list` continues to show the eval (with `samples.completed == total` and a final status), and the log files are present at their final paths. `POST /release` (issued by `inspect ctl process release` or any HTTP client) releases the block; the process tears down its server and exits.
- `inspect eval-set <tasks> --ctl-server=keep` — same. With `retry_immediate=True` (the default), eval-set makes exactly one `eval()` call; per-task retries happen inside that one call, so the control server and the keep-alive park both live in the same single async context.

**Why this isn't always-on.** Most invocations don't need it; the cost is "process doesn't exit on its own." For batch / CI workflows that explicitly want the process to die when done, no keep-alive is correct. The park is opt-in (the *server* is on by default; only the park needs asking for).

### Server lifecycle aligned with `eval()` (and why no threads)

The control server runs on the eval's own anyio loop — same as the existing `task_display().run_task_app(...)` async boundary — with no daemon threads, no cross-loop synchronisation, and no per-thread state. Each binding is one `async with control_server(...)` on a single loop; where a second binding is needed (the eval-set keep-alive park) it's a *sequential* `anyio.run`, never a concurrent second loop. This keeps the control-channel code aligned with the rest of the (anyio-native, single-loop) codebase.

This works because in the common case `eval_set` is *also* a single `eval()` call:

- **`retry_immediate=True` (the default).** Eval-set invokes `eval()` exactly once. Per-task retries happen *inside* that single `eval()` call (via `task_retry_attempts` and the failed-sample-reuse path), so one control server bound for the duration of that `eval()` wraps the entire eval-set's actual work. Keep-alive then parks in a separate, sequential step *after* the display closes (a fresh control server over the same registry — see the Implementation sketch), rather than inside the run's server. Identical effective behaviour to a "threaded eval-set-scoped server" but without any threads.
- **`retry_immediate=False` (legacy batch-retry mode).** Eval-set invokes `eval()` repeatedly via tenacity. Each attempt is its own `eval()` call → its own `anyio.run` → its own control server. Between attempts the server is briefly torn down (`inspect ctl task list` returns "no running evals" for that window). This is a documented limitation of the legacy mode.

**`--ctl-server=keep` is incompatible with `retry_immediate=False`.** The post-retry-loop park would need its own async context outside any single `eval()`, which is exactly the multi-loop bridging problem the alignment chooses to avoid. Eval-set raises `PrerequisiteError` at startup if both are set, with a message pointing at `--retry-immediate` (or dropping the `keep` value).

**Implementation sketch.**

- **Loop-native park condition.** `ControlServer` holds a `_park_cond: anyio.Condition` (not a `threading.Event`). `wait_for_shutdown_async(server)` delegates to `server.wait_for_release()`, which parks while the module-level keep-alive intent holds and re-checks it whenever `POST /release` wakes it via `notify_park_change()`. Only `/release` notifies — the park exits on a transition to *off*, so `/keep` (which sets the intent *on*) has nothing to wake; it just leaves the intent on for the park to honour. A condition rather than a one-shot `anyio.Event` because the intent is **last-write-wins**: a one-shot event, once set by a release, could not be re-armed, so a keep that followed a release would be ignored. Both the routes and the waiter run on the same eval loop, so no thread or cross-loop bridge is needed. The intent **latches process-wide** (a module-level flag reset at the outermost run boundary), so the eval-set park — whose fresh server has its own fresh condition — still sees a keep/release received by the run's server. (An earlier design parked on a `threading.Event` via `anyio.to_thread.run_sync`; that left an abandoned non-daemon worker thread blocked on `Event.wait()` after a Ctrl-C, which is why the loop-native primitive replaced it.)
- **Registry lifecycle: register on start, clear at the run boundary.** `task_run.py` *always* `register_eval`s a task and never unregisters it per-task — so a completed eval stays visible to `ctl task list` for the rest of the run (including any keep-alive park) without a special "keep-alive active" flag. `clear_all_eval_states()` is called once at the outermost run boundary: `_eval_async_inner`'s `finally` when `eval_set_id is None` (standalone eval), or `eval_set`'s `finally` (eval-set). This replaced the earlier `keep_alive_active()` flag + per-task `unregister_eval` + `keep_alive_session` helper, which were removed.
- **Standalone eval parks inline.** `_eval_async_inner` opens `control_server(...)` + `acp_server(...)`, runs the eval body, then — still inside those contexts — prints the keep-alive notice and `await wait_for_shutdown_async(server)` when `ctl_server="keep"`. One control server, parked while it's still bound.
- **Eval-set parks *after* the task display closes.** Eval-set runs its single inner `eval()` (which binds its own control server for the duration of the run, with `eval_set_id` set so that `eval()` does **not** park or clear). After the display tears down and the console summary prints, `eval_set` calls `run_coroutine(_keep_alive_park(eval_set_id))`: a fresh `control_server` is bound on a new loop and parked on its shutdown event. Two sequential server bindings (one during the run, one during the park), both serving the **same** process-global `EvalState` registry — so the surface is continuous across the brief gap while the summary prints. (Doing the park *after* the display closes is deliberate: otherwise the "keeping alive" notice lands inside the live task-display pane instead of the console.) The all-reused short-circuit — every task satisfied by a prior successful log, so `eval()` is never called — reaches the same `_keep_alive_park` with the reused logs already in the registry, so the parked surface looks identical.

**Failure modes worth naming.**

- **Forgotten release.** Agent crashes / loses track of the pid. The process lingers indefinitely. Mitigation: a future idle timeout on the park could auto-shutdown after N minutes. Not in v1.
- **Multiple lingering processes.** Several agents each run their own keep-alive eval. `inspect ctl process release` with no args errors and lists pids; the agent disambiguates by passing the `PID`.
- **External kill.** Operator kills the process while keep-alive is active. The discovery file is left behind; the next `prepare_discovery_dir` sweep picks it up and removes it (pid-liveness check fails).
- **`retry_immediate=False` + keep-alive.** Rejected at startup with a clear error rather than silently giving a broken keep-alive experience.

### Server lifecycle: default on, opt-out

The control endpoint is bound by default whenever `inspect eval` runs. Every running eval benefits from being controllable, and the agent-enablement story falls apart if agents or TUIs can't discover evals launched without a special flag (per-launch opt-in defeats the whole "Claude Code uses Inspect by default" framing).

**Graceful degradation on bind failure.** If the AF_UNIX bind fails (read-only filesystem, restricted sandbox, permissions on `inspect_data_dir`), log a warning and continue without the surface. The eval runs normally; only the control surface is missing. Bind failures are *never* fatal — eval results don't depend on the control channel coming up.

This also covers *partial* startup failures. `start()` binds the socket and launches the server task *before* writing the discovery file, so a later-stage failure (eg. the discovery write) would otherwise leave a running server task and a live socket node behind. The startup path tears that partial state down (the same teardown used on normal shutdown) before degrading to "no surface", so a failed start never leaks a server or socket.

### Version skew: a control-API version integer, gated pre-flight

`inspect ctl` talks to live eval processes that embed whatever inspect version they were launched with. Because the CLI and the server both run locally from the same install, only **one skew direction is expected**: a long-running eval keeps executing the code it was launched with while the install is upgraded underneath it, leaving a **newer CLI pointed at an older server** — rare, but a real workflow (e.g. upgrading precisely to get a new knob for an already-running eval). The reverse — an older CLI against a newer server — would require downgrading the install while an eval runs, and is not a scenario this design supports or defends against; everything below targets the newer-CLI-vs-older-server case. An older server's PATCH handlers silently ignore unknown query params, so without skew handling a new knob would no-op while the CLI prints a success-shaped config view (and a partial apply: the old server applies the knobs it recognizes and drops the rest).

The mechanism is a single channel-wide integer plus a per-knob min-version table, instead of per-feature response-shape sniffing (which accumulates bespoke compat code that never expires) or gating on the package version (not known at PR time; dev installs report unparsable `.dev` versions) or a capability list (a server-side string per feature that never expires):

- **Server**: `CONTROL_API_VERSION: int` in `inspect_ai._control`, advertised in the discovery file (`<pid>.json`) and stamped on each `GET /tasks` row (like `keep_alive`). A missing field means version 0 — the one-time bootstrap for servers deployed before reporting existed, which expires on its own as those processes finish. (`/tasks` returns a bare list, so the version rides each row rather than an envelope; the discovery file is what the CLI gates on, since it's already read before any request and covers the pre-registration window where `/tasks` is empty.)
- **CLI**: `_KNOB_SINCE: dict[str, int]` parallel to `_KNOB_SCOPE`, with key-set parity enforced (a runtime assert in `_exec_limits` plus a test) so every knob declares its since-version explicitly rather than silently defaulting to "understood by every server"; knobs that predate versioning are since-0. Pre-flight — before sending the PATCH — any requested knob with `since > server_api_version` hard-errors, naming the offending flags. The integer is meaningless to users, so the error cites the remedy ("pid N is running an older inspect; restart the eval"), not the number.

**Server-side fail-closed check (strict mutations).** The silent-ignore behaviour the CLI gate defends against is also fixed at the source for servers from this version on: an app-wide dependency compares each mutation request's query-param names against the matched route's declared parameters and 400s — `{"error": "unknown query parameter(s): …"}` — *before* anything is applied, keeping the mutation atomic (every requested knob recognized, or nothing changes). Attached app-wide (short-circuiting on safe methods) rather than per route, so every mutation route — the config `PATCH` routes (`/config`, `/tasks/<task-id>/config`), the `POST` verbs (`/keep`, `/release`, `/tasks/<task-id>/log-flush`), and any added later — is born strict with no per-route annotation to remember. This protects every consumer (TUIs and agents don't carry a `_KNOB_SINCE` table), and needs no per-knob maintenance: the allowed set derives from the handler's own signature via the route's dependant, so a new knob is allowed automatically. `GET`s stay tolerant — an ignored read param can't corrupt anything, so strictness buys no safety on reads. (It would also break an older CLI against a newer server if a read param were ever removed, but that skew direction isn't expected — see above — so tolerance rests on the no-harm argument, not on protecting it.) A newer CLI hitting a strict server gets the specific 400 (already surfaced by `_request_json`) even with no `_KNOB_SINCE` entry, which enables retiring the client-side gate once pre-strict (tolerant) servers age out of the field. Strictness is observable on the wire: it shipped with the `CONTROL_API_VERSION` bump to 3, so `api_version >= 3` mechanically identifies a strict server — the retirement follow-up can skip the pre-flight for known-strict servers and let the server's 400 do the work, keeping the `_KNOB_SINCE` gate only for pre-strict (version < 3) processes rather than relying on a fleet-age judgment call.

**Conventions**: bump `CONTROL_API_VERSION` in the same PR that adds a knob the CLI must gate on (a query param an older PATCH handler would silently ignore), recording the new value as the knob's `_KNOB_SINCE` entry; purely additive response fields the CLI already null-guards don't need a bump. A `_KNOB_SINCE` entry that outruns the constant (forgot-to-bump variant A) is caught mechanically by a test (`max(_KNOB_SINCE.values()) <= CONTROL_API_VERSION`) — and self-catching anyway, since the author's own dev server would block their own knob. Reusing the current value without a bump (variant B) is convention-only. Two in-flight PRs bumping N→N+1 conflict on the constant — arguably a feature (the second PR notices the first).

**New endpoints don't need a bump.** A missing knob fails silently (hence the pre-flight gate), but a missing *route* fails loudly: an older server answers with FastAPI's stock `{"detail": "Not Found"}` 404, which the CLI can tell apart from a handler's `{"error": ...}` entity-not-found 404 (a control-server convention — every handler 404 carries the `error` key, pinned by a test). A new endpoint's CLI verb passes `not_found_missing_route` to `_request_json` and gets a definitive "older inspect — restart the eval" message instead of hedging ("the task may have finished, or…"), with no version bookkeeping and accurate answers even from servers that predate version reporting. The cancel verbs are the first users.

**Endgame**: the knob table is transitional. With strict servers shipped (the fail-closed check above, issue #66), both skew cases are answered by interrogating the actual server — 404 shape for endpoints, 400 for knobs — and the client-side gate retires once pre-strict (version < 3) servers age out of the field (issue #67; processes are short-lived, so they age out quickly).

### Wire envelopes: TypedDicts, adopted lazily

The endpoints' JSON envelopes are historically built and consumed as `dict[str, Any]`. The boundary itself is HTTP, so Python typing can't span it — the cost of `Any` is server-side: a typo'd key or wrongly shaped value at a construction site surfaces only as a CLI misrender, and test doubles drift silently from the real shapes (the config stub's `mutated` logic missed the retry knobs when they landed).

**Convention**: an envelope gets a `TypedDict` in `_control/views.py` when roadmap work next creates or modifies it — not as a big-bang sweep (churn for zero behavior change; if an envelope never changes again, typing it wasn't worth it). TypedDicts are plain dicts at runtime: zero wire change, zero cost, and mypy checks every server-side construction site plus the retyped test doubles. The CLI imports the same types and `cast()`s once at its JSON-parse boundary — documentation plus downstream field-access checking, **not** validation: pydantic-style strict validation client-side would fight the version-skew tolerance above (an older server's envelope must stay acceptable, not just parseable). Keys legitimately absent on older servers are `NotRequired`, so the skew surface is legible in the types. Scoped first step (the `ProcessConfigView` / `TaskConfigView` config envelopes): issue #62.

### Flags

One flag, `--ctl-server`, mirroring `--acp-server`'s overloaded-value shape (`ctl_server: bool | str | None` on `eval()` / `eval_set()` / `eval_retry()`):

```
(omitted)                       # control on, default AF_UNIX at <inspect_data_dir>/control/<pid>.sock
--ctl-server / --ctl-server=true   # control on (the explicit form of the default)
--ctl-server=false              # control off
--ctl-server=keep         # control on + park the process after the eval finishes
```

An earlier draft split "whether" from "where" into separate flags (`--no-ctl` / `--ctl-port` / `--ctl-socket`) and kept keep-alive as its own orthogonal `--keep-alive` flag. Review feedback reversed that: one discoverable knob that matches the established `--acp-server` shape beats a family of flags, and folding keep-alive in as a value makes its dependency on the server *structural* — a parked process with no control endpoint could never be released, and `--ctl-server=false --keep-alive` is now unrepresentable rather than a configuration error to detect.

The transport "where" values (`--ctl-server=4444` for a TCP loopback port, `--ctl-server=/path/to.sock` for a custom AF_UNIX path) are **planned** — the same value space `--acp-server` already accepts. Until they land, any string other than `keep` is rejected (more likely a typo of `keep` than an intentional choice).

### Environment-variable mirror

`INSPECT_EVAL_CTL_SERVER` mirrors the flag (same values: `false` / `true` / `keep`), following the `INSPECT_EVAL_ACP_SERVER` precedent. This lets a test runner or CI config globally suppress the surface (`INSPECT_EVAL_CTL_SERVER=false`) without modifying each `inspect eval` invocation.

### Relationship to `--acp-server`

The control channel defaults **on**; the ACP server defaults **off**. The asymmetry is intentional:

- ACP serves a narrow audience (editor-driven per-sample interaction) — most evals don't need it, so opt-in is right.
- Control serves every running eval — opt-out is right.

The flag shapes match (one overloaded-value flag each: `--acp-server=false|true|<port>|<host:port>|<path>`, `--ctl-server=false|true|keep` with the transport values planned). The remaining difference is just the default (`--ctl-server` omitted means on; `--acp-server` omitted means off), which follows from the audience asymmetry above.

### Test-suite cost

Pytest runs that spawn many evals will each try to bind. AF_UNIX is cheap and discovery files self-clean via PID-liveness, but per-eval bind overhead is worth measuring in phase 1. Mitigations if it matters:

- Set `INSPECT_EVAL_CTL_SERVER=false` globally for the test session.
- Make the bind lazy (allocate only when something asks via discovery).

The graceful-fallback policy means worst-case is "test logs have warning lines"; eval correctness is unaffected.

## Implementation

Phased delivery, with HTTP/H1 as the chosen wire. **Phases 1 (read surface + keep-alive) and 2 (per-sample events + `samples` deltas) are implemented**; phase 3 (modification) and phase 4 (push / SSE) are planned.

### Phase 1 — read surface + keep-alive (done)

The always-on read surface plus the process-lifecycle plumbing agents need. Gives shell-capable agents (Claude Code via Bash) a complete read surface today.

- **`EvalState` aggregate** (`_control/eval_state.py`). A process-global registry of per-eval terminal-sample counters (`total` and the terminal buckets `completed` / `errored` / `cancelled`), cumulative usage (`total_tokens` / `total_messages`), task/model metadata, planned sample ids, log location, and a live data source (`EvalState.live` — the running `TaskLogger`, exposed as a `LiveEvalData`). Registered when a task starts; folded by `task_id` so retry attempts of the same task collapse into one logical row (the latest registered attempt) — including legacy batch-retry attempts (`retry_immediate=False`), whose per-attempt `eval()` calls mint fresh `run_id`s. Each sample bumps exactly one terminal bucket at its final outcome — `cancelled` (sibling-failure / eval-cancel teardown) is separate from `errored` so it doesn't read as a failure but still counts toward `total`, so the eval is marked finished (`completed_at`) and isn't stuck "running". A sample cancelled while still *queued* (parked at the sample semaphore during teardown) never reaches a per-sample record; `finalize_eval` folds that shortfall into `cancelled` at the task's finish point so the counters reconcile. Such samples are deliberately absent from the `samples` listing — they never started, so there is no record to show and no value in identifying them individually; the counters, not the listing row count, are authoritative for totals. A zero-sample eval (eg. `--limit` slices past the dataset — a valid success) is likewise not stuck: with `total == 0` it's marked finished the moment it registers, since there's no sample whose terminal outcome would otherwise stamp `completed_at`. Counters and usage survive a sample leaving `active_samples`, so completed / keep-alive-parked evals stay visible. Reused logs register from their (already-parsed) headers only; their summaries-derived stats (message counts, the precise completed/errored split) resolve lazily — concurrently, memoized — on the first `GET /tasks` request, so an eval-set that no control client ever queries never pays the per-log summary reads. Cleared at the outermost run boundary (the `eval()` call for standalone eval, the eval-set for eval-set).
- **FastAPI server on AF_UNIX** (default; bind failures log a warning and degrade gracefully). Discovery file at `<inspect_data_dir>/control/<pid>.json`; security hardening (0700 dir, 0600 socket + json) per the Security model.
- **Read endpoints:**
  - `GET /tasks` — folded per-task summaries (subsumes the originally-planned per-eval status detail; the CLI reads the whole list and resolves a task client-side). Shipped as `GET /evals`; renamed once the CLI noun reorg made the mismatch obvious — the rows' identity is `task_id`, with retry attempts folded.
  - `GET /evals/<id>/samples` — all of an eval's samples (running + completed + pending), merged from `active_samples` + the recorder's live summaries (falling back to the on-disk log) + the planned `(sample_id, epoch)` set. Running samples carry `last_activity_at` (unix ts of the sample's most recent transcript event) and `events` (a live event count) so a consumer can tell "stalled" from "working" — `now - last_activity_at` is the sample's idle time — without diffing successive polls. (Caveat: a single in-flight model generation emits no event until it returns, so neither field advances *within* one long call — the per-sample `events` stream has the same blind spot; closing it needs streaming token deltas or a "current operation" indicator via the `execution_observer`, out of scope here.)
  - `GET /evals/<id>/sample?sample_id=<sid>&epoch=<n>` — one sample's summary + error detail: the listing's summary fields (status / timing / tokens / messages) alongside the current error + prior-attempt `error_retries`, so `sample show` is a single atomic read (running samples sourced from `active_samples`, terminal ones from the log). `sample_id` is a query param so string ids with reserved chars (`/`, `?`, `#`) address correctly.
- **`POST /release`** / **`POST /keep`** — release / set a keep-alive park. The only write endpoints in phase 1, and they act on the process, not on eval state. `/keep` is the inverse of `/release`: it latches keep-alive (the same process-global latch the launch flag sets and both parks gate on), so a process launched without `--ctl-server=keep` parks after its eval. The intent is last-write-wins — a keep that follows a release re-arms the park.
- **CLI (`inspect ctl`, `--json` throughout; commands shown with their current noun spellings — they originally shipped as flat verbs and were reorganized, see "CLI command hierarchy"):** `task list` (running tasks; a keep-alive status footer reports `on` / `off` / `mixed` across processes), `sample list [TASK]` (per-sample table: status / retries / score / timing / idle / tokens / messages / turns, plus token-limit usage/ceiling columns when a limit is configured), `sample show TASK SAMPLE_ID [EPOCH] [--traceback]` (one sample's summary + error history), `sample errors [TASK]` (triage list of errored / retried samples), `process list` (running processes), `process keep [PID]` (park a running process after its eval), `process release [PID]`. `TASK` resolves by task-id prefix, then task-name (anchored at the name start or after a `/`); unscoped reads span all running tasks, while mutations default to the sole running task.
- **Retry + cancellation surfacing.** Sample retry counts — both sample-level `retry_on_error` and task-level retries (the latter seeded onto the re-run via the sample source, and carried across attempts that tear a sample down before it re-runs) — appear in `samples`; prior-attempt errors in `sample` / `errors`. A cancellation (a sibling failure tore the attempt down) is **not** a genuine error: it renders as `pending` when a retry will re-run the sample, `cancelled` when terminal — never `error`. This avoids the misleading "all samples error" snapshot during a retry teardown.
- **`--ctl-server`** on `inspect eval` / `inspect eval-set` — on/off plus the `keep` park value (see Implementation notes).

### Phase 2 — per-sample events + `samples` deltas (done)

Two additions, both **cursored-pull** (push / `--follow` is deferred to [phase 4](#phase-4--push-sse) — pull is the agent-primary shape, needs no streaming infrastructure, and the cursor designed here is exactly what phase-4 push reuses):

- **Per-sample transcript `events`** — `GET /evals/<id>/sample/events?sample_id=<sid>&epoch=<n>` (`sample_id` a query param, as in `sample`, so ids with reserved chars address correctly). The firehose of `model` / `tool` / `error` / `score` / … events for one running sample. This is the genuine stream — the one thing polling the reads can't reconstruct.
- **A recency delta on `samples`** — `GET /evals/<id>/samples?active_since=<ts>`. "Samples started or updated since T," so a monitoring agent gets *what changed* in one read without diffing snapshots client-side. This subsumes what a separate eval-level "lifecycle updates" stream would have provided (see below).

There is deliberately **no** eval-level lifecycle event stream. Eval-level current state is already a poll of the phase-1 reads (`tasks` counts + status, `samples` status + `last_activity_at`, `errors` / `sample` retry history); the `samples` recency delta covers the "what changed" gap. An *ordered* eval-level transition log is an audit / replay / TUI concern, deferred to [later](#later-beyond-phase-4) — see "Why no lifecycle stream" below.

CLI: `inspect ctl sample events TASK SAMPLE_ID [EPOCH]` (transcript stream) and `inspect ctl sample list TASK --active-since T` (the delta). Event-stream flags: `--cursor <cursor>` (shipped as `--since`; renamed in the noun reorganization to dissolve the `--since`/`--since-time` near-collision), `--tail N`, `--type`, `--full`, `--since-time/--until`, `--json`. (`-f/--follow` arrives with phase-4 push.)

#### Why no lifecycle stream

Building a dedicated eval-lifecycle event stream would mean a control-owned, hook-fed, ordered buffer per task (with its own cursor) — and for the agent monitoring loop it's largely redundant. An agent acts on *current state* ("sample 5 errored", "this one's idle 8m"), which is a poll away: status and counts from `task list` / `sample list`, stalls from `last_activity_at`, retry history from `retries` + `sample errors` / `sample show`, "eval finished" from `task list` `completed_at`. The only thing a poll lacks is a cheap delta — supplied by the `samples` recency filter. The sole thing a transition *log* uniquely adds is the *ordered intermediate history* (every flip, in order), which is an audit/replay/TUI need; deferring it avoids building (and cursoring) a second buffer until a real consumer wants it.

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

Wire it as an **opaque token** (core = the index) carrying the sample's **attempt identity**: the sample uuid (`EvalSample.uuid` == `TaskState.uuid`) plus the attempt count (the number of prior failed attempts, read off `error_retries`). The running source and the terminal (logged) source derive this identically, so a cursor handed out *while the sample runs* stays valid once it's logged — the running→terminal transition does not look like a different run. A retry, on the other hand, runs on a **fresh transcript**: a task-level retry mints a fresh uuid, and an in-process `retry_on_error` reuses the uuid but increments the attempt count — so a cursor carried across either no longer matches and the server signals a reset instead of silently applying a stale index to unrelated events. The client round-trips the token (`--cursor <token>`; `since=<token>` on the wire); opaque also lets the encoding evolve. Response is an **envelope**:

```json
{ "events": [...], "next": "<cursor>", "done": false }
```

- `next` — pass to the next call. `since` is **exclusive** (events with index > cursor; `next` = index of the last event *scanned*).
- `done` — sample has terminated; no more events will come, so a polling agent knows to stop.

A served page is **always contiguous** from the cursor — there is deliberately no "gap" / `missed` field. A bounded transcript's evicted events are re-materialized transparently from its history provider (the realtime sample buffer, read page-sized via `TranscriptHistory.events_from(start, limit)`), so eviction never gaps a page. The one theoretical exception — events evicted with *no* provider — is not a production configuration (bounded mode is only enabled together with the buffer, which is the provider) and surfaces as a hard error (structured 500), never as a silently-gapped stream. An earlier draft carried a soft `missed` count for this case; it was dropped as dead surface once provider-backed reads made the gap unreachable.

**The cursor indexes the unfiltered sequence; `--type` is applied to the page after slicing.** So `next` reflects the last event *scanned*, not the last *matched* — a sparse filter (or changing `--type` between calls) still advances correctly and never re-walks or skips. Starting points are flags, not magic cursor values: no `--cursor`/`--tail` → a small default recent tail (never an empty first page — see the agent output contract); `--tail N` → seed from `recent_events(N)`; `--cursor <token>` → resume.

This cursor is exactly what the phase-4 push path reuses: each SSE event is stamped with its index, so a dropped `--follow` reconnects with `--cursor <last index>`. Pull is built first; push layers on without a new cursor model.

#### Multiple samples

Each sample's transcript has its **own** independent index — there is no eval-wide monotonic sequence (events are created in separate sample tasks; nothing assigns a global counter). So a single scalar cursor can't span samples. Split by consumer rather than forcing one:

- **Agents** compose **the reads + per-sample drill-down**: poll `samples` (with `?active_since` for the delta) to spot a sample that errored or stalled, then read *that* sample's transcript `events`. This covers the monitoring loop with no multi-sample transcript cursor — and it's all cursored pull / poll, so it's fully available in phase 2.
- **TUIs / dashboards** that want the merged firehose want it *live*, which is push: an **eval-wide SSE fan-in** (`GET /evals/<id>/samples/events`) merging every running sample's subscription — live tail, no cursor. Being push, it lands in [phase 4](#phase-4--push-sse).

A multi-sample *cursored pull* of transcript events is intentionally **not** built unless a concrete need appears (lifecycle + drill-down serves agents). If it ever is, the cursor is a **composite vector of per-sample indices** encoded into one opaque token — never a timestamp.

#### Time as a filter, not a cursor

A wall-clock window is a snapshot query (no exactly-once requirement), which is genuinely useful and cheap: on the event stream, `--since-time T1 [--until T2]` filters the page after the cursor slice; the `samples` recency delta (`?active_since=<ts>`) is the same family — "current state of whatever changed since T," not a resume position. Both are timestamp-as-*filter*, which is fine precisely because they don't promise exactly-once. The right home for "by time" without ever being load-bearing for resumption.

Unlocks watchdog agents (cursored polling). Live-render TUIs follow once phase-4 push lands.

### Phase 3 — modification (direct) methods

The first endpoints that **mutate the run**, each idempotent and supporting `?dry_run=true` / `--dry-run` from day one. Shipped so far: the log-flush and buffer-params directives, the concurrency-config directive (`max_samples` / `max_sandboxes` / `max_subprocesses` / `max_connections`) — surfaced through `ctl task log-flush` and `ctl config` — and the cancel directives (`ctl task cancel` / `ctl sample cancel`); adding a task to a running eval, then drain / requeue and the per-sample time/token/message limits follow. The Security model's "future hardening" (SO_PEERCRED UID check, self-targeting guard) lands with this phase, since it introduces the first state-mutating writes.

#### Flush buffered samples + tune buffer params (shipped)

Two small, naturally-idempotent buffer directives shipped ahead of the larger phase-3 work, motivated by long S3-backed runs whose completed samples sit in the local flush buffer (and aren't analyzable in the log) until enough queue up to trigger a write:

- **`POST /tasks/<task-id>/log-flush`** (CLI: `inspect ctl task log-flush [TASK]`; originally shipped as `ctl flush` over `POST /evals/<id>/flush` — re-keyed by task, resolving the latest attempt server-side, when the noun reorg landed) writes the task's currently-buffered completed samples to the (possibly remote) log immediately — `recorder.flush()` followed by removing those samples from the realtime buffer database — and reports the count written. Idempotent: a flush with nothing pending writes nothing and reports `flushed: 0`.
- **`log_buffer` / `log_shared` on `GET`/`PATCH /tasks/<task-id>/config`** (CLI: `inspect ctl config [TASK] [--log-buffer N] [--log-shared S]`; originally shipped as a standalone `ctl buffer` command over `GET`/`POST /evals/<id>/buffer` — absorbed into `config` in the noun reorganization, the params being the `--log-buffer` / `--log-shared` launch flags, and the dedicated buffer routes deleted) reads or retunes the task's sample-buffer params: `log_buffer` (completed samples buffered before a log write) and `log_shared` (the shared-log event sync interval, seconds). The config view carries them under a `buffer` key (`None` for a task with no live buffer — a reused log, or a superseded attempt; an explicit set then warns server-side like the other unadjustable knobs, and the CLI escalates that set to a hard error, warning on a pure read). Setting `log_buffer` changes the threshold for *future* writes only — it doesn't flush samples already buffered; lowering it takes effect from the next completed sample (use `inspect ctl task log-flush` to write what's already pending now). Keeping the directive policy-only avoids coupling a parameter change to a possibly-remote write.

Both reach the live eval through `EvalState.live` — the running `TaskLogger` the runner attaches to the process-global `EvalState` (as a `LiveEvalData`, the same handle that serves sample summaries / full samples / transcript events) — so the control layer never re-derives the buffer's location; it's detached on retry, and reports a finished no-op once `log_finish` has run (kept attached, so a `--ctl-server=keep` park can still answer). An `anyio.Lock` on the `TaskLogger` serializes the three flush paths — the buffer-full flush that sample completion triggers, the on-demand flush, and `log_finish`'s recorder teardown. The recorder holds its own lock, so the writes themselves are already safe; the `TaskLogger` lock keeps the *bookkeeping* correct (the returned flushed count reflects exactly what was flushed) and stops an on-demand flush from reaching into the recorder after `log_finish` has torn it down.

Unlike the larger phase-3 directives, these two ship without `?dry_run=true` and ahead of the phase's security hardening: they're naturally idempotent (a flush with nothing pending, or a buffer read, has nothing to preview) and low-risk, non-destructive mutations over the local AF_UNIX socket.

#### Modify concurrency limits — max-samples / max-sandboxes / max-subprocesses (shipped)

The first slice of the "Modify concurrency" directive (open question #2): retune `max_samples` (per-eval sample concurrency) and `max_sandboxes` (per-provider sandbox concurrency) mid-flight. A follow-on slice added `max_subprocesses` (process-global subprocess concurrency) on the same pattern — the first knob to ride the version gate ("Version skew" above): it is since-1 in `_KNOB_SINCE`, with `CONTROL_API_VERSION` bumped to 1 in the same PR, so a CLI carrying the knob refuses a server launched before it rather than letting the PATCH silently drop it.

- **`GET`/`PATCH /tasks/<task-id>/config`** (CLI: `inspect ctl config [TASK] [--max-samples N] [--max-sandboxes N] [--dry-run]`; originally shipped as `ctl limits` over `…/limits` URLs, renamed in the noun reorganization) reads (`GET`, or a `PATCH` with no set values) or applies (`PATCH`) the knobs. Idempotent — re-applying the same value is a no-op — and `?dry_run=true` / `--dry-run` reports what *would* change without applying it, per the phase-3 agent-shape constraint. (Subsequent slices below extend this with `--max-connections` and `--model`, a process-wide `/config` endpoint, and an optional `TASK`. Originally built as `PATCH /evals/<id>/limits`; re-keyed by task id once `max_samples` became task-scoped — see "Task-keyed, not attempt-keyed" below.)

**The enabler is a resizable limiter.** Both knobs previously bottomed out on a fixed `anyio.Semaphore`. They now back onto a small `ResizableLimiter` wrapping `anyio.CapacityLimiter` (the same primitive the adaptive controller and `DynamicSampleLimiter` already resize via `total_tokens`), so setting a new limit is live: raising it lets more work start on the next acquire; lowering it below the current in-use count blocks new acquires until in-flight holders drain — it **never preempts** a running sample/sandbox. `create_sample_semaphore`'s two static paths return a `ResizableLimiter`; the `concurrency()` registry grew an opt-in `resizable=True` that the sandbox path (`sandboxes/<type>`) used — and, since the follow-on slice, the subprocess path (`subprocesses`) — initially leaving every other registry semaphore on the fixed `anyio.Semaphore`. Since superseded by the named-key slice below, which makes every static registry entry resizable by default.

**Reaching the limiters.** `max_samples` is task-scoped, and its storage matches: the directive reads the limiter straight from the task_id-keyed sample-semaphore registry (populated by the runner, shared across a task's in-run (immediate) retry attempts so a retune survives a retry — legacy batch-mode retries (`retry_immediate=False`) run as separate `eval()` calls whose per-run registry reset reverts to config — see `design/adaptive-concurrency.md`). The attempt-scoped `EvalState` rows are consulted only for existence (the 404). Only a `ResizableLimiter` entry is a user setpoint; a `DynamicSampleLimiter` entry (the adaptive-connections path — concurrency tracks the controller) or a missing entry (a reused/synthetic task that ran no samples here) reports `max_samples` as *not adjustable* (a warning, not an error). `max_sandboxes` is process-global (sandbox concurrency is shared across the process's evals, keyed by sandbox type), so it flows through a process-global sandbox-limiter registry (reset per run) rather than an `EvalState` field; a `PATCH` applies the new value to every tracked sandbox type. Sandbox limiters register **eagerly at run-level sandbox startup** (`ensure_sandbox_limiter`, called before `task_init`'s image pulls — which can take minutes) rather than on the first sample's acquire, so a `--max-sandboxes` issued while the run is still starting lands instead of being dropped; the per-sample acquire path re-ensures idempotently, covering per-sample sandbox overrides the startup pass can't see. `max_subprocesses` is process-global like `max_sandboxes` (the `"subprocesses"` registry key, now `resizable=True`) and flows through a process-global subprocess-limiter slot (reset per run). Unlike sandboxes it registers **lazily, on the first concurrency-managed `subprocess()` call** (pre-acquire, so a retune lands even while every slot is held): there is no startup phase that consumes subprocess concurrency before then, so the not-yet-registered window is exactly the window where the knob has no effect — a set issued in it warns rather than silently dropping, and eager registration would put a permanent `subprocesses` row in every eval's concurrency status display, subprocess-using or not. A knob with no adjustable limiter for the target task is reported with a warning while the other knobs still apply, so a combined `PATCH` isn't all-or-nothing.

**Task-keyed, not attempt-keyed.** The endpoint lives at `/tasks/<task-id>/config` rather than `/evals/<eval-id>/…` because nothing in the view is attempt-scoped: `max_samples` is a per-task setpoint (surviving retries, above) and the other knobs are process-wide. Task ids are stable across retries — the same reason the `ctl` read commands take task selectors — so a caller's handle never goes stale mid-run, where an attempt-keyed URL would dangle on every retry (this settles open question about directive selectors, for this directive, in favour of task ids). The scheme rule: **attempt-scoped resources stay under `/evals/<eval-id>/…`** (samples, sample detail, sample events — they belong to one attempt's log), **task-scoped ones live under `/tasks/<task-id>/…`**. `log-flush` and the buffer params originally shipped attempt-keyed (`/evals/<id>/flush`, `/evals/<id>/buffer`) but only ever act on the live attempt's recorder, so task keying fits them better — they moved task-side (via `latest_eval_for_task`, the last-registered attempt — the same fold rule the summaries use) when the noun reorg landed.

*Future work — task-keyed read aliases.* The reads stay eval-keyed for now: their data genuinely is attempt-scoped (a superseded attempt's samples/events remain addressable until the retry sweep removes its log), and the CLI already resolves task selectors to the latest attempt client-side. When raw-API consumers (agents polling across retries) need a stable handle, add `GET /tasks/<task-id>/samples` / `/sample` / `/sample/events` as *aliases* that resolve the latest attempt server-side (via `latest_eval_for_task`, as `log-flush` already does) — additions, not moves: the `/evals/` reads remain for addressing a specific attempt.

The remaining concurrency knobs — `max_tasks` and the per-sample time / token / message limits — are the later slices of this directive. (Adaptive `max_connections` is covered by the ceiling-retune slice below; the *static* `max_connections` path is reachable by model name through the named-key slice below, the registry entry being an ordinary static semaphore.)

#### Adaptive connections — read-side visibility (shipped)

Under default-on `adaptive_connections`, model-API concurrency isn't a fixed user setpoint: an `AdaptiveConcurrencyController` (one per model per account, process-global in the concurrency registry) runs slow-start + AIMD off rate-limit feedback, and sample concurrency follows it via `DynamicSampleLimiter` (tracks its own model's controller at `concurrency + BUFFER`) — see `design/adaptive-concurrency.md` for the subsystem's internals. So on this path `max_samples` is *not adjustable* — but the old limits endpoint said only that, with no numbers, leaving the whole adaptive path opaque to an observing agent. You can't sensibly decide to throttle what you can't see.

This slice makes the path **observable**. The config view always carries an `adaptive` list: one entry per controller with its live `limit`, in-flight `in_use` (read from `borrowed_tokens` directly — exact through a shrink-below-in-use, matching the `max_sandboxes` fix), scaling bounds (`min` / `max`), and the last few `recent_changes` (each `{at, from, to, reason}`, where `reason` is `slow_start` / `steady_state_up` / `rate_limit`, plus `manual` once the ceiling-retune slice below lands). That's enough to answer "where is concurrency now, how much headroom is left, and is it actively being cut by the provider?". The CLI renders it under an `adaptive connections:` block and repoints the `max samples` line at it (`tracks adaptive connections (see below)`) instead of the bare "not adjustable". Like `max_sandboxes`, controllers are process-global, so the list reports every controller in the process rather than filtering to the queried eval's model.

`AdaptiveConcurrencyController` gains public `in_use` / `min` / `max` accessors (the `min` / `max` also back the write side below).

#### Adaptive connections — retune the ceiling (shipped)

The mutation that pairs with the visibility above: the controller **`max`** (its scaling ceiling) is settable mid-flight via `--max-connections` (`PATCH /tasks/<task-id>/config?max_connections=N`) — `max_connections` on the adaptive path, the deferred slice noted above. This is the natural throttle for the headline "it's hammering the provider / running up cost" scenario, which otherwise has *no* lever on the adaptive path. It applies to every adaptive controller in the process (process-global, one per model), mirroring how `max_sandboxes` fans out; a run with no adaptive controllers reports it as not adjustable (a warning, not an error), consistent with the other knobs.

- **Lowering** clamps the controller's current limit down to the new ceiling immediately (never preempting in-flight requests — same drain-don't-kill semantics as `ResizableLimiter`) and caps subsequent AIMD growth; sample concurrency follows through the existing observer chain.
- **Raising** lifts the ceiling so the controller can climb again on clean rounds; the current limit is left untouched (the controller grows on its own).

`AdaptiveConcurrencyController.set_max(new_max)` does the reconciliation: it updates the ceiling, sets `min` to `min(configured_min, new_max)` — pulled down while the ceiling sits below the configured floor (preserving `min <= max`), restored to that floor when the ceiling is raised again, so a temporary throttle doesn't permanently weaken the floor rate-limit cuts clamp to — and clamps the live limit down (recording a `manual` history entry + firing observers) only when lowering below the current limit. The `manual` entry is captured into the eval log's `connection_limit_history` like any other change (its `reason` enum is `LimitChangeReason`, which includes `manual`), so the logged limit timeline stays continuous across a retune and a throttled run's actual operating concurrency is recoverable post-hoc. The one non-obvious coupling: the controller and `DynamicSampleLimiter` each call `resolve_adaptive()` separately, so they hold *distinct* `AdaptiveConcurrency` objects — a raise would have been silently capped by the sample limiter's stale snapshot of `max`. Fixed by having `DynamicSampleLimiter` derive its cap from its **own model's live controller** (`concurrency + BUFFER` of the controller registered under the task model's connection-pool key — `model_concurrency_key`, the same key `_connection_concurrency` registers under, so the two sides can't drift) rather than its own snapshot, removing the double source of truth so one `set_max` is authoritative. The key scoping is load-bearing: controllers are process-global (one per model *per account*), so an unscoped derivation would let a grader or eval-set sibling model's higher ceiling drive a task's sample concurrency far past its own model's limit — and key (not display-name) identity keeps even a same-named controller on a different account from standing in.

**Selector scope.** `--max-samples` is per-eval, but `--max-connections`, `--max-sandboxes` and `--max-subprocesses` are process-global — a named task just picks the process, and the change reaches every eval in it. For a single-task process this is invisible (process == the named eval); in an eval-set (many tasks per process) it isn't, so the CLI words those options as process-wide and, whenever an invocation supplies one of them (sets and `--dry-run` alike), prints a note when the change can reach more than one task — the process's active tasks, plus an explicitly named completed target (`... applies process-wide — every active task in this process is affected`).

Because those knobs are genuinely process-scoped, they get a **process-level `GET`/`PATCH /config`** endpoint (no task id) alongside the per-task `GET`/`PATCH /tasks/<task-id>/config`. `task_limits` is a superset of `process_limits` (the internal function names predate the URL rename) — the process-global logic (`_apply_process_knobs`) is shared, and `task_limits` just prepends the per-task `max_samples`. The CLI uses this to make `TASK` optional: with no task it defaults to the sole running process — a single-eval process still shows the full per-eval view, a multi-eval process shows just the process-global knobs (with `max samples` rendered as "per task"), and setting the per-eval `--max-samples` there still requires a task. Several running processes with no task is the one ambiguous case (pass a task to pick one).

In a mixed-model run, **`--model`** scopes `--max-connections` (and the reported adaptive view) to matching controllers — matched at the name start or after a `/` with exact-wins precedence, the same rule as CLI task-name selection (`gpt-4` matches `openai/gpt-4`, not `openai/gpt-4-turbo` when both are active). A model that matches no active controller is a warning, not an error.

Deferred beyond this: **pin / freeze** (force a limit and stop adapting — a new controller mode, wait for a concrete ask) and the **tuning-curve knobs** (`cooldown_seconds` / `decrease_factor` / `scale_up_percent` — niche, and hard for an LLM agent to reason about).

#### Retry-loop overrides — timeout / attempt-timeout / max-retries (shipped)

Of the `GenerateConfig` fields excluded from `task_identifier` (safe to retune by construction — they don't affect model outputs, so a mid-flight change can't corrupt eval-set pairing), `timeout`, `attempt_timeout` and `max_retries` are the incident levers: "lower the timeout / stop retrying and fail fast" (or raise retries to ride an incident out) otherwise requires killing the run.

Unlike the concurrency knobs these aren't limiter-shaped — they're read from the per-call `GenerateConfig` inside the generate retry loop. The mechanism is a **live override layer** (`inspect_ai.model._generate_overrides`, process-scoped like `max_sandboxes` / `max_connections`, reset at the outermost run boundary alongside the other control-channel registries) consulted at the *point of use* rather than merged into any config object:

- The tenacity `stop` condition built by `model_retry_config` reads the `max_retries` / `timeout` overrides on **every post-attempt check** — not just at decoration time — so a retune reaches generate calls already stuck inside a retry loop (the incident case; a merged-at-generate-time config would only affect *new* generate calls, and a sample stuck retrying forever never starts one). Post-attempt means the worst-case latency for a fail-fast retune is the remainder of the current backoff sleep (the wait caps at 30 minutes) plus one more attempt — which a simultaneously lowered `attempt_timeout` bounds.
- Batcher **admin-operation** retry loops (batch create / result poll) opt out via `batch_admin_retry_config()` (a `model_retry_config(..., live_overrides=False)` wrapper that batching providers must use, so a new batcher can't drop the opt-out by copying a generate-path call site) and run with the launch config only: an exhausted admin-op retry fails *every request riding the batch*, so a fail-fast retune aimed at stuck generate calls must not convert one transient poll 429 into a whole-batch failure. Batch-mode generates still feel the `timeout` / `max_retries` levers — each request's retries run in `Model._generate`'s own (live) retry loop.
- `Model._generate` resolves `attempt_timeout` per attempt when opening the attempt's cancel scope, so the override applies from the next attempt; an in-flight attempt's scope is never retroactively shortened (drain-don't-preempt, matching the concurrency knobs). A **batched** call is exempt from the `attempt_timeout` override (it keeps its launch value; keyed on a truthy launch `batch` config, so a provider that ignores batching also opts out when batching was requested — the exemption errs toward never cancelling a batch wait): a batched attempt awaits an entire provider batch — routinely minutes to hours — and an override cancelling that wait would resubmit the request into a *new* batch on every retry (duplicated provider work; with unlimited launch retries, forever) — the same whole-batch blast radius the admin-op opt-out avoids, reached through the cancel scope instead of the stop condition. Values a provider SDK bakes into its client at initialization are not affected.

Landing these knobs surfaced (and fixed) a long-standing `max_retries` off-by-one: the old `stop_after_attempt(max_retries)` counted *total attempts*, so `max_retries=1` meant zero retries despite every doc saying "retries". The live stop condition now counts retries as documented — `max_retries=N` allows N+1 attempts, and `0` means "fail after the first attempt", exactly the fail-fast incident value.

Surfaced as `timeout` / `attempt_timeout` / `max_retries` on both `PATCH /config` and `PATCH /tasks/<task-id>/config` (CLI: `inspect ctl config [--timeout S] [--attempt-timeout S] [--max-retries N]`), with the keyword **`clear` removing an override** — restoring each generate call's own launch config. `clear` is spelled the same at every layer (CLI keyword, wire value on the string-typed query params): every integer >= 0 is a real value (`--max-retries 0` = no retries), and an in-band integer sentinel like `-1` would let a caller's sign bug silently clear an active override instead of erroring. Values are bounded above by `MAX_GENERATE_CONFIG_OVERRIDE` (10^9, ~31.7 years in seconds), enforced at both wire layers and in the store itself: an unbounded integer would reach `anyio.move_on_after`'s float conversion and raise `OverflowError` inside every subsequent generate call — a stored bad value poisons the point of use, so it must be rejected at the door. The view carries a `retry` key reporting the active overrides (`null` = no override); the knobs are always adjustable (the override layer exists regardless of any task's launch config), so they never produce not-adjustable warnings. They are since-4 in `_KNOB_SINCE` (with `CONTROL_API_VERSION` bumped to 4 in the same PR — versions 1–3 were taken by `max_subprocesses`, the `--key` knob and strict mutations; see "Version skew" above), so a set against an older process errors pre-flight rather than silently no-opping; on a pure *read* an older server's view simply carries no `retry` key and the CLI omits the knobs rather than claiming a value.

Out of scope from the same exclusion set: `batch` (batcher already running), `cache` / `cache_prompt` (low standalone value), `adaptive_connections` (covered by the `--max-connections` ceiling retune above).

#### Retune named `concurrency()` keys — `--key` (shipped)

The `concurrency()` registry is a public API, and per-knob CLI flags will never cover the tail of limits that tools and user code register by name — the web-search providers (`google_web_search`, the HTTP providers' `concurrency_key`), sandbox-tools binary injection, model compaction (`<model>_compact`), the static `max_connections` semaphores, arbitrary solver code. This slice is the generic retune-by-name directive over that registry: `inspect ctl config --key NAME LIMIT` (`PATCH ?key=NAME&key_limit=N` on both config routes — the registry is process-global, so the knob rides the process-level endpoint and the task route alike).

- **Read side.** The config view grows a `concurrency` list enumerating every *static* registry entry as `{name, limit, in_use, adjustable}` — by exact registered name (no status-display prefix shortening, `visible=False` entries included: visibility governs the status bar, not retunability). Adaptive controllers stay in the `adaptive` view (their limit is a scaling ceiling, not a settable setpoint); a `--key` naming one warns and points at `--max-connections`. The CLI renders the list as a `concurrency keys [process]:` block, with an empty-registry placeholder ("none registered yet" — entries appear lazily on first use) kept distinct from an older server whose view predates the section ("not reported").
- **Resizable by default.** For arbitrary keys the semaphore was created by third-party code with `resizable` unset, so the default registry now backs *every* static entry with a `ResizableSemaphore` (the `resizable=True` opt-in remains for custom registries; a non-resizable entry — e.g. from such a registry — reports `adjustable: false` and a set warns, matching the shipped knobs' precedent). To keep this a pure implementation swap, `ResizableLimiter` acquires on behalf of a fresh borrower token per entry (task-local LIFO in a `ContextVar`) rather than the current task — preserving the `anyio.Semaphore` counting semantics (nested same-key contexts in one task take one slot each) where raw `CapacityLimiter` acquisition raises on a second same-task acquire.
- **Unknown keys error.** Named limits are created lazily on first use, so a `--key` naming no entry is rejected (HTTP 400, listing the available keys) *before any other knob applies* — unlike the shipped knobs' not-adjustable warnings, a mistyped name silently matching nothing would read as applied. Matching is by exact name (a mutation should not fan out on a prefix the caller never spelled); a name backing several entries (one model on two accounts) retunes them all, like `max_connections`' name matching.
- **Version skew.** An older server ignores the unknown query params and would return 200 with the key silently unapplied, so the knob rides the version gate ("Version skew" above): it is since-2 in `_KNOB_SINCE`, with `CONTROL_API_VERSION` bumped to 2 in the same PR, so the CLI refuses a `--key` against an older process *before* sending the PATCH.

#### Add a task to a running eval

`POST /tasks` (CLI: `inspect ctl task add SPEC [...]`) submits a **task spec** that runs in the target process under the same `run_id`, appearing as a new sibling eval in `task list` / `sample list` / `sample events`. Returns the new `eval_id`.

**A spec, not a `Task`.** The wire is HTTP/JSON; a `Task` carries code (solvers, scorers, dataset). So the directive carries a *spec* — registry name or file path, `-T` task args, model, config / limit overrides — which the running process resolves in-process via the registry, exactly as `inspect eval <name>` does at launch. A task the process can't resolve (not importable in its environment) fails with a clear error; `--dry-run` surfaces that before committing.

**Coupled to `--ctl-server=keep`.** A normal eval ends when its initial task set drains, so there's no stable window to add to (an agent would race the teardown). Add-task is therefore a capability of an *addable* run — one launched with `--ctl-server=keep`. An eval not launched addable rejects the directive with a clear error.

**Two add paths, one discriminator.** "Are tasks currently running?" is exactly "is the live work-queue open?":

- **Inject — tasks running.** The scheduler's queue is open → resolve the spec, mint identity + logger, enqueue it; a worker picks it up and it appears in the current task display.
- **Restart — parked.** The run has drained and the process is parked (keep-alive, *outside* the display) → start a fresh scheduler session, re-launching the task display, for the added task(s) under the same `run_id`; on drain, return to the park. The park stays where it is today (after the eval body) — it just gains the ability to relaunch a session.

The queue-closed check *is* the running→parked test, so the two paths can't both fire. An add that lands during the handoff (queue closing, display tearing down, park not yet entered) is **buffered**; the park drains buffered specs on entry — so an add is never lost regardless of timing.

**Always the scheduler path (`run_single` deprecated).** Today `eval_run` uses `run_single` for `parallel==1` (all samples in one task group, no queue) and `run_multiple` (a worker pool over a `memory_object_stream`) for `parallel>1` — only the latter is injectable. Rather than maintain two shapes, **`run_single` is deprecated**: every run goes through the `run_multiple` scheduler (`parallel==1` ⇒ one worker), so a live queue always exists while the display is up and the inject path is uniform. The visible change is that a single-task run renders via the multi-task screen; behaviour is otherwise unchanged.

**Workers.** An addable session **pre-starts `parallel` workers** — idle workers are suspended coroutines (no CPU, not shown in the display), so an injected task runs immediately instead of waiting for a busy worker to free, and there's no need to grow the pool mid-run. (Lazy spawn-on-inject is possible but needs a supervisor task *inside* the scheduler's group to own `start_soon` — a route can't spawn into a nursery it isn't inside — so pre-start is both simpler and effectively free.)

**Identity & logging.** The added task joins the existing `run_id` with a fresh `eval_id` / `task_id` and its own log file in the run's `log_dir`; it `register_eval`s like any task, so the read surface covers it immediately and an agent gets back an `eval_id` it can then poll.

**Wiring.** Mirrors the `--release` precedent (a route signalling the eval's own loop). The runner registers an `add_task` capability — a state-aware callback alongside `EvalState.live` on the process-global state — that either injects into the live queue or buffers for the park. The route resolves the spec on the eval's loop and invokes it; the response is deterministic (the new `eval_id`, a structured error, or a dry-run report).

**`--dry-run`.** Resolves and validates the spec (task importable, model available, args type-check) and reports what *would* run (identity, model, sample count) without minting a log or starting work.

**Scope.** Standalone `inspect eval --ctl-server=keep` first; eval-set — which owns its own retry loop and task resolution — is a later increment.

#### Cancel a task / a sample (shipped)

Both cancel directives ride machinery the eval runner already had; the runner's only involvement is stamping state the control layer reads (the `TaskCancel` handle at registration, `retry_pending` at the eval-set's retry decision):

- **`POST /tasks/<task-id>/cancel`** (CLI: `inspect ctl task cancel TASK [--dry-run]`) fires the latest attempt's registered `TaskCancel` with `"abort"` — the exact path the in-process task display's cancel dialog drives. The runner attaches the handle to the process-global `EvalState` at registration (like `EvalState.live`), so the control layer never reaches into the runner; `latest_eval_for_task` resolves the current attempt, and the handle is task-keyed like `config` / `log-flush` so it never dangles across a retry. Effect: the task group's cancel scope cancels — in-flight samples are torn down (their transcripts so far are preserved in the log as cancelled samples), completed samples are kept, partial results are computed, and the log finishes with an error status ("Task cancelled by user (abort)"); an eval-set does not retry an aborted task, and sibling tasks are unaffected (each task runs in its own cancel scope). Idempotent: a cancel of a finished task, or a repeat while a cancel is already in flight (`TaskCancel.cancel_type` set), reports `changed: false`. A task *between attempts* — its last attempt errored and the eval-set has queued a retry that hasn't started (`EvalState.retry_pending`, stamped at the retry decision point) — is rejected (409) rather than reported finished: "task already finished" would be a lie the retry then contradicts (the operator walks away, the task runs again), so the error says to re-issue the cancel once the retry is running. (Actually cancelling the *pending* retry is deferred with the graceful-drain work below — it needs the same stop-dispatching machinery.) `TASK` is always required on the CLI — destructive verbs get no sole-task default.
- **`POST /evals/<id>/sample/cancel?sample_id=<sid>&epoch=<n>&action=score|error`** (CLI: `inspect ctl sample cancel TASK SID [EPOCH] [--error] [--dry-run]`) interrupts one *running* sample via `ActiveSample.interrupt` — the same primitive the in-process TUI and ACP's `inspect/cancel_sample` use. `action=score` (the default) completes the sample and runs the scorer on the work done so far (recorded with an `operator` limit); `action=error` marks it errored, rejected (409) when the sample is configured to fail on errors (mirroring the TUI/ACP gate — the auto-fail would race it). A still-queued sample (parked at the sample semaphore, no task group yet) is rejected rather than half-cancelled; an already-terminal sample is the idempotent `changed: false` no-op. Sample addressing is by query param (ids may contain URL-reserved characters), and per the selector conventions the CLI requires `EPOCH` whenever the task runs more than one epoch (the task summaries carry an `epochs` field for this) — a defaulted epoch resolves to a *different sample*, which must not happen silently on a mutation. The route itself also fails closed: `epoch` is a required query param (omitting it is a 400), so a raw API caller can't silently target epoch 1 either — only the *read* routes keep the harmless `epoch=1` default.

Both accept `?dry_run=true` / `--dry-run` and return `changed` so the CLI's uniform mutation envelope (`{target, applied, dry_run, detail}`) reports applied vs the idempotent no-op. **Deliberately deferred:** the graceful-drain cancel variant (in-flight samples *finish naturally* before the task ends) and a `--force` split between the two — graceful drain needs the same stop-dispatching machinery as `task drain` (queued samples are all started up-front and parked at the sample semaphore, so "don't start new samples" is a real runner change); the shipped semantics are the abort path, stated as such in the CLI help.

#### Other directives

- `POST /tasks/<task-id>/drain` (`ctl task drain`), `POST /evals/<id>/sample/requeue?sample_id=<sid>&epoch=<n>` (`ctl sample requeue` — query-param sample addressing, like `sample` / `sample/events`, since sample ids may contain URL-reserved characters), and the per-sample time / token / message limits as further knobs on `PATCH /tasks/<task-id>/config` (CLI: `ctl config TASK --time-limit/--token-limit/--message-limit`). (Modify *concurrency* — `max_samples` / `max_sandboxes` / adaptive `max_connections` / named registry keys via `--key` (which also reaches the static `max_connections` semaphores by model name) — shipped ahead of these via `PATCH /tasks/<task-id>/config`; `max_tasks` is the remaining concurrency slice.)

These are the bigger eval-runner changes (live config mutation, requeue).

### Phase 4 — push (SSE)

Adds the **push** shape on top of the phase-2 per-sample event stream — for TUIs, dashboards, and other long-lived clients that render live rather than poll. No new data model: it reuses the phase-2 cursor and projections.

- **`--follow` on the per-sample event stream.** The phase-2 pull URL (`GET /evals/<id>/sample/events?sample_id=<sid>&…`) with `Accept: text/event-stream` streams the same items as the pull path. Each SSE event is stamped with its cursor index, so a dropped connection reconnects with `--cursor <last index>` — i.e. follow is just "pull, kept open," with the same `--type` / `--full` / `--since-time` filters.
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

- **CLI ergonomics are poor.** `inspect ctl task cancel <task>` needs a JSON-RPC client wrapper; no `curl` story; harder to script ad-hoc.
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

- **Agent-friendly `inspect eval`.** Launching an eval as an agent: `--json` output reporting the started run_id / log path / control-channel address; `--detach` so the agent can fire-and-monitor rather than block; structured pre-flight estimates (cost, sample count). The handoff from "launched" to "monitored via control channel" depends on this. The launch-handoff slice of `--json` has shipped (see "The launch handoff is load-bearing" above); `--detach` and the pre-flight estimates remain.
- **Agent-friendly `inspect log`.** Reading finished evals as an agent: `inspect log summary <file> --json`, `inspect log sample <file> <id> --json`, `inspect log compare <a> <b> --json`. The control channel handles live evals; `inspect log` handles finished ones. The handoff between them is part of the agent workflow.
- **CLI-wide ergonomics push.** Every `inspect` subcommand the agent might use needs `--json` and agent-friendly defaults. Help text written verb-first, with examples, no option-vs-flag ambiguity. The "Shape constraints" in this doc (summary-shaped, idempotent, dry-runnable, JSON-first) are CLI-wide conventions, not control-channel-specific ones.
- **Cost / budget visibility.** Agents making scope decisions need to see pre-run estimates and live spend. The control channel exposes live spend (via `EvalState` model usage); pre-run estimates and budget enforcement live in `inspect eval`'s launch surface.
- **Self-targeting guard hardening.** Open question #8 in this doc — an LLM agent running *inside* an eval shouldn't be able to control its own parent eval. The guard logically belongs in the control channel's bind / authorisation layer, but the broader story (sandbox network egress, capability gating, eval-time vs scaffold-time boundaries) is part of the larger agent-enablement effort.
- **"Using Inspect from an LLM agent" documentation.** A guide that walks through the full workflow (launch, monitor, manage, inspect, compare, iterate) and points at every relevant CLI command. Lives in `docs/`, not `design/`.
- **Persisting `ctl config` changes in the eval log.** Today every retune is in-memory only, so the log misdescribes a retuned run. [ctl-config-log-persistence.md](ctl-config-log-persistence.md) designs the recording mechanism (`EvalLog.config_updates`), and is a prerequisite for the planned per-sample limit knobs so they never ship with an unrecorded window.

Where this doc's design touches one of those surfaces (eg. the `EvalState` model that powers `inspect ctl task list`), we describe what the control channel does and reference the broader work for the surrounding context.
