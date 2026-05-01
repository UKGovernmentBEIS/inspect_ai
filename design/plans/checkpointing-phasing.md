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

- `src/inspect_ai/util/_restic/`: `Platform` literal,
  `current_platform()`, async `resolve_restic(platform)`,
  `cache_path()`, pinned version in `version.txt` (currently
  `0.18.1`).
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
- 3 unit tests (`tests/util/test_restic_resolver.py`) covering cache
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

- `src/inspect_ai/checkpoint/`: public subpackage with
  `CheckpointConfig`, all six policy types (`TimeInterval`,
  `TurnInterval`, `TokenInterval`, `CostInterval`, `BudgetPercent`,
  and the `"manual"` literal), `Retention`, `Checkpointer`, and the
  manual `checkpoint()` trigger. The public surface matches the
  design doc; later phases swap implementations underneath.
- `Checkpointer` async context manager. `tick()` consults the policy
  and decides whether the iteration is a checkpoint moment; firing is
  a **no-op** (counter and timestamp resets only). Active checkpointer
  is tracked via a `contextvars.ContextVar` so the manual trigger can
  locate it without explicit plumbing.
- `tick()` implements `TimeInterval`, `TurnInterval`, and `"manual"`
  policies. `TokenInterval` / `CostInterval` / `BudgetPercent` raise
  `NotImplementedError` from `Checkpointer.__init__` (scheduled for
  Phase 6).
- `await checkpoint()` module-level function for manual triggers;
  raises clean `RuntimeError` if called outside a `Checkpointer`
  context.
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

- `react()` and `react_no_submit()` accept an optional
  `checkpoint_config: CheckpointConfig[NonManualCheckpointTrigger] | None
  = None`. The execute body runs inside `async with
  Checkpointer(checkpoint_config) as cp:` and calls `await cp.tick()`
  per loop iteration. `None` is a true no-op (no ContextVar set), so
  `await checkpoint()` from helper code raises rather than silently
  succeeding.
- `NonManualCheckpointTrigger` type alias keeps `trigger="manual"` out of
  agents whose loops have no hook for the manual trigger.
- `Checkpointer.__aenter__` captures `sample_id`, `epoch`,
  `log_location`, and `eval_id` from `sample_active()` into
  `_SampleIdentity` for use by Phase 3's real `_fire()`. Entering an
  active (non-None) Checkpointer outside a sample raises.
- `examples/checkpoint_ctf.py`: layered-decoder CTF harness exercising
  the public API surface end-to-end (no real fire yet).

**Deferred (still lands with Phase 3):**

- **Sample-level retry / attempt index in `ActiveSample`.**
  `Checkpointer.__aenter__` currently captures `sample_id`, `epoch`,
  `log_location`, and `eval_id`. The retry / attempt index needed to
  disambiguate `<sample-id>__<epoch>_<retry>/` is **not yet captured**
  — `ActiveSample` doesn't expose it. Phase 3 resolves this either by
  adding an `attempt` field to `ActiveSample` (symmetric with `epoch`)
  or by subscribing to `on_sample_attempt_start`. See the TODO in
  `inspect_ai/checkpoint/_checkpointer.py` `__aenter__`.

**Why this carve-out:** wiring the agent and capturing identity are
mechanical and reviewable on their own; pulling them forward gives a
runnable harness (`examples/checkpoint_ctf.py`) that exercises the
public API surface before the real I/O lands, and leaves Phase 3 as a
focused swap of `_fire()`'s body plus the read side.

## Phase 3 — Checkpoint write (host + sandbox, end-to-end)

**Status:** In progress; most landed.

**Plan sections covered:** §1, §4a, §4d, §4e, §4f, §4g, §4h, §5,
§7a, §7b, §8a, §8b, §8c, §8e, Appendix B.

This phase consolidates the write-side of the original Phase 3
(host-only) and Phase 4 (sandbox + egress) — both ended up landing
together because the work fell out that way naturally. Resume
(read-side) is split into the new Phase 4.

**Vocabulary** (used consistently across modules + tests):

- *eval checkpoints dir*: `<parent>/<log-base>.checkpoints/` where
  `<log-base>` is the eval log filename with a trailing `.eval`
  stripped. `<parent>` defaults to the log's directory; overridable
  via `CheckpointConfig.checkpoints_dir`. Eventually s3-capable; see
  the "still TBD" list below for current limitations.
- *sample checkpoints dir*: `<eval checkpoints dir>/<sample>__<epoch>/`
  (per-attempt subtree on the destination).
- *eval working dir*: `inspect_cache_dir("checkpoints")/<log-base>/`
  (host-local, ephemeral).
- *sample working dir*:
  `<eval working dir>/<sample>__<epoch>/` (host-local, restic backs
  this up each cycle).

**Landed so far (write side):**

- Modules `_eval_checkpoints`, `_sample_checkpoints`, `_working_dir`
  own paths + writes for each of the four dir kinds. `init_eval_…`
  sets up the manifest; `ensure_sample_…` is the public entry-point
  on each side and handles the eval-level setup as an implementation
  detail.
- `manifest.json` written at the eval checkpoints dir with an
  auto-generated `secrets.token_urlsafe` password. Idempotent across
  samples; mismatched `eval_id` raises.
- `Checkpointer` is a thin facade that picks one of two
  `CheckpointSession` impls on entry:
  - `_NoopCheckpointer` for `Checkpointer(None)` — both methods are
    pass-through.
  - `_Checkpointer` for active configs — holds pre-ensured sample
    dirs, the resolved host restic binary, and the eval password as
    ivars. Tracks turn counter, per-checkpoint ordinal, and trigger
    derivation (`time` / `turn` / `manual`).
- The active session (either impl) is registered on a ContextVar so
  free helpers (e.g. the manual `checkpoint()` trigger) work
  transparently regardless of whether the surrounding Checkpointer is
  active or no-op.
- **Restic integration is real**:
  - Host: `init_host_repo` (idempotent — skip if `repo/config` exists)
    runs at `__aenter__` against `<sample-checkpoints-dir>/host/`;
    `run_host_backup` runs each fire and parses restic's `--json`
    summary into a `ResticBackupSummary` pydantic model.
  - Sandbox: `inject_restic` streams the linux binary as root via
    stdin into `/opt/inspect-restic/restic` (parent dir mode 0700,
    invisible to non-root). `init_sandbox_repo` initializes
    `/opt/inspect-restic/repo` once. `run_sandbox_backup` invokes the
    injected binary as root each fire.
  - **Sandbox egress** (Appendix B): each cycle, `egress_sandbox`
    runs a phase-1 root exec in the sandbox that diffs current
    `repo/` files against `egress-manifest.txt`, builds an ordered
    tar (`config → keys → data → index → snapshots`) into
    `staging/egress-NNNNN.tar`, and emits the new file list. Host
    pulls the tar via `env.read_file`, extracts into the destination
    `<sample-checkpoints-dir>/sandboxes/<name>/`, runs
    `restic snapshots --json` against the destination to verify the
    new snapshot id is listed, then phase-2 root exec advances the
    manifest and drops the tarball. Failure between phases leaves
    the manifest unadvanced so the next cycle re-egresses the same
    files. Destination repo is **not** pre-initialized — first
    cycle's tarball carries `config` + `keys/*`, which makes the
    destination valid on extraction.
  - **Host + each sandbox `(backup → egress)` run in parallel** via
    `inspect_ai.util.collect()`. Within a sandbox the pair is
    sequential (egress diffs against what backup just wrote); pairs
    across sandboxes and the host backup are independent.
- **Sidecar carries per-backup stats** (`host: SnapshotInfo`,
  `sandboxes: dict[str, SnapshotInfo]`) where `SnapshotInfo` =
  `{snapshot_id, size_bytes, duration_ms}`. `size_bytes` comes from
  restic's `data_added_packed` (post-compression on-disk cost);
  `duration_ms` from restic's `total_duration`. Top-level
  `size_bytes` on the sidecar is the rolled-up total.
- **The host snapshot contents are still fake.** The infrastructure
  around them is real — restic backs them up to the host repo, the
  snapshot id and size land in the sidecar, the egress protocol
  ships them — but the bytes inside `context.json` / `store.json`
  are placeholder JSON carrying just the current turn. Real
  serialization (`condense_sample()` + `Store`) is the first item in
  the TBD list below.
- **Destination override**: `CheckpointConfig.checkpoints_dir`
  repoints the parent root under which the per-eval subdir lands;
  default is the log's directory. The per-eval subdir name strips a
  trailing `.eval` and appends `.checkpoints` (so `foo.eval` →
  `foo.checkpoints/`, replacing the earlier `foo.eval.checkpoints/`).

**Still TBD (write side):**

- Real `context.json`: condensed messages/events via
  `condense_sample()` — replaces the placeholder.
- Real `store.json`: serialized sample `Store` — replaces the
  placeholder.
- Atomic sidecar write (write `.tmp`, rename) — currently best-effort.
- `max_consecutive_failures` enforcement.
- Concurrent-safe manifest creation (today: race; first writer wins).
- **Real s3 / remote `checkpoints_dir` support**. The override accepts
  any string today, but only local destinations work end-to-end. The
  fsspec-mediated paths (manifest, sidecar, dir creation) already
  handle `s3://` correctly, but the restic-touching paths assume
  local fs. Concretely:
  - The host backup should be sent **directly** to the destination
    via restic's native s3 backend (no host-local stage). That means
    translating fsspec URLs (`s3://bucket/path`) to restic's URL form
    (`s3:<endpoint>/bucket/path`) before invoking restic, and
    propagating AWS credentials into the restic subprocess `env`
    (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / region) — our
    minimal `_restic_env` only sets `RESTIC_PASSWORD` + `PATH` today.
  - `_restic.init_host_repo` and `egress_sandbox`'s
    `Path(repo).mkdir(...)` / `Path(repo) / "config"` calls collapse
    `s3://` to `s3:` and treat it as local; replace with
    `filesystem(repo).mkdir(...)` / `filesystem(repo).exists(...)`.
  - Egress tar extraction (`tarfile.extractall(dest_repo)`) is
    local-fs only; for remote destinations, either extract to a
    local staging dir then `filesystem(...).put_file(...)` per
    member, or skip the staging and stream extracted bytes through
    fsspec writes. Same restic-URL/creds handling as above for the
    post-extract `restic snapshots` verification.
  - Until that lands, validate the override at config-validation
    time and reject non-local paths with a clear NotImplementedError.

**End state of Phase 3:** Every checkpoint cycle produces a real,
crash-resumable on-disk artifact for both native and sandbox-CLI
agents, on either local or remote destinations. Resume code (Phase 4)
will read these artifacts; nothing in Phase 3 actually rehydrates a
sample.

## Phase 4 — Resume (read side, all surfaces)

**Status:** Not started.

**Plan sections covered:** §6, §7c (resume integration with retry
machinery), and the read-side complement of §1, §4a, §5, §8a, §8b.

This phase consolidates the read-side that was originally split across
the old Phase 3 (host-only resume) and Phase 4 (sandbox resume). They
share enough machinery (sample-source extension, resume hook, retry
integration) that splitting them produced redundant work; tackled
together they're one coherent body.

**Deliverables:**

- Sample-source extension to deliver **partial** samples (the existing
  retry pathway delivers either fresh or completed samples; this
  phase adds a third state).
- Read sidecar → restore host working dir from the host repo →
  rehydrate condensed messages/events + `Store` into `TaskState`.
  Reuses `condense_sample()` / `resolve_sample_events_data()` (§5)
  on the read side.
- **Sandbox state restore**: on resume, re-inject restic into the
  fresh sandbox container, clone the destination sandbox repo back
  in (mechanism — in-sandbox `restic restore` vs host-mediated
  copy-in — settled during implementation), and confirm the agent
  sees its prior `sandbox_paths`.
- Agent protocol: `resume: Literal[True] | None` parameter; agents
  that opt in receive the rehydrated `TaskState`.
- `TaskState.resumed: bool` so agents can branch on it without
  re-reading the sidecar themselves.
- Integration with `inspect eval retry <log>` and eval-set retry —
  both pathways resolve into the same sample source, so wiring in
  the partial-sample state lights both up.

**End state of Phase 4:** A killed eval (native or sandbox-CLI agent)
resumes from the latest checkpoint with full roundtrip fidelity —
messages, events, `Store`, and sandbox filesystem all match the
pre-kill state. **Full roundtrip testable**, and the only blocker
to shipping the feature.

**Why after Phase 3 finishes:** the user has explicitly opted to ship
nothing until resume works, so there's no incentive to start resume
on a moving write-side target. Phase 3's remaining items (real
context/store, atomic sidecar, s3, etc.) all change format-level
details that resume reads — finishing them first means resume code
is written once against the final shape.

## Phase 5 — Observability

**Status:** Not started.

**Plan sections covered:** §8 (write-side observability surfaces).

Customer-visible signals that checkpointing is happening — for
debugging, monitoring, and ops integration. Deferred out of Phase 3
because they're orthogonal to "the cycle works": every item here
improves visibility, none is required for round-trip correctness.

**Deliverables:**

- `CheckpointEvent` in the per-sample event stream — one entry per
  fired checkpoint carrying `{checkpoint_id, trigger, snapshot ids,
  size_bytes, duration_ms}`. Lands in the `.eval` log alongside
  model and tool events; viewable in `inspect view`.
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
  modules and abstractions are shared. The phase isn't shipping
  anything user-facing on its own — there's no resume code yet — but
  produces real on-disk artifacts that Phase 4 will roundtrip.
- **Phase 4 (resume) is the ship gate.** Per the project decision,
  nothing about checkpointing ships to users until Phase 4 is done.
  That means Phase 3's finishing items aren't time-pressured — we
  can land them in any order before resume work begins.
- **Phases 5 + 6 are layered, not blocking.** Phase 5 (observability)
  lands customer-visible signals — events, hooks, TUI — that don't
  change the write/read contract. Phase 6 (advanced policies +
  retention) is intentionally optional polish; anything not ready
  slots into a later release without blocking the core feature.
