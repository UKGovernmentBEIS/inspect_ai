# Verifying sandbox-tools binaries against digests pinned in git

Design for meridianlabs-ai/inspect_ai#283. Status: implemented in the same
PR as this design.

## Problem

Nothing in the pipeline verifies the `inspect-sandbox-tools` injectable
artifacts fetched from S3. The only controls are TLS and the bucket ACL.
Anyone able to modify bucket contents gets code execution as root inside
every sandbox that triggers a download, and the bad copy is cached
permanently in the installed package's `binaries/` directory. Three
unverified fetch sites exist today:

1. **Runtime.** `_download_from_s3` in
   `src/inspect_ai/tool/_sandbox_tools_utils/sandbox.py` does a plain HTTPS
   GET and writes `response.content` straight into `inspect_ai/binaries/`,
   chmod 755. The write isn't atomic, so a crashed download leaves a partial
   file that tier 1 will happily use forever.
2. **PyPI release.** `scripts/pypi-release.py` uses
   `urllib.request.urlretrieve`, and its "verification" is
   exists-and-non-empty. An unverified S3 object propagates into the wheel
   for every PyPI user.
3. **CI release gate.** `.github/workflows/build.yml`
   (`slow-tool-tests-release`) runs a bare `curl` and `chmod +x`.

The publish side (`upload_to_s3.py`) emits no digests, so there is currently
nothing to verify against. `aws s3 cp` also silently overwrites an existing
object, so a version's bytes can change after publication with no signal.

## Trust model

**Trust anchor: the ability to merge to this repository.** Per-variant
SHA256 digests are committed in git and updated in the same PR as the
version bump, and every consumer verifies fetched bytes against them. S3
becomes an untrusted cache. No signatures or key management.

What this defends against:

- Compromise or corruption of the S3 bucket (the headline threat).
- Anything from TLS termination onward, such as CDN or proxy tampering.
- Truncated or corrupted uploads and downloads.
- Accidental overwrite of a published version with different bytes (e.g. the
  "stale checkout" hazard called out in the release skill, or two release PRs
  racing to the same version number).

Residual risks, explicitly out of scope:

- Compromise of the releasing maintainer's build machine. The digests pin
  what the maintainer built, wherever it came from.
- Malicious commits that merge. The anchor is merge rights.
- PyInstaller builds are not reproducible, so third parties cannot rebuild
  and compare. The digest binds "the bytes validated by `validate_distros`
  and blessed in the release PR", not "bytes anyone can reproduce".
- Local-filesystem tampering on the host. An attacker who can write to
  `site-packages` can patch `inspect_ai` itself, so hashing local files buys
  nothing. See "What is deliberately not verified".
- The legacy `inspect_tool_support` Docker-image path (separate distribution
  mechanism; image digest pinning would be a separate piece of work).

## The digest file

`src/inspect_ai/tool/_sandbox_tools_utils/SHA256SUMS`, mirroring the vendored
`src/inspect_ai/util/_restic/SHA256SUMS` pattern, in standard `sha256sum`
format so `sha256sum -c` works in CI:

```
<64-hex>  inspect-sandbox-tools-amd64-v123
<64-hex>  inspect-sandbox-tools-amd64-musl-v123
<64-hex>  inspect-sandbox-tools-arm64-v123
<64-hex>  inspect-sandbox-tools-arm64-musl-v123
```

Decisions:

- **Exactly one version, exactly four entries** (arch × libc, the same four
  artifacts `upload_to_s3.py` publishes). `sandbox_tools_version.txt` pins
  exactly one version and the runtime never fetches any other, so a
  single-version file makes "digests updated together with the bump"
  mechanically checkable: every entry's filename must embed
  `-v{version.txt}`. This also resolves the issue's variant-count note: the
  sums file covers all four uploaded artifacts even though the wheel bundles
  only the two glibc ones and `pypi-release.py` downloads only those two.
- **No `-dev` entries.** Dev-suffixed artifacts are built locally and never
  fetched from the network, so they are never verified. They couldn't be
  anyway, since builds aren't reproducible.
- **Ships in the wheel.** Add `"tool/_sandbox_tools_utils/SHA256SUMS"` to the
  package-data list in `pyproject.toml` (next to the existing
  `sandbox_tools_version.txt` entry). PyPI installs need it at runtime to
  verify the on-demand musl download; the version file and sums file must
  always travel together.
- **Lives outside the injectable tree**, so editing it never triggers the
  `injectable_src` CI filter (which would demand a version bump). It is
  deliberately not added to `_check_main_divergence`'s pathspec groups
  either; see "Install-state detection" below.

A small stdlib-only module `_digests.py` in `_sandbox_tools_utils` owns
reading/writing/parsing (parse tolerates the optional `*` binary marker, as
`_restic/resolver.py::_extract_expected_hash` does). Stdlib-only matters
because `upload_to_s3.py` can run as a plain file outside an installed
`inspect_ai`, and `_digests.py` must be importable both ways.
`_build_config.py` documents the same constraint; staying stdlib-only
satisfies it trivially. Longer term the parsing could be shared with the
restic resolver via `inspect_ai._util`, but the runtime consumer in
`sandbox.py` can import from `_sandbox_tools_utils` directly, so the local
module is sufficient.

## Producer: `upload_to_s3.py`

Reworked to be the single writer of `SHA256SUMS`:

1. **Version guard.** Refuse to run unless the `version` argument equals the
   committed `sandbox_tools_version.txt`. The sums file is keyed to the
   pinned version, and uploading digests for any other version would desync
   them.
2. **Compute digests** of all four local artifacts in
   `src/inspect_ai/binaries/` upfront. This also moves the existence check
   upfront; today it is interleaved with the uploads, so a missing
   `arm64-musl` artifact aborts mid-publish with the amd64 variants already
   on S3.
3. **Immutability guard.** Before uploading, HEAD/GET each S3 object. If an
   object already exists with different bytes (compare digest of the fetched
   object), abort with an error instructing the operator to bump the version
   instead. Published wheels vendor digests for their version forever, so a
   published `v{N}` must never change meaning. Re-uploading identical bytes
   is fine (idempotent retry after a partial upload). There is no `--force`
   escape hatch. No legitimate reason exists to change a published version's
   bytes, and an escape hatch is exactly what an attacker or a rushed
   operator would reach for.
4. **Write `SHA256SUMS`** (sorted, all four entries) before uploading, so a
   crash mid-upload leaves a correct committable sums file and the CI gate
   simply stays red until the upload is completed or retried. (This holds
   only because the gate checks all four objects, see consumer 3; a crash
   during the later arm64 uploads would otherwise slip past an amd64-only
   gate.)
5. **Upload**, then **verify the round trip**: GET each uploaded object and
   check its digest. This catches truncation and eventual-consistency
   surprises before the operator walks away.
6. **Print the follow-up**: `git add .../SHA256SUMS && git commit` on the PR
   branch. The digests must land in the same PR as the version bump.

## Consumers

### 1. Runtime: `sandbox.py`

`_download_from_s3(filename)` changes from "GET + write bytes" to:

1. Look up `filename` in the vendored `SHA256SUMS`. A missing entry is an
   integrity failure — fatal in strict mode (raise, surfacing via
   `SandboxInjectionError`), a warning by default (see Soft launch below).
   For any state
   that reaches the download tier the requested name is
   `inspect-sandbox-tools-{arch}[-musl]-v{version.txt}` and the version file
   and sums file come from the same checkout or wheel, so a missing entry
   means a corrupt install or a desynced commit, never a situation where
   downloading unverified bytes is the right answer. One benign case reaches
   this failure: a non-editable git install of a release-PR branch during the
   review window (version bumped, sums not yet rewritten) classifies `clean`
   and, in strict mode, hard-fails where a 404 would fall into the
   local-build prompt.
   Accepted: the state is transient and self-describing, and falling through
   on a missing entry would blur the fail-closed contract.
2. Fetch and verify via the existing
   `inspect_ai._util.download.download(url, sha256, dest, timeout=60)`
   helper, which streams to a tempfile, hashes while streaming, rejects on
   mismatch, retries transient HTTP errors, and only renames into place
   after verification, which closes the current non-atomic write as a side
   effect. `download()` is sync (sync httpx client, local disk, no fsspec),
   so call it via `anyio.to_thread.run_sync`, exactly as
   `_restic/resolver.py` does. `chmod 0o755` after (the helper doesn't set
   the execute bit).

   **Cross-process caveat.** `download()`'s tempfile is the fixed sibling
   path `dest + ".partial"`, so two processes downloading the same `dest`
   truncate each other's tempfile while each hashes only its own stream. A
   winner can rename an interleaved file into place, recreating exactly the
   hole this design closes: unverified bytes trusted forever by tier 1. The
   in-process `concurrency(executable_name, 1)` guard in
   `_open_executable_for_arch` does not cover multiple eval processes on one
   host (e.g. parallel evals on a fresh install racing to fetch the musl
   artifact). `_restic/resolver.py` avoids this by passing `download()` a
   unique `mkstemp` destination and doing its own final `os.replace`; do the
   same here: `mkstemp` in `binaries/`, `download(url, sha256, tmp)`, chmod,
   `os.replace(tmp, dest)`. (Alternatively fix `download()` itself to use a
   unique tempfile and re-verify the on-disk file before rename; mkstemp at
   the call site requires no change to a shared helper.)
3. Failure semantics (see the matrix below). 404/403 keeps its current
   meaning, "not published yet": return `False` so the resolver falls
   through to the local-build tier. A digest mismatch is fatal in strict
   mode and a loud warning by default (see Soft launch below). Either way it
   is never conflated with "missing" — a mismatch is the attack or
   corruption signal this design exists to surface.

Failure-mode matrix for a download attempt:

| Condition | Behavior | Rationale |
|---|---|---|
| Object missing on S3 (403/404) | return `False`; fall through to local build prompt | Pre-upload window on a release branch; correct and expected |
| Digest mismatch | strict: raise (`PrerequisiteError` wrapped in `SandboxInjectionError`), tempfile discarded, nothing cached; default: warn once, re-fetch unverified | Tampering or corruption; loud either way |
| No entry in `SHA256SUMS` for the resolved name | strict: raise; default: warn once, download unverified | Desynced/corrupt install |
| Transient HTTP (408/429/5xx) | retried by `download()`; raise after exhaustion | Availability issue, not integrity |

**Soft launch.** While the digest machinery beds in, the integrity failures
above are warnings by default: `_download_from_s3` logs once and proceeds
with the unverified bytes unless `INSPECT_SANDBOX_TOOLS_STRICT_DIGESTS` is
set (any value other than empty/`0`/`false`), which makes them fatal. CI's
slow-tool jobs set the variable so strict mode stays exercised. The
operator-facing checks (`upload_to_s3.py`, `pypi-release.py`, the release CI
gate's `sha256sum -c`) are always fatal — softening those would let a bad
release ship quietly. A follow-on PR makes the runtime failures fatal
unconditionally and removes the variable.
| `SHA256SUMS` unreadable/missing from install | strict: raise; default: warn once, download unverified | Corrupt install |

The mismatch error message should state the expected and actual digests, name
the file, and say explicitly that this may indicate a compromised or corrupted
artifact and should be reported, not "please retry".

#### Runtime variation walkthrough

Every path through `_open_executable_for_arch` (install state × libc × tier):

| Install state | Variant | Tier that resolves it | Verified? |
|---|---|---|---|
| `pypi` | glibc (amd64/arm64) | bundled in wheel (`binaries/`) | at bundling time by `pypi-release.py` (see consumer 2); not re-hashed at use |
| `pypi` | glibc, missing from wheel (broken install; today warns) | S3 download fallback | **yes**; wheel vendors `SHA256SUMS` |
| `pypi` | musl (deliberately not bundled) | S3 download, the normal musl path | **yes**; today this is the highest-traffic unverified site |
| `clean` (editable, no sandbox-tools edits) | any | S3 download | **yes**; repo checkout vendors `SHA256SUMS` consistent with `version.txt` |
| `clean`, artifact not yet on S3 (404) | any | falls through to prompted local Docker build | n/a; see below |
| `edited` (editable, sandbox-tools changed) | any (`-dev` name) | local `binaries/` or prompted local build; never downloads | n/a by design |
| `INSPECT_SANDBOX_TOOLS_INSTALL_STATE` override (CI release gate forces `clean`) | glibc + musl | pre-fetched into `binaries/` by the workflow | **yes**; verified by the workflow at fetch (consumer 3) |
| `pypi` misdetected for an editable checkout (`UV_NO_INSTALLER_METADATA=1`, noted in code) | any | same download path | **yes**; same lookup, from checkout's sums |

Derived artifact: the uncompressed-`tar` cache written by
`_uncompressed_tar_bytes` (fallback for gzip-less containers) is decompressed
in-process from an artifact that was already verified at acquisition, and its
existing atomic write stays; it needs no digest entry.

#### What is deliberately not verified

Tier 1 ("local executable check") does not hash files already present in
`binaries/`. Reasons:

- Locally built artifacts (the `_build_it` fallback for `clean` installs, and
  all `edited`/dev artifacts) can never match the committed digests
  (non-reproducible builds); hashing tier 1 would break both fallbacks.
- The threat model is the network/bucket, not the local filesystem. Bytes are
  verified at acquisition: every path by which a release artifact enters
  `binaries/` (runtime download, release-script download, CI fetch) verifies,
  so an unverified release artifact cannot get in. Re-hashing ~40 MB
  on every injection would buy nothing against an attacker who can already
  write to `site-packages`.

One acknowledged gap inherits from this: `binaries/` contents that predate
this change (downloaded unverified by an older inspect_ai) remain trusted by
tier 1. The rollout section covers why this is acceptable.

#### Install-state detection

`_check_main_divergence` needs no change: `SHA256SUMS` is deliberately not
added to its version-file pathspec group. In every sanctioned flow the sums
change only together with a version bump (the extended `check-version-bump`
rule forbids sums-only changes), and version divergence already classifies
the checkout as `edited`, so on a release PR the addition would be redundant.
The one PR where it would have an effect is the seeding PR (sums diverge from
main, version doesn't), and there `edited` is the wrong answer:
`slow-tool-tests-dev` runs on that PR (the `tools` filter matches
`_sandbox_tools_utils/`) but skips its `-dev` build step (both
`injectable_src_changed` and `version_correctly_bumped` are false), so an
`edited` classification would resolve a `-dev` artifact that was never built,
skip the download tier (`edited` never downloads), and die in `_build_it`'s
interactive prompt on the non-interactive runner. Classified `clean`, the
same job instead downloads `v{N}` through the new verified path, which also
CI-checks the seeded amd64 digests (see Rollout). A locally hand-edited sums
file on a checkout that then classifies `clean` is local-filesystem
tampering, already out of scope per the threat model.

### 2. PyPI release: `scripts/pypi-release.py`

The script stays stdlib-only; it parses `SHA256SUMS` itself (or imports
`_digests.py` as a plain file; either is fine, the format is one regex).

- `download_file` verifies the streamed bytes against the expected digest and
  writes via tempfile + `os.rename` (mirroring `download()`'s semantics);
  exists-and-non-empty dies.
- `check_sandbox_tools_exist` (the "already downloaded, skip" path) must
  compare digests, not sizes; today a stale or tampered local file is
  silently bundled into the wheel. A wrong digest is treated as missing:
  clean and re-download.
- **Unconditional pre-build gate**, regardless of how files got there
  (including `--skip-sandbox-download`): immediately before `python -m build`,
  assert that `binaries/` contains exactly the two glibc artifacts for
  `version.txt`'s version and that each matches its committed digest. This is
  the last line of defense for the wheel and must not be skippable.
- **Post-build wheel-contents check**: after `python -m build`, open the
  built wheel (a zip) and assert it contains
  `inspect_ai/tool/_sandbox_tools_utils/SHA256SUMS` (and
  `sandbox_tools_version.txt`, which has the same unprotected dependency
  today) alongside the two bundled binaries. Every other gate runs from a
  repo checkout, which always has the committed sums file, so a dropped or
  broken `pyproject.toml` package-data entry is exercised nowhere else — and
  per the failure-mode table a wheel missing the sums file turns every PyPI
  musl download into a runtime integrity failure (fatal in strict mode, a
  loud warning by default), discovered only by users.
- The glibc-only download set is now checked against a four-entry sums file.
  The lookup is by filename, so the two musl entries are simply unused here.

### 3. CI release gate: `.github/workflows/build.yml`

`slow-tool-tests-release`'s fetch step becomes verify-then-trust:

```sh
VERSION=$(tr -d '[:space:]' < src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt)
SUMS=src/inspect_ai/tool/_sandbox_tools_utils/SHA256SUMS
# Digest file must be in lockstep with the version bump: four non-blank
# entries, all named -v${VERSION}. (Entry format/distinctness is enforced by
# a fast unit test; see Testing.) A flag records the failure rather than an
# early exit: `exit 1` in the awk body jumps to END, whose own exit would
# override the status.
if ! awk -v v="v${VERSION}" 'NF { n++; if ($2 !~ ("-" v "$")) bad = 1 } END { exit (bad || n != 4) }' "$SUMS"; then
  echo "::error::${SUMS} is not updated for v${VERSION}. Build+upload the artifacts (upload_to_s3.py rewrites it) and commit it in this PR."
  exit 1
fi
# All four artifacts are fetched and digest-checked, not just the amd64 pair
# the slow tests exercise on this runner. Otherwise a crash partway through
# upload_to_s3.py's upload order (amd64 first) would leave the gate green
# with the arm64 objects missing, and the committed arm64 digests would
# never be compared against S3 by anything but the maintainer-run round
# trip. The extra ~30 MB download is trivial for CI.
for FILENAME in \
  "inspect-sandbox-tools-amd64-v${VERSION}" \
  "inspect-sandbox-tools-amd64-musl-v${VERSION}" \
  "inspect-sandbox-tools-arm64-v${VERSION}" \
  "inspect-sandbox-tools-arm64-musl-v${VERSION}"; do
  URL="https://inspect-sandbox-tools.s3.us-east-2.amazonaws.com/${FILENAME}"
  # Keep today's explicit not-yet-uploaded error (a bare curl -f 404 is terse
  # and carries no ::error annotation).
  if ! curl -fsI "$URL" >/dev/null; then
    echo "::error::Published binary ${FILENAME} not found at ${URL}. Run: python src/inspect_ai/tool/_sandbox_tools_utils/upload_to_s3.py ${VERSION}, commit the rewritten SHA256SUMS, then rerun this job."
    exit 1
  fi
  curl -fSL -o "src/inspect_ai/binaries/${FILENAME}" "$URL"
  # Exactly-one-match assertion: without it, zero or duplicate entries feed
  # sha256sum a malformed line and its "no properly formatted checksum lines"
  # failure would be mislabeled a digest mismatch below. (The fast unit test
  # enforces distinctness too, but it runs in a different job; this keeps
  # this job's own error accurate.)
  DIGEST=$(awk -v f="$FILENAME" '$2 == f { print $1; n++ } END { exit n != 1 }' "$SUMS") || {
    echo "::error::Expected exactly one ${SUMS} entry for ${FILENAME}; found none or duplicates (malformed sums file)."
    exit 1
  }
  echo "${DIGEST}  src/inspect_ai/binaries/${FILENAME}" | sha256sum -c - || {
    echo "::error::Digest mismatch for ${FILENAME}: the published S3 object does not match the digests committed in this PR. Do NOT re-upload over it. Investigate (wrong-checkout build, truncated upload, or tampering), and if the object is wrong, bump the version and publish fresh artifacts."
    exit 1
  }
  chmod +x "src/inspect_ai/binaries/${FILENAME}"
done
```

Two distinct failure messages matter operationally. 404 stays "run
`upload_to_s3.py {V}` then rerun this job", which is routine. Mismatch must
not suggest re-uploading: an operator "fixing" CI by re-uploading is exactly
the overwrite the design forbids, and the uploader's immutability guard will
refuse anyway.

Also extend the fast `check-version-bump` job, in the unbumped direction
only: if `sandbox_tools_version.txt` is unchanged relative to base,
`SHA256SUMS` must be unchanged too (a sums-only change is a re-publication of
an existing version, which is forbidden). One carve-out: the rule applies
only when `SHA256SUMS` exists on the base ref. Otherwise the seeding PR,
which creates the file without a version bump (see Rollout), would fail the
very rule it introduces, since `pull_request` runs use the PR's own workflow
file. The bumped direction (sums must be updated) is deliberately not
enforced in the fast gate. The sums can only be written after the maintainer
builds the artifacts, which happens post-approval, and failing the fast gate
early would also block the independent `slow-tool-tests-dev` job. The release
gate above enforces it at the point where it can actually be satisfied,
preserving today's landing flow: the gate is red until the maintainer uploads
and commits/pushes the sums, and the push itself triggers the re-run.

Note: `.github/workflows/build.yml` edits are part of the implementation PR
(it is not one of the meridian-only workflows).

### The dev gate: `slow-tool-tests-dev` (no workflow changes)

The other slow-tool gate needs no edits, but the design does change what it
exercises, differently per PR type:

- **Release PR** (injectable source changed, version bumped). The job builds
  amd64 `-dev` binaries and the checkout classifies as `edited` (version.txt
  diverges from main), so the runtime resolves `-dev` names from the
  just-built local `binaries/` and never reaches the download tier.
  Verification is not in play, by design ("No `-dev` entries"), and the
  stale `SHA256SUMS` sitting in the checkout during the review window (it is
  rewritten only at post-approval upload) is never consulted. This is also
  why the fast gate must not enforce the bumped direction (see above): a red
  fast gate would block this job for the whole review window.
- **Tools-adjacent PR** (matches the `tools` filter without touching the
  injectable source or version, e.g. `src/inspect_ai/tool/**` or
  `tests/tools/**`). The `-dev` build step is skipped and, per the workflow's
  own comment, pytest resolves the published v{N} via the runtime's S3
  download path — which is now the verified path, checked against the sums
  the PR shares with main. Every such PR therefore acts as a continuous
  canary comparing the published amd64 pair against the committed digests. A
  corrupted or tampered object turns these jobs red with the mismatch raise
  (the jobs set `INSPECT_SANDBOX_TOOLS_STRICT_DIGESTS`), not a silent
  fallback; that is the intended fail-loud behavior, and the
  recovery is the same stop-the-line path as any other mismatch (investigate;
  if the object is wrong, bump and republish — never overwrite).
- **Seeding PR**: analyzed under "Install-state detection" and Rollout — the
  job classifies `clean` and download-verifies the seeded amd64 digests.

## Process changes

- **`src/inspect_sandbox_tools/design/RELEASING.md`**: document the new step
  between "Upload to S3" and "Merge the PR": commit the rewritten
  `SHA256SUMS` to the release PR. State the fail-closed window explicitly.
  While a version bump is merged (or installed non-editably from the PR
  branch) with the sums not yet rewritten, clean/pypi downloads treat the
  missing sums entry as an integrity failure (fatal in strict mode, a
  warning by default during the soft launch). Once the rewritten sums are
  committed but before the S3 objects land, downloads 404 and fall back to
  local build; the upload-before-commit ordering makes
  this window hard to reach. After upload, a digest mismatch anywhere is a
  stop-the-line signal, and published S3 objects are immutable. Never fix a
  mismatch by re-uploading; always bump.
- **`.claude/skills/release-sandbox-tools/SKILL.md`**: step 4's user-run
  upload now also rewrites `SHA256SUMS`; add "commit and push the sums file to
  the PR branch" as the step after upload; replace the content-length sanity
  check in step 5 with `sha256sum -c` against the committed file (the
  uploader's round-trip verification makes this belt-and-braces, but it's one
  command).

## Rollout

- Verification code, the sums file, `pyproject.toml` package-data, script and
  workflow changes all land in one PR.
- **Seeding the first `SHA256SUMS`**: hash the four currently published S3
  objects for the current version (trust-on-first-use). This blesses today's
  bucket contents rather than freshly built ones. That's acceptable for two
  reasons: a rebuild couldn't do better (non-reproducible builds would just
  bless a different unverifiable binary, while invalidating the bytes already
  bundled in released wheels), and TOFU converts a standing exposure into a
  point-in-time one; every subsequent version is pinned end-to-end at build
  time. Record the seeding provenance in the PR. If the maintainers prefer a
  clean anchor, the alternative is a no-op source change plus a version bump
  releasing fresh binaries through the new pipeline; not required.
- **Seeding verification (required).** `slow-tool-tests-release` — the only
  CI job that runs `sha256sum -c` against the bucket — is skipped on the
  seeding PR (no version bump), so nothing in CI fully checks the seed
  against S3. Two mitigations, both mandatory: `slow-tool-tests-dev` runs on
  the PR with install state `clean` (see Install-state detection) and so
  downloads and verifies the amd64 pair through the new path, and before
  merging, the seeder runs the release gate's fetch + `sha256sum -c` loop
  over all four artifacts locally and pastes the output into the PR next to
  the provenance note. Without this, a typo'd or wrong-object seed merges
  green and then hard-fails every clean/pypi download at runtime.
- **Recovery from a wrong committed digest post-merge**: the fast-gate rule
  blocks the direct fix (a sums-only change) by design, so the remedy is a
  no-op injectable change plus a version bump, publishing fresh artifacts
  through the full pipeline. This is deliberate; cheap digest edits are the
  attack surface, and the seeding-verification step above exists to make
  this path never needed.
- Since the sums file is outside the injectable tree, the seeding PR does not
  itself require a version bump.
- Old released wheels keep their current unverified fallback behavior (they
  lack both the code and the sums file); nothing breaks for them, and the S3
  immutability rule keeps their already-bundled glibc binaries and any musl
  objects they fetch by name stable.
- Previously downloaded artifacts already sitting in `binaries/` are not
  retroactively checked (see "What is deliberately not verified"). Users who
  want a clean slate delete `inspect_ai/binaries/` cached downloads;
  subsequent fetches are verified.

## Implementation checklist

| File | Change |
|---|---|
| `src/inspect_ai/tool/_sandbox_tools_utils/SHA256SUMS` | new, seeded via TOFU (four entries, current version) |
| `src/inspect_ai/tool/_sandbox_tools_utils/_digests.py` | new, stdlib-only read/write/lookup (dual import style like `_build_config.py`) |
| `src/inspect_ai/tool/_sandbox_tools_utils/sandbox.py` | rewrite `_download_from_s3`: lookup, then `download()` via `to_thread`, then chmod; integrity failures fatal in strict mode, warn-by-default (soft launch); 404 unchanged; `_check_main_divergence` deliberately untouched (see Install-state detection) |
| `src/inspect_ai/tool/_sandbox_tools_utils/upload_to_s3.py` | version guard, immutability guard, write sums, round-trip verify, commit reminder |
| `scripts/pypi-release.py` | digest-verified downloads, digest-based existence check, unconditional pre-build bundle gate, post-build wheel-contents check |
| `.github/workflows/build.yml` | release-gate lockstep check + `sha256sum -c` over all four artifacts; `check-version-bump` unbumped-direction sums check; `slow-tool-tests-dev` untouched (see "The dev gate") |
| `pyproject.toml` | add `SHA256SUMS` to package data |
| `src/inspect_sandbox_tools/design/RELEASING.md` | new commit-sums step; fail-closed window; immutability rule |
| `.claude/skills/release-sandbox-tools/SKILL.md` | sums commit step; digest-based verify step |
| `CHANGELOG.md` | user-facing entry (downloads now verified against pinned digests) |
| tests | see below |

## Testing

Unit tests (existing sandbox-tools test area; httpx mocked by patching
`httpx.stream` with a fake, following the pattern in
`tests/util/test_download.py`, or via a local test server — no real S3):

- `_digests.py`: round-trip write/parse; `*` marker tolerated; missing-entry
  lookup raises.
- `_download_from_s3`: success verifies, chmods, and lands atomically; digest
  mismatch in strict mode raises and leaves neither `dest` nor any tempfile
  in `binaries/`, by default warns and installs the unverified bytes; 404
  returns `False`; missing sums entry in strict mode raises without any
  network call, by default warns and downloads unverified.
- Sums format: a test asserting every `SHA256SUMS` entry filename parses via
  `filename_to_config`, has no `-dev` suffix, all entries share one version,
  and the four arch×libc combinations are each present exactly once. This
  test deliberately does not assert that the shared version equals
  `version.txt`'s. On every release PR the version bumps at PR-open while
  the sums are rewritten only at post-approval upload, so a lockstep
  assertion here would keep the fast test suite red for the whole review
  window. Version lockstep belongs solely to the release gate, the job that
  is legitimately red during that window.
  (`inspect_ai._util.download` itself already has direct coverage in
  `tests/util/test_download.py`.)
- `pypi-release.py` verification helpers: mismatch on download and mismatch on
  pre-existing file both fail; pre-build gate rejects extra/missing/wrong
  files; wheel-contents check rejects a wheel missing `SHA256SUMS` or
  `sandbox_tools_version.txt`.

End-to-end: the existing `slow-tool-tests-release` gate exercises the real
S3 fetch + verify on every release PR; no new slow test needed.
