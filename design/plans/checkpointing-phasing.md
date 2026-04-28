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

**Status:** Done. React agent wiring is held back to Phase 3, where it
lands together with the no-op fire becoming a real write.

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

**Deferred (lands with Phase 3):**

- Built-in React agent wiring (optional
  `checkpoint: CheckpointConfig | None = None` constructor parameter;
  per-iteration `tick()` call).

**Why this carve-out:** locked the agent contract and the public type
surface before the heavy machinery lands on top of it. Pure policy
tests caught subtle threshold semantics in isolation. The state
ownership question (`TaskState` vs. context var) settled in favor of
context var.

## Phase 3 — Host-only checkpointing + resume (native-agent end-to-end)

**Plan sections covered:** §1, §4a, §4d, §4g, §5, §6, §7a, §7b, §8a,
§8b, §8c, §8e.

**Deliverables — write side:**

- Host working tree + host repo (`context.json` + `store.json`).
- Sidecar (`ckpt-NNNNN.json`) atomic write.
- `manifest.json` with auto-generated password.
- `CheckpointEvent` in the event stream.
- `on_checkpoint_start` lifecycle hook.
- `max_consecutive_failures` enforcement.
- TUI indicator.
- Phase 2's no-op fire becomes a real write.
- Built-in React agent wired up: optional
  `checkpoint: CheckpointConfig | None = None` constructor parameter;
  constructs a `Checkpointer` and calls `tick()` per loop iteration
  when non-None.

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
