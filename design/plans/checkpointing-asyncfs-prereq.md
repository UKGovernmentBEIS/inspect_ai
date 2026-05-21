# Checkpointing: AsyncFilesystem conversion (write-path prereq)

## Context

Phase 3's only remaining write-side gap is real `s3://` / remote
`checkpoints_location` support. The actual S3 enablement involves
restic URL translation (`s3://` → `s3:<endpoint>/...`), AWS credential
propagation into the restic subprocess, and a different shape for
`tarfile.extractall` against a remote `dest_repo`.

This prereq is the precondition pass: it switches every sync-FS access
on the checkpointing **write path** to the project's async filesystem
abstraction (`inspect_ai._util.asyncfiles.AsyncFilesystem`). After
this, the S3 enablement step narrows to (1) URL/cred plumbing into
restic and (2) a remote-aware replacement for `tarfile.extractall`.

`AsyncFilesystem` is already established at the eval entrypoint
(`_eval/eval.py:331, 1089` wrap `run_task_app` in `with_async_fs`),
so checkpointing code can rely on `get_async_filesystem()` returning
a live instance throughout a sample run.

Resume-side conversions are deferred.

## Scope

### Sites to convert (write path only)

- **`util/_checkpoint/_layout/sample_checkpoints_dir.py`** — all 4 uses
  of `filesystem()`:
  - `has_sample_checkpoint`
  - `ensure_sample_checkpoints_dir`
  - `ensure_restic_config`
  - `scan_latest_committed_id` (becomes `async def`)
- **`util/_restic/ops.py:init_repo`** — `Path(repo).mkdir(...)` and
  `(Path(repo)/"config").exists()`.
- **`util/_checkpoint/_sandbox_restic/egress.py:egress_sandbox`** — the
  `Path(dest_repo).mkdir(parents=True, exist_ok=True)` call only.
- **`util/_checkpoint/checkpointer_impl.py:_scan_next_checkpoint_id`** —
  `Path.is_dir()` + `.glob("ckpt-*.json")`. Becomes `async def`.

### Explicitly out of scope

- **Resume conversions.** `hydrate.py:_fs_copy_*`, `host_context.read`
  via `local_path`, `ingress_sandbox`'s `Path(src_repo).rglob`, the
  `Path(host_repo).parent` string-as-Path manipulation. Write-first
  per user direction.
- **Host-local-only paths** that will never carry an S3 URL: sample
  working dir (`_layout/working_dir.py`, `_layout/host_context.py`),
  the restic post-restore reorg in `restore_repo`.
- **`_extract_tar` (`tarfile.extractall(dest_repo)`).** Local-only by
  shape; needs a different fix for remote `dest_repo` (extract-to-
  staging + fsspec `put_file`, or fsspec streaming). Bundles with the
  actual S3 enablement step.
- **Promoting `mkdir` onto `AsyncFilesystem` itself.** Local helper for
  now; revisit promotion after the S3 step.

## New helper

New module `src/inspect_ai/util/_checkpoint/_async_fs.py` exposing one
function:

```python
async def async_mkdir(path: str, *, exist_ok: bool = True) -> None:
    """Async mkdir across local and remote filesystems.

    For S3 URLs this is a no-op (S3 has no directory concept). For
    everything else, delegates to sync ``filesystem(path).mkdir(...)``
    via ``anyio.to_thread.run_sync``.
    """
```

Implementation: `is_s3_filename` check → short-circuit; otherwise
`anyio.to_thread.run_sync(lambda: filesystem(path).mkdir(path, exist_ok=exist_ok))`.
Reuses the existing sync `filesystem()` wrapper from
`inspect_ai._util.file` (already has S3-friendly mkdir semantics at
line 194). The S3 short-circuit avoids an unnecessary boto3 round
trip.

## Per-site changes

### `_layout/sample_checkpoints_dir.py`

- Drop the `_blocking` inner helpers and the `anyio.to_thread.run_sync`
  wrappers; the public functions become directly async.
- `has_sample_checkpoint`: `await async_fs.exists(sample_dir)` then
  `async for path in async_fs.iter_files(sample_dir, pattern="ckpt-*.json"):
   return True`.
- `ensure_sample_checkpoints_dir`: `await async_mkdir(eval_dir)`,
  `await async_mkdir(sample_dir)`.
- `ensure_restic_config`: `await async_fs.exists(...)` →
  `await async_fs.read_file(...)` or `await async_fs.write_file(...)`.
- `scan_latest_committed_id`: `async def`. `iter_files(...,
  pattern="ckpt-*.json")` to enumerate, `read_file(...)` to validate.

### `_restic/ops.py:init_repo`

`_restic` is a use-case-agnostic package (also used by the prefetch
CLI per `design/plans/checkpointing-phasing.md` §Phase 1); it cannot
import from `_checkpoint`. Resolve by splitting the responsibilities:

- **Move dir creation to the caller.** `init_repo` no longer mkdirs;
  callers (`hydrate`, sandbox init) ensure the repo dir exists before
  calling. For checkpointing callers this is one line:
  `await async_mkdir(host_repo)` (and likewise for sandbox-side repo
  init paths).
- **Use `get_async_filesystem()` for the existence check.** Replace
  `(Path(repo)/"config").exists()` with
  `await get_async_filesystem().exists(f"{repo}/config")`. This makes
  `_restic/ops.py` import from `inspect_ai._util.asyncfiles` only —
  not from `_checkpoint`.

`init_repo`'s docstring updates to reflect the new contract: caller
guarantees the repo dir exists; `init_repo` returns immediately if
already initialized.

### `_sandbox_restic/egress.py:egress_sandbox`

`Path(dest_repo).mkdir(parents=True, exist_ok=True)` →
`await async_mkdir(dest_repo)`. `_extract_tar` unchanged (S3-task).

### `checkpointer_impl.py:_scan_next_checkpoint_id`

Becomes `async def`. Uses
`async for path in get_async_filesystem().iter_files(sample_dir,
pattern="ckpt-*.json"):` to enumerate ids. Single caller in `_fire`
adds `await`.

## Caller updates

- **`hydrate.py:_hydrate`** Phase 1 — add `await async_mkdir(host_repo)`
  before the host `init_repo` call. Add equivalent
  `await async_mkdir(sandbox_repo_path)` for each sandbox-side
  destination repo path that previously relied on `init_repo` to
  mkdir.
- **`hydrate.py`** call to `scan_latest_committed_id` —
  `await scan_latest_committed_id(...)` instead of `to_thread.run_sync(scan_latest_committed_id, ...)`.
- **`checkpointer_impl._fire`** — `await _scan_next_checkpoint_id(...)`.

## Verification

1. `pytest tests/checkpoint/ -v` — all existing tests pass on local FS.
2. `examples/checkpoint_ctf.py` runs end-to-end on local FS unchanged
   (golden path + interrupted-resume scenario).
3. `mypy --exclude tests/test_package src tests` clean.
4. `ruff check --fix` clean.

No new tests added in this PR — the prereq is a behavior-preserving
mechanical conversion. S3 tests land with the S3-enablement step.

## Unresolved questions

- Promotion of `async_mkdir` to `AsyncFilesystem.mkdir()` — defer until
  after the S3 enablement step.
