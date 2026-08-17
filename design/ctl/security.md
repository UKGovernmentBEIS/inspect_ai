# Control Channel Security

The security model for the [control channel](control-channel.md), in two halves:

- **Access** — who can reach the control endpoint (socket permissions, peer credentials, network exposure).
- **Content** — what the agent-controlled data flowing *out* of the read endpoints can do to whoever consumes it (a human operator's terminal, or a monitoring agent's context).

The access model below is implemented as described. The content half mixes shipped mitigations with analysis and open proposals (it originates in the audit filed as issue #190); status is marked per item.

## Access model: who can reach the endpoint

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

**Filesystem hardening** (implemented by `prepare_discovery_dir` and `write_discovery_file` in `_util/discovery.py`):

| Object | Mode | Rationale |
|---|---|---|
| `<inspect_data_dir>/control/` directory | **0700** | **Principal protection.** Without `x` permission on the directory, other users can't traverse into it — the socket and discovery JSON can't even be `stat()`'d, much less opened. |
| `<pid>.sock` (AF_UNIX socket) | 0600 | Defence-in-depth — closes the gap if the directory ever gets loosened. |
| `<pid>.json` (discovery file) | 0600 | Same — prevents the socket path / run_id leaking via a world-readable JSON. |

The directory and socket modes are applied via `chmod` on every server start (idempotent), so a directory created before the hardening landed gets locked down on the next bind. The discovery JSON is handled differently: it's created owner-only at `open()` time (the mode is passed to `os.open`, capped by the umask) and published with an atomic temp-write-then-rename, so it is never *momentarily* more permissive than 0600 (no post-write `chmod` window) and a concurrent `inspect ctl task list` reader never observes a torn / partial-JSON file. Some filesystems ignore Unix permissions (FUSE, certain network mounts); the fallback is benign — everything still lives under `inspect_data_dir`, which is user-scoped, so the loss of defence-in-depth is bounded.

**What this buys us.** With the directory at 0700, an attempted connection from another user's process fails at the directory-traversal step (`EACCES`) before the socket file's own permissions are even consulted. The socket and JSON 0600 modes are belt-and-suspenders: they protect against a misconfigured umask, a future code path that lowers the directory perms, or a user running Inspect under different identities (sudo etc.) that accidentally widen perms.

**What this does NOT buy us:**

- **Same user, different process.** Filesystem perms can't distinguish "your Inspect eval" from "an untrusted script you ran as yourself" — both run with your UID. To enforce "only the launching eval can be controlled" would require an application-layer secret (cookie, capability token). Not in scope for v1 — trust model matches every other user-local IPC (D-Bus session bus, X11 socket, ssh-agent).
- **Sandboxed self-targeting.** Today sandboxes don't see the host data dir, so an LLM agent inside an eval can't reach the control channel. If a future scenario mounts the host data dir into a sandbox (eg. a meta-eval that watches other evals), that protection vanishes and we need a server-side "no self-targeting" guard ([control-channel.md](control-channel.md) open question #8).
- **Filesystems that ignore Unix permissions.** Some FUSE / network filesystems don't enforce perms correctly. If a user places `inspect_data_dir` on such a filesystem, all bets are off — but that's also true of their ssh-agent socket, browser cookies, etc.

**SO_PEERCRED / `LOCAL_PEERCRED` UID check.** **(Shipped.)** The server verifies the connecting process's effective UID matches its own and drops the connection otherwise. Redundant with filesystem perms in the normal case, but cheap defence-in-depth — it covers a misconfigured umask, a future code path that loosens the directory perms, and (partially) the ignores-Unix-permissions filesystems above. Implementation notes: the check is *connection-level* (the credential is a property of the connection) and applies app-wide rather than only to the write endpoints — reads share the same trust model, and one check at `connection_made` is simpler than a per-route dependency. It lives in a uvicorn HTTP-protocol subclass (`_peer_checked_http_protocol` in `_control/server.py`) because the ASGI request scope doesn't carry the accepted AF_UNIX socket; the credential read itself is `peer_uid` in `_util/sockets.py` (Linux `SO_PEERCRED`, macOS/FreeBSD `LOCAL_PEERCRED`). Fails **open** when the credential is unavailable (platform without the API — eg. Windows AF_UNIX — or a failed `getsockopt`): the check is defence-in-depth on top of the 0700/0600 permissions, and failing closed would brick the whole control surface on those platforms.

**Future hardening:**

- **Self-targeting guard.** Server-side rejection of any operation whose target eval is the caller's own process. Belongs in the bind-time check + each write handler. Tracked as [control-channel.md](control-channel.md) open question #8.
- **Authenticated remote attach.** If/when remote-attach is in scope, design needed: bearer tokens, mTLS, or a more domain-specific mechanism. Out of scope for v1 (loopback-only is the only supported transport; see open question #3 there).

## Content threat model: the agent under evaluation controls what the channel carries

With the access model above holding, the evaluated agent cannot reach the socket: it is defended by the filesystem permissions plus the peer-UID check, and the socket lives on the host outside the sandbox. So the channel cannot be *invoked* by the agent (if it could, the agent has already escaped and the channel is moot).

The channel's job, however, is to carry the evaluated agent's output **outward** to consumers — the `inspect ctl` CLI, TUIs, and monitoring agents. That content is attacker-controlled. The channel performs no content sanitization at the API layer — it is a faithful pipe by design. So the risk is not the agent reaching the host *through* the channel; it is the agent reaching whoever is *reading* the channel.

Crucially, the agent controls the carried content **two ways**:

- via **model completions** (requires the model under test to emit the text), and
- via **tool results** — e.g. `bash` stdout — which it controls directly and unconditionally (`echo <anything>` lands verbatim in the transcript, no model cooperation needed).

### How agent-controlled output flows through the channel

Four read endpoints can carry attacker-controlled content (since issue #190 shipped, only when the caller opts in with `content=true` / `full=true` — see "Mitigations" below; the fields listed are what an opted-in read carries):

| Endpoint | Source | Agent-controlled fields |
|---|---|---|
| `GET /evals/{id}/sample/messages` | `TaskState.messages` (`_control/messages.py`) | assistant completions; tool-call `arguments` (model-chosen); tool-message `content` (**sandbox output — fully agent-controlled**); tool `error`; `function` name |
| `GET /evals/{id}/sample/events` | transcript events (`_control/events.py`) | model event `completion`; tool event `arguments`/`result`/`function`; `error` event `message`; `info` event `source`/`data` |
| `GET /evals/{id}/sample` | error detail (`_control/state.py`, `sample_error_detail`) | error `message`, `traceback`, `traceback_ansi` — plus the same for every prior retry (tool-raised exception messages embed agent-influenced strings) |
| `GET /evals/{id}/samples` | sample listing | `activity.detail` (in-flight tool `function` name, model-chosen); `filter=errors` rows carry the error `message` |

The compact projections truncate free-text to 256 chars (`_TRUNCATE`/`_truncate` in `_control/events.py`, shared by `messages.py`) — but truncation is a size bound, not a sanitizer. `full=true` returns `model_dump(mode="json")` **untruncated** — the entire conversation / event content, raw. Machine consumers (`--json` / `--full`) get bytes-faithful data by contract and must do their own quoting/escaping; the sanitization described below is a property of the CLI's *human* rendering paths only.

### Vector 1 — prompt injection into a monitoring agent (primary; open by design)

A monitor that polls `sample events` / `sample messages` / `sample show` with content opted in (`--content` / `--full`; the default read is metadata-only — see "Mitigations" below) ingests attacker-controlled text on every poll. The payload can arrive via a plain `bash` tool result, so it does not depend on the model under test cooperating. The blast radius is **whatever the monitor can do**, which splits in two:

- **Within the ctl surface:** if the monitor is granted the mutation endpoints (the intended design), injected instructions could drive `POST .../sample/cancel` (kill a sample right before it is flagged), `.../sample/requeue` (discard an incriminating transcript by re-running it), `POST /pause` or `/models/pause` (DoS the run), `PATCH /config` (disable retries, or crank `max_connections`), or `POST /release` (end a keep-alive park → process exit). This corrupts eval integrity but stays inside the process.
- **Outside it:** monitors typically have *other* tools — web access, a filesystem, their own model, or the ability to shell out (including running the `inspect ctl` CLI, which can act on the host). The ctl channel is the injection conduit; the actual escape happens through the monitor's own capabilities, which Inspect does not and cannot bound. **This is the path that impacts the world outside the sandbox.**

**The trust boundary, stated explicitly:** a monitor reading this channel must be treated as processing untrusted input — exactly like a monitor reading raw model output. A monitor granted mutation endpoints should be sandboxed / capability-limited like any injection-exposed agent, and the read-consumer and mutation-actor roles should be separable (see "Mitigations" below for what separable would take).

### Vector 2 — terminal escape-sequence injection (mitigated)

When a **human operator** runs `inspect ctl` read commands, agent-controlled text is written to their terminal. Unmitigated, a tool result like `printf '\e]0;compromised\a\e[2K\rALL SAMPLES PASSED'` would reach the terminal raw — output spoofing/hiding (rewrite what a triage operator believes they are seeing), terminal-title changes, OSC 8 hyperlinks, OSC 52 clipboard writes on terminals that honor them.

**Mitigation (shipped — issue #195).** The human rendering paths (`_sanitize_control` in `_cli/ctl.py`, applied via `_truncate`, `_render_table`, `_echo_error`, and the sample-detail header) strip ANSI escape sequences (whole, payload included), C0/C1 control bytes, and Unicode bidi controls (RLO etc. — on BiDi-aware terminals these visually reorder the rest of the line across cell boundaries, cf. Trojan Source) before echoing, so a sample can't rewrite what a triage operator sees (`\r`/`\x08` overwrites), retitle the terminal, or write the clipboard (OSC 52). Single-line renderings — table cells, joined header parts, status/reason echoes, error messages — additionally flatten embedded newlines to spaces (`_sanitize_line`) so content can't forge rows or plausible whole lines of its own; only deliberately multi-line output (tracebacks) keeps newlines. Where several fields are joined into one line (the sample-detail header and its score list, event/message summaries), each field is sanitized *before* the join, so an unterminated string sequence in one field can't swallow the fields rendered after it.

Sanitization is deliberately **provenance-blind**: every dynamic string is sanitized at its formatting boundary — table cells, summary interpolations, joined header parts, directive status lines, the config view — whether or not the field is agent-influenced today. Classifying fields ("this one carries transcript content, that one is a server-generated status") is a per-field judgment that silently rots as fields are added and projections change; blanket application is a no-op on clean text, idempotent, and reviewable locally at the call site.

The policy is enforced structurally at the exit: all output leaves `_cli/ctl.py` through a sanitizing `_echo` wrapper (an AST-walking test keeps direct `click.echo` calls out of everything but the two wrappers), with `_echo_raw` as the explicit opt-out for machine output — the `--json` paths, bytes-faithful by contract, where `json.dumps` escapes control bytes itself — and for the keep-SGR renderings, whose deliberately kept styling the default wrapper would strip. Per-field sanitization before joins remains on top of the backstop, for fidelity rather than security: an unterminated string sequence sanitized only at echo time still swallows the rest of its line into the stripped sequence (silently losing the fields joined after it), whereas a field sanitized before composition can lose at most its own tail. The residual failure mode for a missed per-field wrap is therefore a truncated line, not an escape reaching the terminal.

The `--json` / `--full` machine paths pass content through untouched (consumers get bytes-faithful data and do their own quoting). `traceback_ansi` — usually Inspect's own rich rendering — keeps its SGR color/style codes (inert: they restyle, never rewrite) but is otherwise sanitized too, because it falls back to raw un-rendered text for oversized tracebacks and in recovered logs, and the exception text inside it is agent-influenced.

`process anomalies` is agent-influenced through a different route — a stalled sandboxed `bash` call's shlex-joined command line lands verbatim in the trace record's detail, and the rich table it renders through both preserves escape bytes in its styled export and parses cell strings as console markup (`[link=...]` would export an OSC 8 hyperlink) — so its rendered fields are sanitized, newline-flattened, and markup-escaped per record before entering the table (`_sanitized_anomalies`; per record, not post-export, where one row's unterminated OSC would swallow the rows after it), with a keep-SGR pass over the export as a backstop. `inspect trace anomalies` shares that rich rendering but not the sanitization — it is outside `inspect ctl` and reads local trace files, but shows the same agent-influenced detail text, so extending sanitization to it is a known follow-up.

### Vector 3 — DoS / event-loop amplification (partially mitigated)

The per-sample reads run **synchronously on the eval's own event loop** (see `_control/terminal_cache.py` and [endpoint-cost-audit.md](endpoint-cost-audit.md)). The agent controls transcript/message *volume*, and `full=true` is unbounded and re-serializes the whole sample. The agent cannot trigger the read, but it can make each read arbitrarily expensive; a monitor polling `--full` against a deliberately-bloated sample becomes CPU/allocation pressure on the eval loop, slowing the run. Mitigated (page limit 500, the 5s terminal-source cache, compact-mode truncation) but not eliminated — the mitigations cap per-page cost, not the agent's ability to inflate what a `--full` or whole-conversation read must materialize. A response-size ceiling for `full=true` is a candidate hardening, not currently planned.

### What is *not* a vector (defenses that hold)

- The channel never executes agent content as code — it is serialize-and-return only.
- `sample_id`/`eval_id` path and query params come from the dataset/harness, not the agent, so they are not an injection surface into the server itself; unknown query params fail closed on mutations (`_control/strict.py`).
- The socket is unreachable from a secure sandbox, and peer-UID + filesystem perms defend it from other host users (the access model above).
- Cursors are opaque and malformed ones safely restart (`decode_cursor` in `_control/events.py`).

## Mitigations: the metadata-only default (shipped) and the uninjectable monitor (proposal)

> **Status: the metadata-only default is shipped (issue #190); the read-only monitor tier is not.** Any client that can reach the socket can still call every route, reads and mutations alike — the read-only sections below record the design thinking for a hardened monitor tier, for when demand for one materializes.

**The shipped shape:** the per-sample read endpoints (`sample messages` / `sample events`, the error detail on `sample`, and the samples listing's error rows) return **metadata only by default** — roles, indices, tool `function` names, token counts, event types, timestamps, status, error *presence* — and gate the free-text content (completions, tool arguments, tool results, error messages) behind an explicit opt-in. A three-tier ladder:

- **default** → metadata only (the floor)
- `content=true` (CLI `--content`) → truncated content (the former compact default, 256-char cap)
- `full=true` (CLI `--full`) → raw serialized objects

The control-channel version history's entry 6 records the wire change; the CLI needs no version gate (GETs are tolerant of unknown params, so an older server pointed at by a newer CLI simply keeps returning content — the CLI is a human surface, where the metadata default is UX, not the security boundary).

**Why this is worth doing — the security property is "never becomes compromised", not "safe once compromised".** The security-relevant moment is the transition from a clean monitor to a compromised one: the first time it ingests raw attacker content. A monitor that *never reads raw agent content is uninjectable by construction* — the payload never reaches it. Metadata-default makes that uninjectable state the effortless default, and content-reading a deliberate, rare exception.

This reframes what the opt-in flag is. It is **not** a runtime guard that a compromised monitor might flip back on (pre-injection there is nothing to bypass; post-injection the monitor is already lost). It is a **design-time class declaration**: a monitor is either in the uninjectable metadata class, or its owner has deliberately placed it in the injectable content class. That distinction is the whole value — and it means the gate belongs at monitor-provisioning/policy level, not (only) as a per-request query param.

**Corollary — the ctl channel only matters as an *initial infection* vector.** Once a monitor is compromised, the ctl channel is not special: a compromised monitor with filesystem/network access can read the `.eval` logs or realtime buffer snapshots directly and obtain all the ongoing attacker content it wants — a richer, always-available source than the channel. So hardening what the channel hands an *already-compromised* monitor is largely moot; the leverage is entirely in preventing the initial compromise.

**Recommended architecture (the strong form):**

> **Metadata-only, read-only ctl access + no direct log / filesystem / network access = a monitor that structurally cannot obtain raw agent content (so cannot be prompt-injected) and cannot mutate eval state (so cannot enable cheating).**

This is a provable boundary and the pattern to document for oversight monitors that only need structural/behavioral signals (tool-usage patterns, loop detection, token/resource anomalies, cancel-on-anomaly). It supports a genuinely valuable tier of oversight that *cannot be turned*.

**The read-only leg is a requirement, not a nice-to-have — the mutation endpoints are a direct cheating lever.** Even a metadata-only monitor with no log/fs access can materially alter scoring if it retains the mutation surface. The scoring-integrity core:

- **`POST .../sample/requeue`** — re-runs a flagged/errored sample; the final log and counters reflect the *fresh* outcome, so this can erase evidence of misbehavior or manufacture extra attempts. The sharpest lever.
- **`POST .../sample/cancel`** — `action=score` scores partial work; `action=cancel` records it as not-an-error — either escapes a bad outcome.
- **`PATCH /config` / `PATCH /tasks/{id}/config`** — bump `max_retries`, relax `attempt_timeout`, or change concurrency → more attempts / friendlier conditions.
- **`POST /pause` · `/resume` · `/models/pause` · `.../task cancel` · `/release` · `/keep` · `.../log-flush`** — timing manipulation, early termination, and run-lifetime control.

**Read-only ctl access is not expressible today.** The peer-UID check is app-wide by design (see the access model above: reads share the same trust model as the mutations), there is no per-route capability or token auth, and any client that can reach the socket can call all the mutation routes. Reaching the socket = full read **and** write. Delivering a read-only monitor therefore needs a new mechanism. Cleanest fit with the existing filesystem-permissions-are-the-boundary model:

> **A separate read-only socket** — bind a second AF_UNIX socket whose app mounts only the GET routes, and grant the untrusted monitor a path to *that* socket only; trusted operators (the `inspect ctl` CLI) keep the full read+write socket. Since an isolated monitor's environment is provisioned deliberately, handing it the read-only socket and nothing else is straightforward.

Alternatives — capability/token auth on the single socket, or a GET-only filtering proxy — are heavier and less aligned with the current uid/filesystem trust model.

The important dual conclusion: **the ctl content gate is only as strong as the monitor's weakest content path.** If the monitor retains direct log/fs access, metadata-default ctl buys little (it reads content from the logs instead). So the content gate must be designed alongside the monitor's log/fs capabilities, not in isolation. Monitors that *do* need semantic content oversight are accepted as the injectable class and mitigated differently (sandboxing, capability limits, human-in-the-loop).

**Caveats:**

- *Metadata is not yet a perfectly clean trust boundary.* Some "metadata" is still attacker-influenced free-ish text — tool-call `function` names are model-chosen strings, `info.source`, error class names. Low-bandwidth, but for a *provably* uninjectable tier these should be constrained/escaped too. And `scores` reach default readers even though a custom scorer can embed extracted agent text in a score value — scores are the core signal a monitor exists to read, so they stay ungated: a documented caveat rather than a withheld field.
- *This is least-privilege, not an anti-injection mechanism for content readers.* It does not protect a monitor that opts into content — that monitor still needs the bytes and is still injectable. It shrinks the default attack surface and makes content exposure an explicit, auditable choice.
- *Not a substitute for the Vector 2 sanitization.* For the human-operator terminal vector, sanitization is the right fix; content-hiding would degrade the primary interactive use ("what did the model actually say") without closing the escape (escape sequences can ride in metadata such as `function` names).

## Residual risk and the limits of content monitoring

Everything above bounds what a compromised monitor can *do*; none of it addresses the floor of the analysis: **for any monitor that reads content, prompt injection can neutralize it**, and that failure mode is untouched by read-only access, metadata-defaults, or mutation least-privilege.

A neutralized monitor fails as a **false negative** — it silently declines to flag the thing it is watching for. The injection does not need the monitor to *act* ("cancel this sample"); it only needs it to *not act* ("this transcript is benign, nothing to report"). No mutation, no log access, no capability of any kind is required to fail to raise an alarm. So the content-reading monitor is, irreducibly, a **probabilistic detection layer — not a security boundary** — against an adversary who controls the content it reads. Stating this outright matters, so "we have a monitor" is not read as closing a risk it only reduces.

Two things keep this from being a dead end:

- **The read-only + no-mutation leg's real payoff is evidence preservation, not just blast-radius reduction.** A neutralized monitor produces a false negative — but the incriminating transcript *survives in the logs*, precisely because the monitor was denied `requeue` / `cancel` / mutation and so cannot erase or re-run the evidence away. The failure degrades from "detection defeated, evidence gone" to "*live* detection defeated, evidence intact and recoverable." That makes a **trusted out-of-band pass** (offline, a different model, or human review over flagged-or-sampled transcripts) a viable integrity backstop.
- **The uninjectable metadata tier is the only live layer with integrity under this threat.** Structural/behavioral detection (tool-call patterns, resource anomalies, loop detection, timing) never reads attacker content, so injection cannot turn it. It cannot do *semantic* detection — but whatever oversight can be expressed structurally is oversight the agent cannot talk its way out of.

**The layered picture that follows:**

1. **Uninjectable metadata monitor** — live, cannot be turned, limited to structural signals.
2. **Content-reading monitor(s)** — live semantic triage, *injectable*. Harden probabilistically — ensemble diverse models/prompts so one injection must defeat all at once; deny final authority (flags advise, they do not adjudicate); consider canary / tripwire content to detect a broadly-compromised monitor — but never treat as robust.
3. **Trusted out-of-band review** — the actual integrity backstop, made viable by the read-only / no-mutation evidence-preservation guarantee.

**Bottom line:** a content monitor is a probabilistic detection layer, not a security boundary. The security boundary is the uninjectable metadata tier + evidence preservation (read-only, no mutations) + trusted retrospective review.
