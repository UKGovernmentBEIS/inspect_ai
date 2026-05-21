# Inspect Checkpointing — Implementation Phasing

> Companion to [checkpointing-working.md](./checkpointing-working.md). The
> design doc establishes *what* we're building; this doc proposes the
> order we'll build it in.

## Principles

- **Each phase closes a loop end-to-end** so we get real roundtrip
  testing rather than a half-built dead end.
- **Latent merges are fine** when they shrink risk and let us land
  scaffolding under review before the heavy machinery follows.
  Phases 1 and 2 are intentionally latent (no customer-visible
  behavior on their own).
- **Front-load the simpler half.** Host-only checkpointing stabilizes
  the format and the resume harness before the sandbox-side novelty
  (restic injection, egress protocol, privilege model) lands on top.

## Phase 1 — Restic acquisition

**Status:** Done.

**Plan sections covered:** §4c.

**What landed:**

- `src/inspect_ai/util/_restic/` is the use-case-agnostic restic
  utility package — generic across consumers (today only checkpointing
  + the prefetch CLI):
  - `binary.py` — `Platform` literal, `current_platform()`, async
    `resolve_restic(platform)`, `cache_path()`. Pinned version in
    `version.txt` (currently `0.18.1`).
  - `summary.py` — `ResticBackupSummary` pydantic model + `_parse_summary`
    (parses the final JSON line of `restic backup --json`).
  - `ops.py` — thin async wrappers over the restic CLI:
    `init_repo`, `run_backup` (accepts `str | Sequence[str]` for
    sources, takes a `tag` parameter), `restore_repo`, plus the
    shared `restic_env` env-builder.
- Cache lives at `platformdirs.user_cache_path("inspect_ai") / "bin/"`
  (handles `$XDG_CACHE_HOME` on linux/mac and `%LOCALAPPDATA%` on
  windows automatically).
- Download path: urllib + bz2 / zipfile, atomic `os.replace`,
  SHA256 verification against fetched `SHA256SUMS`. Fail-fast on any
  error (no retries, no locking). Sync work wrapped in
  `anyio.to_thread`.
- Hidden CLI command `inspect download restic` (no flags) that
  fetches every supported platform. Idempotent: prints "downloaded" or
  "already cached" per platform, then a summary table. Hosted under a
  hidden `inspect download` group so future binary downloads can slot
  in alongside without namespace churn. Hidden via click `hidden=True`
  so it doesn't appear in `--help` until checkpointing itself is
  exposed.
- Unit tests at `tests/util/test_restic_binary.py` covering cache
  hit, cache miss + populate, and SHA256 mismatch. No network.
- Decisions deliberately deferred: file locking, retry, macOS xattr
  stripping, cache cleanup CLI.

**Why first:** every later phase depends on it; risk was contained (no
inspect runtime semantics changed); the hidden CLI gives an easy
verification surface.

## Phase 2 — Checkpointer skeleton (no I/O)

**Status:** Done.

**Plan sections covered:** §2 (`CheckpointConfig` + policy types),
partial §3 (built-in support primitives).

**What landed:**

- `src/inspect_ai/util/_checkpoint/`: subpackage with
  `CheckpointConfig`, all six policy types (`TimeInterval`,
  `TurnInterval`, `TokenInterval`, `CostInterval`, `BudgetPercent`,
  and the `"manual"` literal), `Retention`, the `checkpointer()`
  async-cm factory, and the `Checkpointer` Protocol that the yielded
  session implements. The factory dispatches to a no-op or active
  session impl on entry; later phases swap implementations
  underneath.
- `tick()` consults the policy and decides whether the iteration is a
  checkpoint moment; firing is a **no-op** (counter and timestamp
  resets only). Active session is tracked via a
  `contextvars.ContextVar` so free helpers can locate it without
  explicit plumbing.
- `tick()` implements `TimeInterval`, `TurnInterval`, and `"manual"`
  policies. `TokenInterval` / `CostInterval` / `BudgetPercent` raise
  `NotImplementedError` at session construction (scheduled for
  Phase 6).
- `cp.checkpoint()` on the yielded session forces a fire regardless
  of policy.
- 10 unit tests (`tests/checkpoint/test_checkpointer.py`) covering
  all policies, fire counts, mocked-time semantics,
  NotImplementedError paths, and the outside-context error case.
  No I/O.

**Why this carve-out:** locked the agent contract and the public type
surface before the heavy machinery lands on top of it. Pure policy
tests caught subtle threshold semantics in isolation. The state
ownership question (`TaskState` vs. context var) settled in favor of
context var.

## Phase 2.5 — React agent wiring + sample identity capture

**Status:** Done.

**Plan sections covered:** the agent-wiring half of §3.

**What landed:**

- `react()` and `react_no_submit()` enter `checkpointer()` (zero-arg)
  around the agent loop and call `await cp.tick()` per iteration.
  Conversation messages are tracked by the agent itself via
  `state.messages = cp.track("messages", lambda: state.messages,
  state.messages)`. Config is ambient: the harness installs the
  resolved `CheckpointConfig` on `ActiveSample.checkpoint` before the
  agent runs, and the factory reads `sample_active()` on entry. If no
  config is installed (or no sample is active), the factory dispatches
  to the no-op session.
- `build_impl()` (called by the factory) captures `sample_id`, `epoch`,
  `log_location`, and `eval_id` from `sample_active()` and passes them
  to the active `_Checkpointer` constructor for use by Phase 3's
  `_fire()`.
- `examples/checkpoint_ctf.py`: layered-decoder CTF harness exercising
  the public API surface end-to-end (no real fire yet).

**Deferred (still lands with Phase 3):**

- **Sample-level retry / attempt index in `ActiveSample`.**
  `build_impl()` currently captures `sample_id`, `epoch`,
  `log_location`, and `eval_id`. The retry / attempt index needed to
  disambiguate `<sample-id>__<epoch>_<retry>/` is **not yet captured**
  — `ActiveSample` doesn't expose it. Phase 3 resolves this either by
  adding an `attempt` field to `ActiveSample` (symmetric with `epoch`)
  or by subscribing to `on_sample_attempt_start`. See the TODO in
  `src/inspect_ai/util/_checkpoint/checkpointer_impl.py:build_impl`.

**Why this carve-out:** wiring the agent and capturing identity are
mechanical and reviewable on their own; pulling them forward gives a
runnable harness (`examples/checkpoint_ctf.py`) that exercises the
public API surface before the real I/O lands, and leaves Phase 3 as a
focused swap of `_fire()`'s body plus the read side.

## Phase 3 — Checkpoint write (host + sandbox, end-to-end)

**Status:** Done.

**Plan sections covered:** §1, §4a, §4d, §4e, §4f, §4g, §4h, §5,
§7a, §7b, §8a, §8b, §8c, §8e, Appendix B.

This phase consolidates the write-side of the original Phase 3
(host-only) and Phase 4 (sandbox + egress) — both ended up landing
together because the work fell out that way naturally. Resume
(read-side) is split into the new Phase 4.

**Vocabulary.** The canonical terms are defined in
`src/inspect_ai/util/_checkpoint/UBIQUITOUS_LANGUAGE.md` — **evals
checkpoints dir**, **eval checkpoints dir**, **sample checkpoints
dir**, **sample staging dir**, **context subdir**, **in-sandbox
restic repo**, plus the **sample root** convenience term. Both local
and remote (`s3://`, etc.) destinations are supported.

**Landed (write side):**

- **Layout subpackage.** `src/inspect_ai/util/_checkpoint/_layout/`
  groups everything that knows about where checkpoint state lives on
  disk and what shape each file takes:
  - `eval_checkpoints_dir.py` — eval-dir path computation +
    `log_basename` helper.
  - `sample_checkpoints_dir.py` — `restic-config.json` + `ckpt-*.json`
    checkpoint file I/O, plus `scan_latest_committed_id` (parses-OK
    high→low checkpoint file walker used on resume).
  - `staging_dir.py` — sample staging dir (remote-dest only) + the
    per-sample subdir helpers (`restic_dir`, `host_repo_dir`,
    `sandbox_repo_dir`, `context_dir`, `restic_config_path`,
    `is_remote_destination`).
  - `host_context.py` — the 5-file JSON schema inside the context
    subdir (events, events_data, attachments, store, agent_state),
    with paired read/write.
  - `schemas.py` — pydantic models (`Checkpoint`, `ResticConfig`,
    `SnapshotDetails`) for the on-disk JSON shapes.
  - `__init__.py` is a narrow facade that re-exports only what
    crosses the package boundary
    (`eval_checkpoints_dir`, `eval_checkpoints_dir_from_config`,
    `has_sample_checkpoint`, `sample_checkpoints_dir`). Internal
    callers import the concrete submodule.
- **Host egress + async fs.**
  `src/inspect_ai/util/_checkpoint/_host_egress.py` ships staging-dir
  files to remote destinations (see remote-destination bullet below).
  `_async_fs.py` exposes `async_mkdir` — a thin S3-aware wrapper that
  no-ops on S3 (no directories) and delegates to local `mkdir`
  otherwise; everything else goes through
  `inspect_ai._util.asyncfiles.get_async_filesystem()`.
- **Per-sample restic password in `restic/restic-config.json`.** Each
  sample subtree carries its own `restic-config.json` with a
  `restic_password` field auto-minted at first checkpoint setup via
  `secrets.token_urlsafe`. No eval-level manifest, no shared secret,
  no cross-sample coordination — every sample is independent. On
  retry, the password rides forward via the FS copy at resume (see
  Phase 4).
- **Two-phase checkpointer lifecycle.** `checkpointer()` is the
  agent-facing async-cm; the harness stashes a `_CheckpointerSetup`
  on `ActiveSample` ahead of time, and entering it performs the
  on-disk + sandbox I/O via `hydrate()` and returns a fully-formed
  `_EnteredCheckpointer`. The cached pattern makes re-entry within
  the same sample a no-op. `_NoopCheckpointer` is dispatched when no
  config is installed.
- **Trigger strategy.** `CheckpointTrigger` Protocol in
  `triggers/_base.py`; concrete strategies in `triggers/_manual.py`,
  `triggers/_turn_interval.py`, `triggers/_time_interval.py`. Each
  trigger owns its per-session state (turn counter, time of last
  fire); the entered checkpointer `copy.deepcopy`s the configured
  trigger so each sample session has its own.
- **Restic split.** `src/inspect_ai/util/_restic/` is generic restic
  (Phase 1); `src/inspect_ai/util/_checkpoint/_sandbox_restic/` is
  the checkpoint-specific "restic-in-an-inspect-sandbox" layer:
  - `repo.py` — `inject_restic` (root, mode 0700 path inside the
    container), `init_sandbox_repo`, `run_sandbox_backup`.
  - `egress.py` — `egress_sandbox` + `ingress_sandbox` + the 2-phase
    manifest commit (Appendix B). Imports `restic_env` from
    `_restic/ops.py`.
- **Restic integration is real**:
  - Host: `init_repo` (idempotent — skip if `repo/config` exists)
    runs at hydrate-time against `<sample-root>/restic/host/`;
    `run_backup(restic, repo, password, source, tag)` runs each fire
    and parses restic's `--json` summary into a
    `ResticBackupSummary`. Tag format `ckpt-{N:05d}` is built by
    the checkpointer caller (`_restic_tag` in `checkpointer_impl.py`).
  - Sandbox: `inject_restic` streams the linux binary as root via
    stdin into `/opt/inspect-restic/restic` (parent dir mode 0700,
    invisible to non-root). `init_sandbox_repo` initializes
    `/opt/inspect-restic/repo` once. `run_sandbox_backup` invokes the
    injected binary as root each fire with the same tag.
  - **Sandbox egress** (Appendix B): each cycle, `egress_sandbox`
    runs a phase-1 root exec in the sandbox that diffs current
    `repo/` files against `egress-manifest.txt`, builds an ordered
    tar (`config → keys → data → index → snapshots`) into
    `staging/egress-<tag>.tar`, and emits the new file list. Host
    pulls the tar via `env.read_file`, extracts into the destination
    `<sample-root>/restic/sandboxes/<name>/`, runs
    `restic snapshots --json` against the destination to verify the
    new snapshot id is listed, then phase-2 root exec advances the
    manifest and drops the tarball. Failure between phases leaves
    the manifest unadvanced so the next cycle re-egresses the same
    files. Destination repo is **not** pre-initialized — first
    cycle's tarball carries `config` + `keys/*`, which makes the
    destination valid on extraction.
  - **Host + each sandbox `(backup → egress)` run in parallel** via
    `tg_collect`. Within a sandbox the pair is sequential (egress
    diffs against what backup just wrote); pairs across sandboxes
    and the host backup are independent.
- **Checkpoint file carries per-backup stats** (`host: SnapshotDetails`,
  `sandboxes: dict[str, SnapshotDetails]`) where `SnapshotDetails` =
  `{snapshot_id, size_bytes, duration_ms}`. `size_bytes` comes from
  restic's `data_added_packed` (post-compression on-disk cost);
  `duration_ms` from restic's `total_duration`. Top-level
  `size_bytes` on the checkpoint file is the rolled-up total.
- **Host snapshot: up to five files, condensed + pooled.** The
  context subdir (`<sample-root>/context/`) is overwritten each fire
  by `host_context.write()` with:
  - `events.json` — condensed events; `ModelEvent.input` and
    `ModelEvent.call` messages are replaced with `input_refs` /
    `call_refs` into the pools. **Span-only invariant**: only events
    from the first `span_begin checkpoint` onward are captured —
    pre-first-span new-attempt setup chatter never enters the
    accumulator. Enforced by lazy-initing `_events_consumed` on the
    first `_open_next_span()` to the transcript index where that
    span_begin is about to land.
  - `events_data.json` — `{messages, calls}` dedup pools that the
    refs index into. Built incrementally: each fire processes only
    the new event slice via `condense_model_event_inputs` /
    `condense_model_event_calls` against the session's persisted
    `_msg_index` / `_call_index`, appending new entries. Total
    hashing work over a sample is O(N) rather than O(N) per fire.
  - `attachments.json` — `transcript().attachments`, captured live
    by `Transcript._process_event` as call payloads >100 chars get
    rewritten to `attachment://<hash>` refs. Persisted alongside so
    resume can resolve the refs.
  - `store.json` — `store_jsonable(state.store)`, pulled from
    `sample_state().store`.
  - `agent_state.json` *(opt-in)* — agent-defined property bag.
    The agent registers one or more keyed callbacks via
    `cp.track(key, callback, initial_value)` — a single combined
    affordance that also returns the prior value (or `initial_value`
    when none). Each callback is invoked at fire time and its result
    is stored under its key in the merged dict. Duplicate keys raise.
    File is absent when no callback was registered. `react()`
    registers two callbacks: `"messages"` (the conversation, which
    the protocol no longer privileges as a separate top-level file)
    and `"attempt_count"` (so retries resume at the right attempt).
  All files serialize via `to_jsonable_python(..., exclude_none=True)`.
  `events.json` and `events_data.json` both have a byte-stable prefix
  across fires (only the tail grows), which tightens restic CDC
  dedup beyond what a flat events array would give.
- **Restic-config tuning for the host repo.** Host backup invokes
  restic with `--compression max` (zstd-max ≈ 5–10× ratio on
  JSON-only content vs the default `auto` ≈ 2–3×) and `--no-scan`
  (skips the up-front size-estimate walk; we control the source).
  Sandbox backups keep restic defaults — sandbox content is mixed
  binaries / logs, where `auto` is right.
- **Checkpoint file commit is "parses or doesn't."** The checkpoint
  file write itself is non-atomic. Resume reads the highest
  *parseable* `ckpt-NNNNN.json` (via `scan_latest_committed_id`) as
  the resume point. A mid-write crash costs at most one checkpoint,
  same as crashing before the checkpoint file starts. See §4d.
- **Destination override**: `CheckpointConfig.checkpoints_location`
  repoints the parent root under which the per-eval subdir lands;
  default is the log's directory. The per-eval subdir name strips a
  trailing `.eval` and appends `.checkpoints` (so `foo.eval` →
  `foo.checkpoints/`).
- **Remote (`s3://`, etc.) destinations.** Restic always writes
  locally. When the resolved sample checkpoints dir is remote, the
  fire materializes into a per-sample **staging dir** under
  `inspect_cache_dir("checkpoints")/<log-basename>/<sample>__<epoch>/`
  with the same internal layout as a local sample checkpoints dir
  plus `.egress-manifest.txt`. At the end of each fire, `host_egress`
  (`_host_egress.py`) reads the manifest, diffs against the staging
  dir, ships new files via `AsyncFilesystem` in a safe order
  (`config`/`keys` → `data` → `index` → `snapshots` → `restic-config.json`
  → `ckpt-NNNNN.json`), and atomically advances the manifest. The
  checkpoint file's arrival at the destination is the remote commit
  point. The context subdir and the manifest itself are never
  shipped. Idempotent re-ship is safe (restic content is content-
  addressed; checkpoint files overwrite cleanly). This sidesteps
  restic's narrow AWS auth (no SSO / profile / assume-role) — all
  remote I/O flows through `AsyncFilesystem`, which uses the full
  boto3 credential chain. See
  [checkpointing-remote-dest.md](./checkpointing-remote-dest.md).
- **`max_consecutive_failures` enforcement.** `_fire` wraps the fire
  body (`_fire_once`) so a failed attempt is non-fatal by default: it's
  recorded (structured `InfoEvent` `source="checkpoint"` + a logged
  warning) and the per-session failure counter increments;
  `CheckpointFailureLimitExceeded` re-raises only when the count
  exceeds `max_consecutive_failures` (`None` = unlimited, `N` = fail on
  the (N+1)th, `0` = strict), at which point the sample fails through
  inspect's normal sample-error machinery. A successful fire zeroes the
  counter; the counter is fresh per session. See working.md §8d.

**Still TBD (write side):**

- None — write side is complete.

**End state of Phase 3:** Every checkpoint cycle produces a real,
crash-resumable on-disk artifact for both native and sandbox-CLI
agents on local **and** remote destinations, with bounded failure
tolerance. Phase 4 (resume) reads these artifacts.

## Phase 4 — Resume (read side, all surfaces)

**Status:** Done. End-to-end resume verified locally on the CTF
example (kill mid-eval → `inspect eval retry` → roundtrip).

**Plan sections covered:** §6, §7c (resume integration with retry
machinery), and the read-side complement of §1, §4a, §5, §8a, §8b.

This phase consolidates the read-side that was originally split across
the old Phase 3 (host-only resume) and Phase 4 (sandbox resume). They
share enough machinery (sample-source extension, resume hook, retry
integration) that splitting them produced redundant work; tackled
together they're one coherent body.

The companion design doc
[checkpointing-hydration.md](./checkpointing-hydration.md) covers
the resume hydration design in detail; this section lists what
landed and what remains.

**Landed:**

- **Sample-source `ResumeCheckpoint` variant.** The
  `EvalSampleSource` union now carries a `ResumeCheckpoint` case (in
  addition to fresh and completed). The harness threads it into
  `active_sample(...)` and into `_CheckpointerSetup`, which passes
  it to `hydrate()` for every sample. Fresh samples in a retry eval
  pass `None` and mint their own password without any awareness of
  the surrounding retry.
- **`hydrate()` orchestrator + parallel domain hydration.** Phase 1
  prologue (paths, dirs, `restic/restic-config.json` materialization,
  restic binary, `latest_committed_id` scan); Phase 2 fans out
  `_hydrate_host` and `_hydrate_sandboxes` in parallel via a task
  group. Returns a `HydrationResult` with everything the agent-facing
  `_EnteredCheckpointer` needs at construction. See hydration.md
  §3 for the function structure.
- **Remote-source resume.** The FS copy used at hydrate-time
  (`_fs_copy_cross_cutting` for `restic-config.json` + `ckpt-*.json`,
  `_fs_copy_repo` for the host and sandbox restic repos) goes through
  `AsyncFilesystem`, so a prior eval's sample checkpoints dir can
  live on `s3://` (or any supported scheme) and resume reads it into
  the new sample root just as it would from local disk. When the
  *new* eval's destination is also remote, `seed_manifest()`
  pre-populates `.egress-manifest.txt` from everything just copied
  into the staging dir — without this, the first post-resume fire's
  host egress would treat every downloaded file as "new" and re-ship
  the full resume payload.
- **Orphan-snapshot cleanup.** Both `_hydrate_host` and
  `_hydrate_sandbox` drop any restic snapshot tagged `ckpt-NNNNN`
  with `N > latest_committed_id` from the FS-copied repo before the
  restore / ingress step. This enforces "checkpoint file is the
  commit point" against fires that completed their backup but not
  their checkpoint file (working.md §4d). For sandboxes, the drop runs on the
  host-side repo *before* `ingress_sandbox` tars it into the
  container, so the in-container repo never sees the orphan packs.
- **In-container sandbox restore via `ingress_sandbox`.** Tar the
  host-side sandbox repo in memory, stream the bytes via stdin to a
  root `sh` invocation that extracts into `/opt/inspect-restic/repo`,
  then invoke the injected restic to
  `restic restore latest --target /` so the configured
  `sandbox_paths` land at their original absolute paths. The
  in-container egress manifest is reseeded so the next fire's diff
  treats the inherited snapshots as already-shipped.
- **Span-only `events.json` invariant + `prior_run` wrap.** On read,
  `_hydrate_host` wraps the rehydrated events in a synthesized
  `prior_run N` span (name `checkpoint restore N`, sibling-per-prior-attempt)
  before pushing them into the live `Transcript`. Each resume adds
  one new sibling wrap; events.json after R resumes contains R
  `prior_run` wraps followed by the current session's flat
  checkpoint spans. The wrap is seeded into the accumulator so
  subsequent fires persist the structure. See hydration.md §3b1.
- **Pool / accumulator seeding.** `_EnteredCheckpointer.__init__`
  seeds `_condensed_events`, `_msg_pool`, `_call_pool` (with rebuilt
  `_msg_index` / `_call_index`) from the hydration result.
  `_events_consumed` is lazily set by the first `_open_next_span()`
  to the transcript index where `span_begin checkpoint M+1` is about
  to land — so new-attempt setup chatter is excluded from the
  accumulator and events.json stays span-only.
- **Resume-shape validation.** `_validate_resume_state` runs after
  the push and raises if any invariant fails (first event is
  `span_begin checkpoint restore 1`, sequential checkpoint + wrap names,
  paired begin/end by id, checkpoint count matches
  `latest_committed_id`, checkpoint file parity, `CheckpointEvent`
  count matches `latest_committed_id` with sequential
  `checkpoint_id`s). Console-logs a readable summary either
  way under `[hydrate.validate]`.
- **Per-sample restic password from `restic/restic-config.json`.** Each
  sample carries its own password in `restic/restic-config.json`; the
  FS copy at resume
  preserves it so the new sample dir's restic repos unlock with the
  same password. There is no eval-level shared secret.
- **`Checkpointer.track` resume plumbing.** `track(key, callback,
  initial_value, *, value_type=None)` returns the persisted value
  on resume. Deserialization is auto-handled for single Pydantic
  `BaseModel` instances (`type(initial_value).model_validate(raw)`)
  and JSON primitives (`int`, `float`, `str`, `bool`, `None`). For
  collections, generics, or anything else with a lossy JSON
  round-trip, the caller passes `value_type=...` and `track` runs
  `TypeAdapter(value_type).validate_python(raw)`. Primitives also
  enforce a type-match check against `initial_value` to catch
  schema drift.
- **`is_resuming` on the agent-facing API.** `Checkpointer.is_resuming`
  exposes the resume signal for the simple "this is a resume" case
  without requiring the agent to look at `TaskState`.

**End state of Phase 4:** A killed eval (native or sandbox-CLI agent)
resumes from the latest checkpoint with full roundtrip fidelity —
messages, events, `Store`, and sandbox filesystem all match the
pre-kill state. Works whether the prior eval's sample checkpoints
dir is local or remote.

## Phase 5 — Observability

**Status:** Partially landed (transcript spans); rest not started.

**Plan sections covered:** §8 (write-side observability surfaces).

Customer-visible signals that checkpointing is happening — for
debugging, monitoring, and ops integration. Deferred out of Phase 3
because they're orthogonal to "the cycle works": every item here
improves visibility, none is required for round-trip correctness.

**Landed:**

- **Per-checkpoint transcript spans.** Each agent-checkpointed
  window is bracketed by a `span_begin/span_end` pair of
  `type="checkpoint"`, `name="checkpoint N"` matching the checkpoint
  file id. Spans are siblings (not nested). On resume, the rehydrated
  spans are wrapped in a synthesized `prior_run` sibling span
  (`type="prior_run"`, `name="checkpoint restore N"`). See working.md §8b
  and hydration.md §3b1.
- **`CheckpointEvent` in the transcript / `.eval` log.** Each
  successful fire emits a `CheckpointEvent` carrying the full
  per-checkpoint file contents as flat top-level fields (via
  multiple inheritance from `BaseEvent` + `Checkpoint`).
  Lands in the `.eval` log alongside model and tool events;
  viewable in `inspect view`. Emitted *after* `write_checkpoint_file` so
  the event position is `span_end_N` → `CheckpointEvent_N` →
  `span_begin_(N+1)`. By construction the event is **not** in fire
  N's `events.json`; it **is** captured in fire N+1's. Resume
  reconstructs the trailing event from
  `ckpt-{latest_committed_id:05d}.json` so the rehydrated transcript
  matches a live run. See working.md §8a and hydration.md §3b.
- **Failed-attempt record.** A failed fire emits a structured
  `InfoEvent` (`source="checkpoint"`, `data.event="checkpoint_failed"`)
  into the transcript / `.eval` log and logs a warning — reusing
  existing event types rather than a dedicated failure event. See
  working.md §8a / §8d and the Phase 3 `max_consecutive_failures`
  bullet.

**Still TBD:**

- `on_checkpoint_start` lifecycle hook — extension point for users
  to observe / react at the start of each cycle (e.g. flush
  in-memory state to disk so it lands in the snapshot, gate
  background work that shouldn't be mid-flight when restic
  enumerates the working tree). Symmetric with the existing
  `on_sample_*` hooks.
- TUI indicator — show "checkpoint N saved" / cumulative checkpoint
  bytes in the running-eval view, similar to how token usage shows
  today.

**Why fifth:** Phases 3 + 4 produce the on-disk artifacts and the
roundtrip; Phase 5 makes them legible to humans and external tooling
without changing the write/read contract.

## Phase 6 — Advanced policies + retention + polish

**Plan sections covered:** the remaining bits of §2 (live wiring of
token/cost/budget policies into inspect's existing limit machinery),
§8d.

**Deliverables:**

- `tick()` implementation for `TokenInterval`, `CostInterval`,
  `BudgetPercent` policies — observe inspect's existing
  `token_limit` / `cost_limit` / `time_limit` / `working_limit`
  state and fire on threshold crossings. Phase 2 already shipped the
  types; this phase makes them functional.
- `Retention` field actually enforced (`delete` vs `retain`
  after_eval).
- Any remaining failure-handling polish.
- Documentation handoff to the public docs.

**Why later:** none of these block customer value; they refine the
experience after the core works.

## Phase 7+ — Future capabilities

Not scheduled. Tracked here so they're not lost:

- Mid-tool-call checkpointing (currently a Phase-1 non-goal in the
  plan).
- User-provided encryption password.
- Eval-complete vs sample-complete retention granularity (the §9 open
  question).
- Provider-native snapshot variants (Modal memory snapshots, etc.) if
  and when worth it.

## Notes on this shape

- **Phases 1 / 2 / 2.5 were latent** — scaffolding under review before
  the user-facing machinery followed.
- **Phase 3 is the biggest single phase** and consolidates write-side
  work that the original plan split between host-only (old Phase 3)
  and sandbox (old Phase 4). Both halves landed together because the
  modules and abstractions are shared; remote-destination support
  ultimately landed in the same phase via the staging-dir + host-egress
  topology rather than restic-native S3.
- **Phase 4 (resume) cleared the ship gate.** The hydration core,
  orphan-snapshot cleanup, `prior_run` wrap, validation, and the
  `inspect eval retry` integration are in place and roundtrip-tested
  on the CTF example with both local and `s3://` sample checkpoints
  dirs. Phases 5 + 6 are layered polish on top.
- **Phases 5 + 6 are layered, not blocking.** Phase 5 (observability)
  lands customer-visible signals — events, hooks, TUI — that don't
  change the write/read contract. Phase 6 (advanced policies +
  retention) is intentionally optional polish; anything not ready
  slots into a later release without blocking the core feature.
