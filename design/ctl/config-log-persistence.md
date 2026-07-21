# Persisting `ctl config` changes in the eval log

> **Status: phases 1–2 implemented** (schema + read path + control-channel wiring, and the `--reason`/`--author`/`persisted` surface polish; viewer rendering lives in the viewer repo). Phases 3–4 (per-sample limit knobs, consumer policy) remain future work. Design for [meridianlabs-ai/inspect_ai#82](https://github.com/meridianlabs-ai/inspect_ai/issues/82). Builds on the shipped `inspect ctl config` surface described in [control-channel.md](control-channel.md) (phase 3).

## Problem

`inspect ctl config` retunes a running eval's launch configuration mid-flight — concurrency caps, log-buffer parameters, the retry-loop overrides, and (planned) the per-sample time / token / message limits. Every one of these changes is applied **purely in memory**: concurrency knobs resize live limiter objects (`src/inspect_ai/_control/limits.py`), the retry knobs land in a process-global override dict (`src/inspect_ai/model/_generate_overrides.py`), and the buffer knobs reconfigure the live recorder. All of it is deliberately reset at the outermost run boundary (`reset_run_registries()` in `src/inspect_ai/_control/eval_state.py`) and none of it is written anywhere durable.

Meanwhile the eval log records the *launch* values of these same settings — `EvalSpec.config` (an `EvalConfig`) and `EvalSpec.model_generate_config` (a `GenerateConfig`) are serialized into the log header at eval start and carried verbatim into the final header at finish. The result is a log that silently misdescribes the run: an eval that spent its last six hours at `--max-connections 5` (throttled through a provider incident) or under a raised `--time-limit` reads, forever, as if it ran start-to-finish at its launch values. That misleads every after-the-fact consumer — a human reading the log in the viewer, `eval_retry` re-applying the recorded config, an agent diagnosing why throughput changed halfway through, anyone auditing what limits a sample actually ran under.

The issue's scope qualifier — *"if they're recorded in the log originally"* — draws the line this design keeps: a `ctl config` change should be persisted in the log **when the knob it changes has a recorded counterpart in the log's launch config**. Knobs with no recorded counterpart (today, only `--key`) stay ephemeral.

## Knob inventory: what's retunable, and what the log records

The full set of `ctl config` knobs is the `_KNOB_SCOPE` table in `src/inspect_ai/_cli/ctl.py` (each with a scope and a min-server-version in `_KNOB_SINCE`), plus the per-sample limits planned in [control-channel.md](control-channel.md) ("Modify per-sample limits" rides `PATCH /tasks/<task-id>/config` as further config knobs).

| Knob | Scope | Recorded in the log? | Recorded where |
|---|---|---|---|
| `--max-samples` | task | yes | `EvalConfig.max_samples` |
| `--max-sandboxes` | process | yes | `EvalConfig.max_sandboxes` |
| `--max-subprocesses` | process | yes | `EvalConfig.max_subprocesses` |
| `--max-connections` | process | yes (approximately — see below) | `GenerateConfig.max_connections` (`EvalSpec.model_generate_config`, `EvalPlan.config`) |
| `--key NAME LIMIT` | process | **no** | — (a named `concurrency()` registry entry, defined in user/solver code; the log has no field for it) |
| `--log-buffer` | task | yes | `EvalConfig.log_buffer` |
| `--log-shared` | task | yes | `EvalConfig.log_shared` |
| `--timeout` | process | yes | `GenerateConfig.timeout` |
| `--attempt-timeout` | process | yes | `GenerateConfig.attempt_timeout` |
| `--max-retries` | process | yes | `GenerateConfig.max_retries` |
| `--time-limit` (planned) | task | yes | `EvalConfig.time_limit` |
| `--token-limit` (planned) | task | yes | `EvalConfig.token_limit` (+ `token_limit_type`) |
| `--message-limit` (planned) | task | yes | `EvalConfig.message_limit` |

Natural extensions of the planned per-sample set — `turn_limit`, `working_limit`, `cost_limit` — also have `EvalConfig` fields and would join the table if/when they become retunable. Keep-alive intent (`ctl process keep` / `release`) is technically config too but has no recorded field and no bearing on how the eval ran; out of scope.

So: **every current and planned knob except `--key` has a recorded counterpart**, and the counterparts split across exactly two recorded objects — `EvalConfig` and `GenerateConfig`.

Two mappings deserve a caveat:

- **`--max-connections` is a knob over live controllers, not a config field write.** On the adaptive-connections path it retunes each `AdaptiveConcurrencyController`'s scaling ceiling; the recorded `GenerateConfig.max_connections` is a per-model launch value and a process may host several models with different configs. The recorded field is the knob's closest counterpart, not an exact alias. A retune restricted with `--model` never touched the other models' controllers, yet its record fans out to every live task log — so the filter is stamped into the record (`provenance.metadata["max_connections_model"]`), letting a reader distinguish a filtered retune from a global one before trusting the folded value for a given log's model.
- **The retry knobs are consulted at point-of-use, not merged into any `GenerateConfig`** (`_generate_overrides.py`), and they're deliberately excluded from eval-set task identity (`_GENERATE_CONFIG_FIELDS_TO_EXCLUDE` in `src/inspect_ai/_eval/evalset.py`).

Both caveats push the same direction: persist changes as **records of what was retuned**, not as rewrites of the recorded config objects.

## What the log can record today

The log has no mechanism for this. The relevant facts (see `src/inspect_ai/log/_log.py` and `src/inspect_ai/log/_recorders/`):

- **`EvalConfig` is written once and never mutated.** It's constructed at eval kickoff, written into `_journal/start.json` (`LogStart{version, eval, plan}`) by the `.eval` recorder's `log_start`, and re-serialized verbatim into `header.json` at `log_finish`. The JSON recorder holds the whole `EvalLog` in memory and serializes on flush; same story.
- **There is no eval-level event stream.** The transcript is strictly per-sample (`Transcript` is instantiated once per sample); `SampleLimitEvent` and friends land in `EvalSample.events`. `EvalLog` has no `events` field, and an ordered eval-level lifecycle log is explicitly deferred in control-channel.md.
- **The one sanctioned post-write mutation channel is `EvalLog.log_updates: list[LogUpdate]`** (`src/inspect_ai/log/_edit.py`) — append-only groups of `TagsEdit` / `MetadataEdit` with `ProvenanceData` (timestamp / author / reason / metadata), applied post-hoc to a finished log via `edit_eval_log()` + `write_eval_log()`, with header-only in-place rewrite support in both recorders. It covers tags and metadata only.
- **The `.eval` journal is the append-during-run mechanism.** Samples and per-flush summary files (`_journal/summaries/{n}.json`) accumulate inside the zip while the run is live; `read_eval_log` on an in-progress log reconstructs a header from `start.json` plus the journal.

So we need a new recorded structure. The design below adds one, following the two existing precedents: an append-only, provenance-carrying update list (the `log_updates` shape) persisted via the journal-file pattern (the summaries shape).

## Requirements

1. **The launch record stays pristine.** `eval.config` and `eval.model_generate_config` must continue to record what the eval was *launched* with, unchanged. This is not just a provenance nicety: `task_identifier()` (`_eval/evalset.py`) hashes the logged plan config and per-sample limit fields (e.g. `eval.config.message_limit`) to pair logs with tasks across eval-set retries — mutating recorded config in place could silently unpair a log from its task. Note that **no currently-shipped knob feeds task identity**: the retry/connection knobs (`timeout`, `attempt_timeout`, `max_retries`, `max_connections`) are all in `_GENERATE_CONFIG_FIELDS_TO_EXCLUDE`, and the concurrency/buffer knobs live on `EvalConfig` fields that `task_identifier` never hashes (only the six per-sample limit fields are pulled into the hash). The identity concern becomes load-bearing only with the *planned* per-sample limit knobs (`--time-limit`, `--token-limit`, `--message-limit`), which are hashed directly — so this requirement is belt-and-suspenders today and non-negotiable from phase 3 on.
2. **Changes are recorded with provenance and order.** Who/when/why, old and new value, appended chronologically. A knob can change several times in one run; all changes are kept, not just the last.
3. **Crash-durable on the same terms as sample data.** A change should survive a process crash to the same extent completed samples do — i.e. it rides the journal, not only the finish-time header.
4. **The record never blocks the retune.** Applying the knob is the control action; persisting it is bookkeeping. A log-write failure degrades to a warning (matching the control channel's "bind failures are never fatal" stance), it doesn't fail the PATCH.
5. **Readable header-only.** Consumers (viewer, `inspect log`, agents) must see the updates without reading samples.
6. **Scope-faithful.** A process-scoped change affects every task in the process; each affected task's log records it. A task-scoped change lands only in that task's log.

## Design

### Record shape

A new module (natural home: alongside `_edit.py`, e.g. `src/inspect_ai/log/_config_update.py`):

```python
class ConfigValueChange(BaseModel):
    """One knob's value change within a config update."""

    config: Literal["eval", "generate"]
    """Which recorded config object the knob shadows (EvalConfig or GenerateConfig)."""

    name: str
    """Field name in that object (same spelling as the ctl knob: "max_samples", "timeout", ...)."""

    value: JsonValue
    """New value. May itself be None where None is a meaningful setting for the
    knob (e.g. a time_limit of None lifts the limit entirely)."""

    cleared: bool = False
    """True when the override was removed (the retry knobs' `clear`) — the knob
    reverts to its launch value and `value` carries no meaning (set to None)."""

    previous: JsonValue
    """Effective value before this change (informational, best-effort — see below)."""


class ConfigUpdate(BaseModel):
    """A group of config changes applied together, sharing provenance."""

    changes: list[ConfigValueChange]

    scope: Literal["task", "process"]
    """Blast radius of the PATCH that carried the changes."""

    provenance: ProvenanceData
    """Reuses the log-edit provenance shape: timestamp, author, reason, metadata."""
```

Notes on the shape:

- **One `ConfigUpdate` per applied PATCH request *per scope***, mirroring how `LogUpdate` groups the edits of one `edit_eval_log` call. A single `ctl config --max-samples 4 --log-buffer 20` invocation is one record with two changes. A PATCH that mixes task- and process-scoped knobs (e.g. `--max-samples` + `--timeout` on the task route) writes one update per scope, sharing provenance: a single `scope` field can't describe both, and the fan-out differs (the task update goes only to that task's log; the process update to every live log).
- **`config` + `name` rather than a closed enum of knobs.** The knob vocabulary grows with phases (the per-sample limits are next); a string field with the "same spelling as the launch flag" convention (already the ctl surface's unifying rule) means no schema change per knob. A `token_limit` retune that also carries `token_limit_type` is just two changes in one update.
- **`cleared` is an explicit flag rather than overloading `value: None`.** For nullable knobs, None is itself a meaningful target — once the per-sample limits become retunable, `time_limit=None` means *unlimited*, which the effective-config fold must distinguish from "revert to the launch value of 3600". A separate boolean keeps both representable: `value: None, cleared: false` sets the knob to null; `cleared: true` removes the override.
- **`previous` is the previous *effective* value, best-effort.** For a knob changed earlier in the run it's the prior override; for a first change it's the launch value where one exists (`--key`-style knobs are out of scope, so it always does). It exists so a human or agent reading the record sees `5 → 20` without replaying history; it is informational, never used to compute effective config (the fold below uses launch values + ordered updates only).
- **Provenance**: `author` follows the convention inspect_flow's tag/metadata steps already use for `log_updates` provenance (`inspect_flow/_steps/tag.py`): a new optional `--author` flag on `ctl config`, defaulting to the git identity (`git config user.name` + `user.email`, rendered `Name <email>`) and falling back to the OS username. Resolved **client-side** by the ctl CLI (the server process has no view of who invoked it) and forwarded on the PATCH. `provenance.metadata` carries record-specific annotations: currently the model filter of a filtered `--max-connections` retune (`max_connections_model`, see the caveat above) and the `inherited: true` marker on catch-up copies recorded into logs that started after the retune. A matching optional `--reason` flag — also forwarded as a query param — flows into `provenance.reason`, so agents (and humans) can annotate *why* a retune happened ("provider incident", "throttling for overnight run"). Dry-run PATCHes apply nothing and record nothing. An explicit `--author`/`--reason` on a pure read (no set option) hard-errors client-side — there is no change to annotate, and silently dropping the values would hide a forgotten knob. The same gate applies when every set option is recordless (`--key`, whose changes deliberately have no logged counterpart — see the knob table above): the retune would apply but the provenance would vanish, so the CLI hard-errors rather than silently dropping it.

### Where it lives in the log: `EvalLog.config_updates`

A new top-level field on `EvalLog`, adjacent to its closest relative:

```python
config_updates: list[ConfigUpdate] | None = Field(default=None)
"""Mid-run configuration changes applied via the control channel (inspect ctl)."""
```

- Placed next to `log_updates` in the field order (the order is load-bearing for serialization — see the warning at the top of `EvalLog`).
- `None` default keeps every existing log parsing unchanged and keeps the field out of serialized output for the overwhelmingly common no-retune case (matching `log_updates`).
- Header-only reads pick it up for free in the `.eval` path (`header.json` is the whole `EvalLog` minus samples); the JSON streaming header reader (`_read_header_streaming` in `_recorders/json.py`) adds `config_updates` to its scanned top-level keys, exactly as `log_updates` is handled.

Why `EvalLog` rather than `EvalSpec`: the spec is the immutable descriptor written into `start.json` at eval start — putting a grows-during-the-run list inside it would either force `start.json` rewrites or leave the spec's serialized forms inconsistent with each other. `EvalLog` is where the run's mutable outcome state already lives (`status`, `results`, `error`, `log_updates`).

### Persistence path

**`.eval` recorder** — follow the summaries journal pattern. (Why journal rather than rewrite a header member on each change: there is no `header.json` mid-run — its presence is what marks a log as finished in the read path — and zip members are immutable once written, so any mid-run "rewrite" of `start.json` would mean duplicate entries and dead bytes. Appending journal files is the format's native mid-run write.)

- A new recorder method (e.g. `log_config_update(eval: EvalSpec, update: ConfigUpdate)`) appends `_journal/config_updates/{n}.json` (one file per update; updates are rare — a handful per run at most — so per-update files beat batching, and the write happens immediately rather than on the sample-flush cadence).
- `log_finish` consolidates the accumulated updates into `header.json`'s `config_updates` field (the same consolidate-at-finish move summaries make into `summaries.json`).
- The in-progress/crashed-log read path (`start.json` fallback in `_read_header`/`_read_header_async`) additionally reads `_journal/config_updates/*` — so a crashed run's header still reports the retunes, satisfying requirement 3.

**JSON recorder** — the in-memory `EvalLog` gains the update via the same recorder method; it hits disk at the next `flush`/`log_finish` like everything else in that format. (Weaker crash durability than `.eval`, consistent with the format's general story.)

For **remote logs** (`log_shared` / S3), journal writes ride the existing sync machinery; a crash can lose the un-synced tail exactly as it can for sample data. No new guarantees invented.

### Wiring from the control channel

The PATCH handlers in `src/inspect_ai/_control/server.py` / appliers in `_control/limits.py` are the single choke point where changes happen, and they run on the eval's own event loop — so they can reach the live `TaskLogger` directly (the `log_buffer`/`log_shared` knobs already do, via `state_buffer_config` on the latest attempt's logger in `_control/buffer.py`). The flow:

1. **Apply first** (exactly as today — resize the limiter, set the override).
2. **Build the `ConfigUpdate`** from what was *actually applied*. The appliers already distinguish applied vs. no-op vs. warn-and-skip (e.g. "no adjustable limiter for this knob"); only applied changes are recorded. A PATCH that changes nothing (idempotent re-send of the current value) records nothing — mirroring `edit_eval_log`'s no-op filtering.
3. **Record**: task-scoped changes → that task's live logger. Process-scoped changes → **every task logger currently active in the process** (each affected log gets the record; `scope: "process"` in the record tells a reader the change wasn't specific to this task).
4. **Failures degrade**: a recording error logs a warning and the PATCH still succeeds; the JSON result envelope gains a `persisted: bool` per applied knob so callers (and `--json` agents) see when the log write didn't happen.

**Inheritance by work that starts later in the same run.** Process-scoped state outlives individual attempts and eval-set children: a task retried after a `--timeout` override, or the next sequential eval-set child, still runs under the override — but its fresh log would otherwise show no trace. Fix: keep the run's accumulated process-scoped `ConfigUpdate` list in the control channel's run-scoped state (`_control/eval_state.py`, reset by `reset_run_registries()` alongside the registries whose lifetime it must match); each `TaskLogger` keeps a watermark into that list and records the copies it hasn't yet captured (original provenance/timestamps preserved — the records say when the change really happened, which can predate this log's own record of it; the copies are marked explicitly via `provenance.metadata`). The catch-up runs at two points bracketing the gap between "logger exists" and "logger is a live fan-out target": at `TaskLogger.init()` (retunes that predate the log — a retry attempt or a later eval-set child), and at task start immediately before `register_eval` — necessary because a run's initial loggers are all init()ed up front in `prepare_options` while retunes fan out only to registered evals, so a task queued behind `--max-tasks` would otherwise never record a retune applied while it waited even though the process-global override governs it. Ordering the catch-up before `register_eval` closes the window: both run on the eval's single event loop and `register_eval` is sync, so no retune can land in between. Task-scoped knobs need no equivalent: `max_samples` retunes target the task's live semaphore, and a fresh attempt re-reads launch config.

### Reading it back: effective config

`eval.config` stays the launch record; the *effective* final values are a fold. Provide helpers rather than making every consumer reimplement the overlay:

```python
def effective_eval_config(log: EvalLog) -> EvalConfig: ...
def effective_generate_config(log: EvalLog) -> GenerateConfig: ...
```

Each returns a copy of the launch object with `config_updates` applied in order (a `cleared` change restores the launch value; a `value: None` change sets a nullable knob to null, e.g. lifting a time limit). The `--max-connections` caveat above is documented on the helper: for that knob the folded value is the retuned ceiling, which is the honest answer to "what was it running at" even though the launch field is per-model.

Consumers, and what changes for them:

- **`eval_retry`** (`_eval/eval.py`) re-applies ~30 fields from `eval_log.eval.config`. **Phase 1 deliberately does not change its behavior** — it keeps using launch values. Whether a retry should inherit retunes is a genuinely two-sided question (a raised `--time-limit` was probably a considered correction the retry should keep; a `--timeout` bump to ride out a provider incident probably shouldn't outlive the incident), and per-sample limit fields feed `task_identifier`, so folding retunes into retry config interacts with eval-set pairing. Recording first, unchanged behavior, gives us the data to decide with; a `--use-final-config` style opt-in (or per-knob policy) is a follow-up once the records exist.
- **Viewer / `inspect log`**: surface `config_updates` in the info panel ("config changed during run", old → new, when, why) and optionally badge folded values. Follow-up work in the viewer repo; the header field is all it needs.
- **`ctl config` view**: the live view already reports current effective values; once persistence lands it can also report whether the last change was persisted.
- **Sample-level interpretation** (matters once the per-sample limits become retunable): a sample's effective limits are determined by which updates predate its start. Samples already record some effective values directly (`EvalSample.token_limit` / `token_limit_type`); for the rest, the timestamped update list against sample start times is the disambiguator. If per-sample limit retunes land with "applies to samples not yet started" semantics (the control-channel plan), consider also stamping the remaining effective limits onto each sample at start, which is more direct than timestamp arithmetic — but that's an extension of the sample record, separable from this design.

## Compatibility

- **Old logs, new reader**: `config_updates` defaults to `None`; nothing to migrate.
- **New logs, old reader**: an optional extra top-level key. Same exposure class as any additive header field (e.g. `log_updates` when it landed); no `LOG_SCHEMA_VERSION` bump — the schema version marks structural breaks, not additive optional fields.
- **Control-channel version skew**: recording is server-side behavior, invisible on the wire, so no `CONTROL_API_VERSION` bump for persistence itself. The `--reason` and `--author` flags *are* new query params an older server's strict check would reject — they get a `_KNOB_SINCE`-style gate (or simply ship with the next knob that bumps the version anyway). The `persisted` field in the result envelope is additive and null-guarded per the wire-envelope conventions.

## Alternatives considered

**A. Mutate the recorded config in place** (rewrite `eval.config.max_samples` in the header when the knob changes). Rejected: destroys the launch record (requirement 1), loses multiplicity and provenance, and — decisively — the recorded config feeds `task_identifier`, so an in-place mutation could unpair a log from its eval-set task (not an issue for any knob shipped today — see the requirement 1 note — but it would become one the moment the per-sample limits are retunable). It would also require rewriting `start.json` mid-run, which the journal format treats as immutable.

**B. Ride `log_updates` with a new `ConfigEdit` edit type.** Tempting — provenance, append-only semantics, and header-rewrite machinery all exist. Rejected, decisively, on backward compatibility: `LogEditType` is a *discriminated union* (`_edit.py`), so an old reader parsing a new log whose `log_updates` contains a `type: "config"` entry hits a pydantic validation error and the **entire log read fails** — every retuned log would be unreadable by older inspect versions. A new optional top-level field is the opposite: unknown fields are silently ignored, so old readers degrade gracefully (see Compatibility). Reuse also buys less than it appears — the genuinely new machinery (mid-run journal write, crash-fallback read, finish-time consolidation) doesn't exist for `log_updates` (which is written by post-hoc header rewrite on finished logs) and would have to be built either way. And the lifecycles genuinely differ: `log_updates` is the *post-hoc, user-initiated* edit channel for finished logs (`edit_eval_log` validates against and updates the log's current tags/metadata state, and `recompute_tags_and_metadata()` folds edits into the live fields — a fold we specifically must *not* perform on `eval.config`). Config updates are written *by the running eval about itself*, journaled mid-run, and must never rewrite the fields they shadow. Wedging both into one list means every consumer of either filters out the other, `ConfigUpdate.scope` has no `LogUpdate`-level home, and it would invite a post-hoc "edit a finished log's config" capability nobody wants. A sibling field with a shared `ProvenanceData` shape keeps the symmetry without the entanglement; if the viewer ever wants a single "everything that changed" timeline, it can merge the two lists on timestamp.

**C. An eval-level event stream** (a `ConfigUpdateEvent` in an eval-scoped transcript). The most general answer — and a rearchitecture this feature doesn't need. There is no eval-level transcript today; control-channel.md explicitly defers an ordered eval-level lifecycle log. A handful of config records per run doesn't justify building one; if an eval-level event stream ever lands, `config_updates` migrates into it naturally (the record shape is already event-like: timestamped, ordered, typed).

**D. A sidecar file next to the log** (e.g. `<log>.updates.json`). Rejected: logs are copied, moved, and served (S3, `inspect view` bundles) as single files; a sidecar detaches in every one of those flows. The `.eval` format exists precisely so run artifacts travel as one zip.

## Phasing

1. **Schema + read path**: `ConfigValueChange` / `ConfigUpdate`, `EvalLog.config_updates`, recorder method on both recorders, journal write + finish-time consolidation + crashed-log fallback read, `effective_*_config` helpers. Wire the *existing* knobs (concurrency, buffer, retry overrides) through the PATCH handlers, including the process-scope fan-out and the run-scoped inheritance snapshot.
2. **Surface polish**: `--reason` and `--author` on `ctl config` (author defaulting to git identity per the flow convention), `persisted` in the result envelope, viewer rendering of `config_updates`.
3. **Per-sample limits**: when `--time-limit` / `--token-limit` / `--message-limit` retuning lands (control-channel phase 3 remainder), it plugs into the same recording path from day one — this design is a prerequisite worth landing first, so those knobs never ship with an unrecorded window.
4. **Consumer policy follow-ups**: whether/how `eval_retry` and eval-set adopt effective values (per-knob), sample-start limit stamping.

## Open questions

1. **Should `eval_retry` ever fold retunes in automatically?** Deferred (see above) — needs the records to exist first, and likely wants per-knob policy (per-sample limits: probably yes; incident-response retry knobs: probably no).
2. **Verified author identity.** `author` follows the flow tag-step convention (see Record shape): `--author`, defaulting to client-side git identity, falling back to OS username — a client-asserted claim, not an authenticated principal. AF_UNIX + `SO_PEERCRED` could add a verified uid to provenance (e.g. in `metadata`) when the future write-endpoint hardening lands (control-channel security model).
3. **Programmatic (non-ctl) mutation.** If a Python `ControlClient` or future in-process API mutates the same knobs, it should flow through the same appliers and therefore the same records — worth asserting with a test so no second, unrecorded path grows.
