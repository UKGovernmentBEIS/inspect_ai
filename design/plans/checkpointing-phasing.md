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
  Phase 5).
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

## Phase 3 — Host-only checkpointing + resume (native-agent end-to-end)

**Status:** In progress.

**Plan sections covered:** §1, §4a, §4d, §4g, §5, §6, §7a, §7b, §8a,
§8b, §8c, §8e.

**Vocabulary** (used consistently across modules + tests):

- *eval checkpoints dir*: `<log>.eval.checkpoints/` (destination root,
  may be on s3).
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
- Sample working dir still gets **placeholder** `context.json` /
  `store.json` carrying the current turn — restic actually backs them
  up, but the contents are stand-ins until the real condensed
  serialization lands.

**Deliverables — write side (still TBD):**

- Real `context.json`: condensed messages/events via `condense_sample()`.
- Real `store.json`: serialized sample `Store`.
- Atomic sidecar write (write `.tmp`, rename) — currently best-effort.
- `CheckpointEvent` in the event stream.
- `on_checkpoint_start` lifecycle hook.
- `max_consecutive_failures` enforcement.
- TUI indicator.
- Concurrent-safe manifest creation (today: race; first writer wins).

**Deliverables — read side:**

- Sample-source extension to deliver partial samples.
- Read sidecar → host snapshot → rehydrate messages, events, `Store`.
- Agent protocol `resume: Literal[True] | None`.
- `TaskState.resumed`.
- Integration with `inspect eval retry` and eval-set retry.

**End state:** A native Python agent (e.g. the built-in React agent)
configured with `sandbox_paths={}` checkpoints, can be killed, and
resumes from the latest checkpoint. **Full roundtrip testable.**
Sandbox CLI agents are not yet supported.

**Why next:** half the customer base (native agents) gets a working
feature; format-level invariants get exercised by real resume code;
sandbox-side complexity stays decoupled.

## Phase 4 — Sandbox checkpointing + resume (sandbox-CLI end-to-end)

**Plan sections covered:** §4a (sandbox half), §4e, §4f, §4h, Appendix B.

**Deliverables — write side:**

- Restic injection into sandbox image (extends sandbox-tools pipeline).
- Privilege model: `/opt/restic` mode 0700, root-only egress buffer,
  all execs as root, password via `RESTIC_PASSWORD` env only.
- In-sandbox `restic backup` against configured paths.
- Egress protocol (Appendix B): per-file copy-out of new pack files,
  manifest-based diff, two-phase commit.
- Sidecar `sandboxes` map populated.

**Deliverables — read side:**

- Sandbox restore on resume (mechanism — in-sandbox `restic restore`
  vs host-mediated copy-in — TBD during implementation).

**End state:** A sandbox CLI agent (Claude Code, Codex CLI, etc.) with
`sandbox_paths={"default": ["/root", "/workspace"]}` checkpoints and
resumes end-to-end. The "main event" for the heaviest customer use
case.

**Why fourth:** Phase 3 has stabilized the format and resume harness;
sandbox additions slot in cleanly. The egress protocol is the only
meaningfully novel mechanism.

## Phase 5 — Advanced policies + retention + polish

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

## Phase 6+ — Future capabilities

Not scheduled. Tracked here so they're not lost:

- Mid-tool-call checkpointing (currently a Phase-1 non-goal in the
  plan).
- User-provided encryption password.
- Eval-complete vs sample-complete retention granularity (the §9 open
  question).
- Provider-native snapshot variants (Modal memory snapshots, etc.) if
  and when worth it.

## Notes on this shape

- **Phase 3 is the biggest single phase** because it pairs checkpoint
  write and resume. Deliberate — building one without the other gives
  no roundtrip signal. If the phase becomes too unwieldy, it could
  split into 3a (write only, with format-level unit tests) and 3b
  (resume), but 3a alone has no externally observable user value.
- **Phases 1 and 2 are genuinely small and self-contained** —
  scaffolding that lands latent under review before the user-facing
  machinery follows.
- **Phase 4 carries the most novel risk** (egress protocol, privilege
  model, multi-provider sandbox testing). Putting it after Phase 3
  means we have a working checkpoint-resume harness to validate
  against rather than building it green-field.
- **Phase 5 is intentionally optional** — anything in it that's not
  ready in time can ship in a later release without blocking the core
  feature.
