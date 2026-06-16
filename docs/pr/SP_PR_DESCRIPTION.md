<!--
DRAFT / BUILD-AHEAD — not yet opened. This file is the proposed PR body for the
sandbox-fingerprint feature. It is committed to the branch so the draft is reviewable
and so the PR can be opened later without re-deriving it.

Before opening the real upstream PR, remove `docs/pr/` from the branch — these are
process artifacts, not part of the feature.

Proposed PR title:
    Capture resolved sandbox runtime fingerprint into the eval log

Target: base UKGovernmentBEIS/inspect_ai:main  <-  head joesposito8/inspect_ai:sandbox-provenance-capture
-->

# Capture resolved sandbox runtime fingerprint into the eval log

## Problem

Inspect runs agents inside throwaway sandboxes whose recipes routinely pin **mutable
image tags** (`:latest`, floating refs). The eval log records only the sandbox
*recipe* — the provider and config path (`EvalSpec.sandbox`, with `revision=None`) —
never the runtime that recipe actually resolved to. So when a mutable tag is silently
repointed at a different underlying image, **two runs in genuinely different
environments produce byte-identical environment records in the log.**

The consequence: when a score moves between two runs, you cannot tell from the log
whether the model changed or the computer underneath it did. The environment is an
uncontrolled, unrecorded variable.

## Why this matters

Environment drift is not a rounding error in agentic evals:

- **WAREX** ([arXiv:2510.03285](https://arxiv.org/abs/2510.03285)) reports **agent-success
  swings of 70%+** attributable to environment variance.
- **Sober Look** ([arXiv:2504.07086](https://arxiv.org/abs/2504.07086)) documents how
  much evaluation conclusions hinge on environment/setup details.
- **EleutherAI lm-eval** ([#3357](https://github.com/EleutherAI/lm-evaluation-harness/issues/3357))
  finds variance even under fixed seed/hardware — establishing that environment is a
  first-class source of irreproducibility.

Demand signal in this repo: [#2286](https://github.com/UKGovernmentBEIS/inspect_ai/issues/2286)
asks for exactly this capability.

## What this PR adds

An auto-on (opt-out) capture step that probes each live sandbox at sample start and
records its **resolved runtime fingerprint** into a typed per-sample field on the eval
log. It does not change how any eval runs — it just makes each run write down what it
actually ran on.

### Before / after (eval log, per sample)

```jsonc
// before — recipe only; identical across two drifted runs
"sandbox": { "type": "docker", "config": "compose.yaml" }

// after — recipe unchanged, PLUS the resolved runtime, keyed by environment name
"sandbox": { "type": "docker", "config": "compose.yaml" },
"sandbox_fingerprint": {
  "default": {
    "type": "docker",
    "image": "ghcr.io/.../inspect-eval-class_eval:latest",
    "image_id": "sha256:87fd150c…",
    "repo_digests": ["…@sha256:…b9e26308"],
    "os": "Debian GNU/Linux 13 (trixie)",
    "kernel": "6.8.0-110-generic",
    "packages": { "…": "…" },
    "network_profile": "none",
    "metadata": {}
  }
}
```

## Design

- **Auto-on `Hooks` subclass** (`SandboxFingerprintHook`), covering all sandboxed evals
  with zero per-eval edits. Opt out with `INSPECT_DISABLE_SANDBOX_FINGERPRINT`.
- **Probes at `SampleStart`** — the sandbox is live there (`on_sample_init` fires before
  sandbox creation, too early).
- **Typed field**: `EvalSample.sandbox_fingerprint: dict[str, SandboxFingerprint] | None`,
  keyed by environment name, mirroring how multi-service sandboxes are addressed. The
  `SandboxFingerprint` model has every field optional except `type`, so partial/degraded
  captures remain valid.
- **Stable public API only** — host-side image identity via `docker inspect` (resolved
  from `sandbox().connection()`); in-container facts via `sandbox().exec()`
  (`/etc/os-release`, `uname -r`, `pip list`). No private `_service`/`_project` internals.
- **Pluggable probe seam** — `register_fingerprint_probe(name, fn)` / `@fingerprint_probe(name)`
  let ports add domain-specific signals (e.g. an AndroidWorld AVD hash); custom probes
  write under `metadata` to avoid colliding with built-ins.
- **Never fails an eval** — every probe and the host connection are wrapped; failures
  degrade to `None`/partial fields and log a warning, they do not raise.

The default fingerprint fields are `image`, `image_id`, `repo_digests`, `os`, `kernel`,
`packages`, `network_profile`, plus free-form `metadata`.

## Evidence

Full validation matrix: [`docs/sandbox-fingerprint-evidence.md`](../sandbox-fingerprint-evidence.md)
— 12 scenarios across distinct images, each scored on every field.

**Drift is detected.** The same mutable tag pointed at two different underlying images
yields two distinct `image_id`s while the recorded recipe is byte-identical. This is
locked into the suite by
[`tests/util/sandbox/test_sandbox_fingerprint_drift.py`](../../tests/util/sandbox/test_sandbox_fingerprint_drift.py)
(`@pytest.mark.slow`, `@skip_if_no_docker`): it builds a Debian image and an Alpine image
behind one tag in turn, runs an eval after each repoint, and asserts the recipe is
identical across runs while `image_id` and `os` differ. The discriminator asserted is
`image_id` — OS alone cannot catch minor-version drift (`python:3.12-slim` and
`python:3.13-slim` both report Debian 13 trixie), whereas `image_id` always can.

**Flagship coverage.** Validated against `inspect_evals/class_eval` (full run) and the
OSWorld base image `aisiuk/inspect-computer-tool:latest`. Note: the OSWorld evidence is
**base-image**, not a full OSWorld run — the full OSWorld harness boots a VNC/noVNC
desktop and sparse-clones a large dataset and did not reach `SampleStart` within the
validation window. Since OSWorld's sandbox is built `FROM aisiuk/inspect-computer-tool:latest`,
that exact image is fingerprinted directly; the captured digest (`…cb0bb8c1`) matches the
independently recorded value.

### Degradation matrix (excerpt)

| Provider / case | image / image_id | os / kernel / packages | Eval outcome |
|---|---|---|---|
| docker (normal) | captured | captured | success |
| non-docker `local` | `None` (no host-side image) | host values captured | success |
| alpine (no `pip`) | captured | `packages = None`, rest captured | success |
| opt-out env set | — | — | `sandbox_fingerprint = None` by design |

## Known limitations (disclosed)

- **Crash-recovered samples lack the fingerprint.** `reconstruct_eval_sample`
  (`src/inspect_ai/log/_recover/_reconstruct.py`) sets `sandbox_fingerprint=None`: the
  field is not persisted to the realtime buffer DB, so a sample reconstructed after a
  crash has no fingerprint. Normal completed runs are unaffected.
- **Extension seam placement.** `register_fingerprint_probe` / `@fingerprint_probe` are
  currently importable from `inspect_ai.hooks._sandbox_fingerprint` (an underscore
  module). If maintainers want this to be a supported extension point, it should be
  re-exported from a public namespace — flagging for input rather than presuming.

## Files changed

- `src/inspect_ai/util/_sandbox/environment.py` — `SandboxFingerprint` model (exported
  from `inspect_ai.util`).
- `src/inspect_ai/log/_log.py` — `EvalSample.sandbox_fingerprint` typed field.
- `src/inspect_ai/hooks/_sandbox_fingerprint/` — the hook, probes, and probe registry;
  registered in `src/inspect_ai/hooks/_startup.py`.
- `src/inspect_ai/util/_sandbox/context.py`, `_eval/task/run.py` — per-sample context-var
  bridge (mirrors `model_usage`).
- `src/inspect_ai/log/_recover/_reconstruct.py` — explicit `None` (see limitations).
- `src/inspect_ai/_view/inspect-openapi.json` — regenerated schema.
- Tests: `tests/hooks/test_sandbox_fingerprint.py`,
  `tests/util/sandbox/test_sandbox_fingerprint_drift.py`.
- `docs/sandbox-fingerprint-evidence.md`, `CHANGELOG.md`.

## CI checklist (for whoever opens the PR)

- [ ] **Remove `docs/pr/` from the branch** — process artifacts, not part of the feature.
- [ ] **Regenerate generated TypeScript types.** `check-schema-and-types`
      (`.github/workflows/log_viewer.yml`) runs `python src/inspect_ai/_view/schema.py`
      and fails on any diff. The Python side (`inspect-openapi.json`) is already
      regenerated and committed. The **TypeScript** side was **not** regenerated here:
      it requires `pnpm` + Node 18+ inside the `ts-mono` submodule, neither available in
      the build environment (Node 12, no pnpm/corepack). The generated file lives in the
      **separate** `meridianlabs-ai/ts-mono` repo
      (`packages/inspect-common/src/types/generated.ts`), so completing this is a
      cross-repo step:
      ```bash
      git submodule update --init --recursive src/inspect_ai/_view/ts-mono
      # with pnpm + Node >=18 available:
      python src/inspect_ai/_view/schema.py      # regenerates JSON + TS
      # commit the regenerated generated.ts to ts-mono, then bump the submodule pointer
      ```
- [ ] **Changelog** — entry added under the unreleased heading in `CHANGELOG.md`.
- [ ] Drift test is `--runslow` + docker-gated; confirm CI runs the slow/docker suite or
      note it as locally verified (`pytest tests/util/sandbox/test_sandbox_fingerprint_drift.py --runslow`).
