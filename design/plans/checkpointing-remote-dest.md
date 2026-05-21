# Checkpointing: remote sample checkpoints dir support (write side)

## Context

Phase 3's last open write-side item: support a remote **sample
checkpoints dir** (`s3://`, plus any other
`AsyncFilesystem`-resolvable URI) so that an eval's checkpoint state
lands at the destination and is durable across machines. Setting
`CheckpointConfig.checkpoints_location` to a remote URI is one path to
this state; another is the eval log itself being remote with no
override.

The "restic talks directly to S3" design is ruled out because restic's
S3 backend speaks only the env-var / `~/.aws/credentials` axis of AWS
auth. Modern flows (SSO, `~/.aws/config` profiles, assume-role) are
invisible to it. Customers would have to know that "checkpointing
needs static keys," which leaks the restic implementation detail and
breaks long-running evals (SSO temps refresh but restic can't
re-authenticate mid-run).

Instead: **restic always writes locally**, and a host-side egress hop
ships state to the destination via `AsyncFilesystem` — which the
inspect process already uses for checkpoint file I/O and logs, and which
transparently honors the full boto3 credential chain (including SSO
refresh) and equivalents for non-AWS schemes.

`AsyncFilesystem` is the exclusive filesystem abstraction. The plan
does not reference `fsspec` directly even though `AsyncFilesystem`
sits on top of it; consumers stay above the abstraction.

Resume conversions are out of scope; tracked separately.

## Vocabulary

Per `src/inspect_ai/util/_checkpoint/UBIQUITOUS_LANGUAGE.md`:

- **Sample checkpoints dir** — destination. Always exists. May be local
  or remote. Layout: `ckpt-*.json` checkpoint files at the root,
  `restic/restic-config.json`, `restic/host/`, `restic/sandboxes/<name>/`,
  and (when destination is local) `context/`.
- **Sample staging dir** — per-sample host-local directory; exists
  only when destination is remote. Path:
  `inspect_cache_dir("checkpoints")/<log-basename>/<sample-id>__<epoch>/`.
- **Context subdir** — `<sample_root>/context/`. The host context
  files restic backs up each fire (`events.json`, `store.json`, etc.).
  Replaces the former top-level "sample working dir."
- **Host egress** — the new hop that ships staging-dir contents
  (everything except the context subdir and the manifest) to the
  remote sample checkpoints dir each fire. Mirrors the existing
  **sandbox egress** algorithm: manifest-diff + two-phase commit.

`<sample_root>` above is shorthand for "wherever restic and checkpoint
files are written locally" — `sample_checkpoints_dir` when local, the
**sample staging dir** when remote.

## Topology

### Local destination (no staging dir)

```
<sample_checkpoints_dir>/                 # final destination, local
  restic/restic-config.json
  ckpt-*.json
  restic/host/                              # restic repo
  restic/sandboxes/<name>/                   # restic repo(s)
  context/                                # host context files; restic source
```

### Remote destination (staging dir present)

```
<sample_staging_dir>/                     # host-local (inspect_cache_dir)
  restic/restic-config.json
  ckpt-*.json
  restic/host/
  restic/sandboxes/<name>/
  context/
  .egress-manifest.txt
<sample_checkpoints_dir>/                 # final destination, remote (e.g. s3://...)
  restic/restic-config.json
  ckpt-*.json
  restic/host/
  restic/sandboxes/<name>/
  # (no context/ — restic source, not part of the checkpoint state)
```

Restic never sees the destination URL in either case. The new layout
also unifies the previously-separate "host-local working" tree
(`inspect_cache_dir/checkpoints/<log>/<sample>/` containing
`events.json` etc.) with the restic-repo + checkpoint file tree: they're now
peer subdirectories of one **sample root**.

## Changes

### 1. Path helpers

New / renamed helpers in `_checkpoint/_layout/`:

```python
def sample_root(
    *, sample_checkpoints_dir: str, sample_staging_dir: str | None
) -> str:
    """Where restic and checkpoint files are first materialized.

    Returns sample_checkpoints_dir when the destination is local
    (sample_staging_dir is None); the sample_staging_dir otherwise.
    """

def is_remote_destination(path: str) -> bool:
    """Whether `path` requires a staging dir + host egress."""

def sample_staging_dir(*, log_location: str, sample_id, epoch) -> str:
    """Per-sample host-local staging path under inspect_cache_dir."""

def host_repo_dir(sample_root: str) -> str:
    """<sample_root>/restic/host/"""

def sandbox_repo_dir(sample_root: str, name: str) -> str:
    """<sample_root>/restic/sandboxes/<name>/"""

def context_dir(sample_root: str) -> str:
    """<sample_root>/context/"""
```

`is_remote_destination` checks `is_s3_filename(path)` for v1; widens
to other schemes as they're exercised.

The old `sample_working_dir` / `eval_working_dir` paths and helpers
(`_layout/working_dir.py`) get repurposed. `ensure_sample_working_dir`
becomes `ensure_sample_staging_dir`; same path computation, used only
when the destination is remote.

### 2. Renames in the on-disk layout

Existing paths shift:

- `<sample_root>/host/` → `<sample_root>/restic/host/`
- `<sample_root>/sandboxes/<name>/` → `<sample_root>/restic/sandboxes/<name>/`
- The host context files (`events.json`, etc.) move into a `context/`
  subdir under the sample root. Previously they were the only thing
  in the sample working dir; now they're a sibling of `restic/host/`.

Restic's `run_backup(source=...)` argument changes from the old
`sample_working_dir` path to the new `<sample_root>/context/` path.

Checkpointing is unreleased; no on-disk back-compat to preserve.

### 3. `_hydrate` Phase 1

Pseudo-flow:

```
sample_checkpoints_dir = compute_destination_path(...)
await ensure_sample_checkpoints_dir(sample_checkpoints_dir)  # async_mkdir

if is_remote_destination(sample_checkpoints_dir):
    sample_staging_dir = compute_staging_path(...)
    await ensure_sample_staging_dir(sample_staging_dir)
    sample_root = sample_staging_dir
else:
    sample_staging_dir = None
    sample_root = sample_checkpoints_dir

await ensure_restic_config(sample_root)
await ensure_context_dir(sample_root)
```

Both `sample_root/restic/host/` and `sample_root/restic/sandboxes/<name>/`
are pure-local from restic's point of view; their parent dirs are
created by `init_repo` (host) and `egress_sandbox`'s existing mkdir
(sandbox).

### 4. `ensure_restic_config` and `write_checkpoint_file`

Accept the sample root as their target dir parameter. Callers pass
the result of `sample_root(...)`.

### 5. `_restic/ops.py:init_repo`

Restic never sees remote paths now. Revert to local-only:
- `Path(repo).mkdir(parents=True, exist_ok=True)` — restore the mkdir
  that was pushed to the caller in the prereq.
- `(Path(repo)/"config").exists()` — local check.

Drop the `inspect_ai._util.asyncfiles` import. `_restic/` stays
generic.

Caller in `_hydrate_host` no longer pre-mkdirs the host repo dir
(init_repo handles it).

### 6. Sandbox egress: `dest_repo` retargets

`egress_sandbox(env, dest_repo=...)`'s `dest_repo` becomes
`<sample_root>/restic/sandboxes/<name>/`. Internal code is unchanged —
`async_mkdir(dest_repo)` and `tarfile.extractall(dest_repo)` are now
guaranteed-local in both topologies.

### 7. Host egress

New module `src/inspect_ai/util/_checkpoint/_host_egress.py`:

```python
async def host_egress(
    *,
    staging_dir: str,
    destination_dir: str,
) -> None:
    """Ship newly-written files from staging_dir to destination_dir.

    Manifest at <staging_dir>/.egress-manifest.txt. Two-phase commit:
    `AsyncFilesystem.write_file(...)` each new file first; only then
    atomically replace the manifest. Crash between the two leaves
    destination ahead of the manifest → next fire re-ships
    (idempotent because restic content is content-addressed and
    checkpoint files overwrite cleanly).
    """
```

Algorithm:

1. Enumerate `staging_dir` recursively. Collect file paths relative
   to `staging_dir`. Exclude `context/` (restic source, not part
   of the checkpoint state) and `.egress-manifest.txt` itself.
2. Read `<staging_dir>/.egress-manifest.txt` (sorted list of
   relative paths previously shipped). Diff vs. enumeration to
   identify new files.
3. If no new files, return.
4. Sort new files into safe-order tiers, mirroring sandbox egress
   Appendix B:
   - `restic/host/config`, `restic/host/keys/*`,
     `restic/sandboxes/<name>/config`, `restic/sandboxes/<name>/keys/*`
     (first cycle for each repo)
   - `**/data/**` (immutable pack files)
   - `**/index/**` (immutable; occasionally consolidated)
   - `**/snapshots/**` (immutable)
   - `restic/restic-config.json` (first cycle)
   - `ckpt-NNNNN.json` last (commit point at destination)
5. For each new file, `await AsyncFilesystem.write_file(...)` (or
   `write_file_streaming` if large).
6. Write new manifest contents to
   `<staging_dir>/.egress-manifest.txt.tmp`, `os.replace` to
   `.egress-manifest.txt` (atomic on POSIX).

All remote I/O goes through `AsyncFilesystem`. No `fsspec` references
in checkpointing code.

### 8. `_fire` flow

```
write host context (to <sample_root>/context/)
restic backup host (source=<sample_root>/context/,
                    repo=<sample_root>/restic/host/) ─┐
per-sandbox:                                        ├── parallel
  restic backup sandbox                             │
  egress_sandbox → <sample_root>/restic/sandboxes/...  ┘
write_checkpoint_file(<sample_root>, checkpoint)    # local "commit"
if remote:
  await host_egress(staging_dir=sample_staging_dir,
                    destination_dir=sample_checkpoints_dir)
                                                    # remote commit
```

Host egress is synchronous within `_fire` — the turn boundary blocks
on shipment, matching sandbox egress today.

`CheckpointEvent` is emitted after both the checkpoint file AND the
host egress (when remote), so the event's "this checkpoint is durable
at the destination" contract holds.

### 9. Failure semantics

- Restic backup / sandbox egress / `write_checkpoint_file` failures:
  same as today; fire fails, no destination mutation, no manifest
  update.
- Host egress fails partway through (file-shipment loop):
  - Some new files at destination; manifest not updated; new
    checkpoint file may or may not have shipped yet.
  - If the checkpoint file didn't ship: destination's prior
    checkpoint file remains the commit point on resume; next fire's
    egress diff re-ships the in-flight files (content-addressed;
    no-op on re-write).
  - If the checkpoint file shipped but a later step failed (rare —
    the checkpoint file is last in safe order): destination has the
    new checkpoint file; resume sees it as committed; next fire
    catches up via manifest diff.
- Manifest rename fails: same recovery as above; manifest re-derives
  on next diff.

Destination's "is this checkpoint committed?" predicate stays
`<destination>/ckpt-NNNNN.json` exists and parses. Same rule as
today, with destination potentially remote.

### 10. Resume readiness (out of scope but the seam matters)

Destination layout after a successful fire is structurally identical
to a local-destination eval's layout (same files + names, modulo the
absent `context/` which is restic input, not output). So a future
remote-resume implementation reads the destination via
`AsyncFilesystem` directly; the staging dir is not consulted
(typically a different machine on resume anyway). When resume needs
the restic repo locally to call `restic restore`, it downloads from
the destination — separate work item.

## Out of scope

- Resume from a remote destination (read-side).
- Staging dir cleanup post-eval (lands with retention work).
- Schemes beyond S3 in v1 — should work via `AsyncFilesystem` but
  not specifically exercised in this PR.

## Verification

1. New unit tests:
   - `tests/checkpoint/test_host_egress.py` — manifest-diff,
     ordering, partial-failure recovery, manifest atomicity. Uses
     `tmp_path` for both staging and destination (local).
2. Existing local-destination tests under `tests/checkpoint/` continue
   to pass after the rename (`host/` → `restic/host/`, etc.) — they're
   the regression guard for the local case.
3. New roundtrip test against `mock_s3` (moto, fixture already in
   `tests/conftest.py`):
   - Run a fire with
     `checkpoints_location="s3://test-bucket/.../foo.checkpoints"`.
   - Assert staging dir has the expected file set.
   - Assert destination (via moto) has the expected file set.
   - Assert checkpoint file at destination parses.
4. Manual: `examples/checkpoint_ctf.py` with
   `checkpoints_location="s3://epateytest2/checkpoints/"` produces
   the expected file shape at the bucket.
5. `pytest tests/checkpoint/` clean.
6. `mypy --exclude tests/test_package src tests` clean.
7. `ruff check` clean.

## Phasing within this PR

Order to keep review tractable:

1. **Renames** (`host/` → `restic/host/`, `sandboxes/` → `restic/sandboxes/`,
   relocating context files to `context/`). Path helpers updated;
   existing local-dest tests adjusted in lockstep. No behavioral
   change to the remote path yet.
2. **Sample working dir / eval working dir concept dissolution**:
   `working_dir.py` → `staging_dir.py` (or similar); host context
   files now live under the sample root.
3. **`_restic/ops.py:init_repo`** reverts to local-only;
   `_hydrate_host` drops the explicit `async_mkdir`.
4. **Staging-dir routing in `_hydrate`**: when remote, compute
   `sample_root = sample_staging_dir` and route the host repo +
   sandbox `dest_repo` paths accordingly.
5. **New `_host_egress` module + standalone tests.**
6. **Wire `host_egress` into `_fire`** at the end (when remote).
7. **Roundtrip test against moto.**

## Unresolved questions

- Listing strategy in `host_egress`: walk staging dir via
  `Path.rglob` (purely local, simplest) versus
  `AsyncFilesystem.iter_files(recursive=True)` (uniform with our
  other listing patterns; ok with sync `Path` because the staging
  dir is always local). Lean `Path.rglob` for staging-side
  enumeration; `AsyncFilesystem.write_file` for the destination
  writes.
- `restic/restic-config.json` is in the manifest once on first cycle. Restic
  passwords don't rotate, so the file is byte-stable — no re-ship.
