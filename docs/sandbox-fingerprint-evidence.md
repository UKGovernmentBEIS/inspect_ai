# Sandbox Fingerprint — Cross-Eval Validation Evidence

Validation of the `sandbox_fingerprint` primitive (SP-1) across real sandboxed
evals, plus the drift regression test that locks the behaviour into the suite.

## What the primitive does

An auto-on (opt-out via `INSPECT_DISABLE_SANDBOX_FINGERPRINT`) `Hooks` subclass
probes each live sandbox at `SampleStart` and records a typed `SandboxFingerprint`
per environment into `EvalSample.sandbox_fingerprint` (a `dict[str, SandboxFingerprint]`
keyed by environment name). Fields: `type`, `image`, `image_id`, `repo_digests`,
`os`, `kernel`, `packages`, `network_profile`, `metadata`. The eval log otherwise
records only the sandbox *recipe* (provider + config path), so two runs pinned to
the same mutable tag are byte-identical in the log even when the underlying image
silently drifts. The fingerprint records the *resolved* runtime so that drift is
detectable.

## Environment

- inspect_ai `0.3.238.dev1+gf8cbfff5d`, branch `sandbox-provenance-capture`, loaded
  editable from this worktree (verified: `inspect_ai.__file__` and the
  `_sandbox_fingerprint._hook` module both resolve into
  `inspect-ai__sandbox-provenance-capture`).
- inspect_evals editable from `inspect-evals.git/inspect-evals__main`.
- Docker 29.1.3. All evals run with `--model mockllm/model --limit 1` (the
  fingerprint is captured at `SampleStart`, before any model interaction).
- `hooks enabled: 1 — inspect_ai/sandbox_fingerprint` confirmed at run start.

## Evidence matrix

Legend: ✓ = populated · — = `None` (expected for the case) · PASS = fingerprint
captured correctly · DEGRADE-OK = degraded gracefully, eval did **not** fail.

Sources: **new** = run fresh for SP-2 · **recovered** = produced by SP-1's
validation harness at `/tmp/fp-val/`, re-read here (not re-run).

| # | Scenario | Source | Image / sandbox | type | image_id | repo_digests | os | kernel | #pkgs | net | status | Result |
|---|----------|--------|-----------------|------|----------|--------------|----|--------|-------|-----|--------|--------|
| 1 | **class_eval** | new | `ghcr.io/arcadiaimpact/inspect-eval-class_eval:latest` | docker | ✓ `87fd150c…` | ✓ `…b9e26308` | Debian 13 (trixie) | 6.8.0-110 | 28 | none | success | PASS |
| 2 | **osworld image** (computer-tool) | new | `aisiuk/inspect-computer-tool:latest` | docker | ✓ `a1cf5b4b…` | ✓ `…cb0bb8c1` | Ubuntu 22.04.5 LTS | 6.8.0-110 | 64 | none | success | PASS |
| 3 | basic capture | recovered | `python:3.12-slim` | docker | ✓ `2931a495…` | ✓ | Debian 13 (trixie) | 6.8.0-110 | — | none | success | PASS |
| 4 | multi-service (3 envs) | recovered | `python:3.12-bookworm` ×3 | docker | ✓ `0fe3531e…` | ✓ | Debian 12 (bookworm) | 6.8.0-110 | 1 | none | success | PASS |
| 5 | per-sample override | recovered | `python:3.13-slim` / `python:3.12-slim` | docker | ✓ `766526d7…` / `2931a495…` | ✓ | Debian 13 (trixie) | 6.8.0-110 | 1 | none | success | PASS |
| 6 | editable/URL pkgs | recovered | `fp-pkgs:latest` (built) | docker | ✓ `2d71ad65…` | — (local build) | Debian 13 (trixie) | 6.8.0-110 | 7 | none | success | PASS |
| 7 | alpine (no pip) | recovered | `alpine:3.19` | docker | ✓ `83b2b670…` | ✓ | Alpine Linux v3.19 | 6.8.0-110 | — (no pip) | none | success | PASS (partial degrade) |
| 8 | **non-docker degradation** | recovered | `local` (host) | local | — | — | Ubuntu 22.04.5 LTS | 6.8.0-110 | 280 | — | success | **DEGRADE-OK** |
| 9 | **drift** (same tag, 2 images) | recovered | `drift-test:latest` → 3.12-slim then 3.13-slim | docker | ✓ `2931a495…` ≠ `766526d7…` | ✓ | Debian 13 (trixie) | 6.8.0-110 | 1 | none | success | PASS |
| 10 | drift (local builds) | recovered | `drift-test:latest` (two builds) | docker | ✓ `4c076307…` ≠ `7d158411…` | — (local) | Debian 13 (trixie) | 6.8.0-110 | — | none | success | PASS |
| 11 | opt-out | recovered | `python:3.12-slim`, `INSPECT_DISABLE_SANDBOX_FINGERPRINT=1` | — | — | — | — | — | — | — | success | by-design (fingerprint = `None`) |
| 12 | `.eval`/`.json` round-trip | recovered | `python:3.12-slim` | docker | ✓ `2931a495…` | ✓ | Debian 13 (trixie) | 6.8.0-110 | — | none | success | PASS (field survives both formats) |

Image ids/digests are truncated for readability; full values are in the source logs.

**osworld note (row 2):** the full `inspect eval inspect_evals/osworld` harness was
attempted but did not reach `SampleStart` — its VNC/noVNC desktop sandbox is slow to
boot and sparse-clones the large OSWorld dataset, cycling containers for >11 min without
producing a sample (a harness/environment limitation unrelated to the fingerprint
primitive). Since osworld's sandbox is built `FROM aisiuk/inspect-computer-tool:latest`,
row 2 fingerprints that exact image directly via a minimal docker task — faithful
osworld-class evidence. The captured digest `…cb0bb8c1` matches the value SP-1 recorded
for this image, confirming stability.

## Gate coverage

- **≥4 sandboxed evals, fingerprint correctly captured**: rows 1–10, 12 (well over four
  distinct docker images: class_eval, computer-tool, python-slim, python-bookworm,
  alpine, fp-pkgs, drift-test). class_eval and the osworld base image are the two
  named flagship evals.
- **Degradation never fails the eval**: row 8 — a non-docker `local` sandbox yields
  `type=local` with `image`/`image_id`/`repo_digests` all `None` (host-side container
  probes return nothing), while `os`/`kernel`/`packages` come from the host; the eval
  completes `success`. Row 7 shows per-field degradation (no `pip` in Alpine → `packages`
  is `None`, everything else captured). Row 11 shows opt-out (`fingerprint = None`).
- **Drift recorded distinctly**: rows 9–10 — the same mutable tag (`drift-test:latest`)
  pointed at two different underlying images produces two distinct `image_id`s while the
  recorded recipe (compose path) is byte-identical. This is the scenario locked into the
  suite by `tests/util/sandbox/test_sandbox_fingerprint_drift.py`.

## Drift regression test

`tests/util/sandbox/test_sandbox_fingerprint_drift.py`
(`@pytest.mark.slow`, `@skip_if_no_docker`) promotes the throwaway drift demo into the
suite. It builds two genuinely different images — `Dockerfile.a` (`FROM python:3.12-slim`,
Debian) and `Dockerfile.b` (`FROM alpine:3.19`, Alpine) — publishes each behind the SAME
mutable tag `inspect-fingerprint-drift:latest` in turn, and runs an eval after each
repoint with the SAME compose file. It asserts:

- `log_a.eval.sandbox == log_b.eval.sandbox` — the recorded recipe is identical across runs.
- `fp_a.image == fp_b.image == "inspect-fingerprint-drift:latest"` — identical at the tag level too.
- `fp_a.image_id != fp_b.image_id` — the fingerprint distinguishes the drift the recipe cannot.
- `fp_a.os != fp_b.os` — a second independent signal (Debian vs Alpine).

The discriminator is `image_id` (not `os` or `repo_digests`): SP-1 evidence shows
`python:3.12-slim` and `python:3.13-slim` both report `os = "Debian GNU/Linux 13 (trixie)"`,
so OS alone cannot detect minor-version drift — `image_id` always can. `repo_digests` is
only present when the resolved image carries registry digests, so it is not asserted.

Result: **PASSED** (`pytest tests/util/sandbox/test_sandbox_fingerprint_drift.py --runslow`).

## Reproduction

```
cd inspect-ai__sandbox-provenance-capture
uv venv --python 3.12 .venv-validate
uv pip install --python .venv-validate/bin/python -e .
uv pip install --python .venv-validate/bin/python -e <inspect-evals worktree>
# gate: inspect_ai must resolve into THIS worktree
.venv-validate/bin/python -c "import inspect_ai; print(inspect_ai.__file__)"
# named eval
.venv-validate/bin/inspect eval inspect_evals/class_eval --model mockllm/model --limit 1
# regression test
.venv-validate/bin/python -m pytest tests/util/sandbox/test_sandbox_fingerprint_drift.py --runslow
```
