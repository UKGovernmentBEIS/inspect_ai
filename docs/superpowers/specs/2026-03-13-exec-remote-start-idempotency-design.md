# Idempotent exec_remote RPCs via Request ID

## Problem

exec_remote RPCs are vulnerable to lost responses. If the host sends an RPC and the connection drops after the server processes it but before the response arrives, the host retries blindly:

- **`exec_remote_start`**: Retrying spawns a duplicate orphan process.
- **`exec_remote_poll`**: Retrying gets empty output (buffers were already drained). If the lost response was the terminal poll (state=completed), the job was cleaned up and the retry gets "No job found".
- **`exec_remote_write_stdin`**: Retrying writes the data a second time.
- **`exec_remote_kill`** / **`exec_remote_close_stdin`**: Retrying gets empty output (buffers drained).

The existing retry logic (added for transient connection failures) handles the case where the RPC never reached the server. This spec addresses the complementary case: the RPC executed but the response was lost.

## Design

### Approach: Client-generated request_id with server-side response caching

Every RPC call from the host includes a `request_id` (a `shortuuid`). The server:

1. Checks if it has a cached response for that `request_id`.
2. If yes, returns the cached response without re-executing (idempotent replay).
3. If no, executes normally and caches the response before returning.

### Host-side changes (`src/inspect_ai/util/_sandbox/exec_remote.py`)

All RPC calls pass a `request_id` param. Each call generates a fresh `shortuuid`.

A `request_id` is only useful when the call may be retried, and retrying is only safe when the server can deduplicate. Therefore, we generate `request_id` if and only if a `retry_policy` is set. These are coupled: enabling retry on `_start()` and `write_stdin()` is only safe *because* of the `request_id` addition — they must land together.

- `_start()` — now calls `_rpc()` with `retry_policy=CLEANUP_RETRY`.
- `_poll()` — already retries with `POLL_RETRY`, now also passes `request_id`.
- `write_stdin()` — now calls `_rpc()` with `retry_policy=CLEANUP_RETRY`.
- `kill()` / `close_stdin()` — already retry with `CLEANUP_RETRY`, now also pass `request_id`.

The `request_id` generation is centralized in `_rpc()`:

```python
async def _rpc(self, method, params, result_type, retry_policy=None):
    if retry_policy is not None:
        import shortuuid
        params = {**params, "request_id": shortuuid.uuid()}

    async def call():
        return await exec_model_request(...)

    if retry_policy is None:
        return await call()

    retrying = retry(...)
    return await retrying(call)()
```

### Server-side changes (`src/inspect_sandbox_tools/`)

**`tool_types.py`** — Add optional `request_id` to all param types:
```python
class SubmitParams(BaseModel):
    request_id: str | None = None
    # ... existing fields ...

class PollParams(BaseModel):
    request_id: str | None = None
    # ... existing fields ...

# Same for WriteStdinParams, KillParams, CloseStdinParams
```

**`_controller.py`** — Add per-job response cache and start dedup map:

```python
class Controller:
    def __init__(self) -> None:
        self._jobs: dict[int, Job] = {}
        # Start dedup: request_id -> pid (prevents duplicate process spawning)
        self._start_request_ids: dict[str, int] = {}
        self._pid_to_start_request_id: dict[int, str] = {}
        # Response cache: pid -> (request_id, response)
        # Only the last response per job is cached. This is safe because the
        # host sends RPCs sequentially per process (never concurrent).
        self._last_response: dict[int, tuple[str, object]] = {}
```

For `submit()` — dedup check:
```python
async def submit(self, ..., request_id: str | None = None) -> int:
    if request_id and request_id in self._start_request_ids:
        return self._start_request_ids[request_id]

    job = await Job.create(...)
    self._jobs[job.pid] = job
    if request_id:
        self._start_request_ids[request_id] = job.pid
        self._pid_to_start_request_id[job.pid] = request_id
    return job.pid
```

For `poll()` — response cache with terminal state handling:
```python
async def poll(self, pid: int, request_id: str | None = None) -> PollResult:
    # Check response cache
    if request_id and pid in self._last_response:
        cached_rid, cached_response = self._last_response[pid]
        if cached_rid == request_id:
            return cached_response  # type: ignore[return-value]

    # Execute normally
    job = self._get_job(pid)
    result = await job.poll()

    # Cache before cleanup (cleanup may remove the job)
    if request_id:
        self._last_response[pid] = (request_id, result)

    if result.state in ("completed", "killed"):
        self._cleanup_job(pid)

    return result
```

For `kill()` — response cache with cleanup:
```python
async def kill(self, pid: int, request_id: str | None = None) -> KillResult:
    # Check response cache
    if request_id and pid in self._last_response:
        cached_rid, cached_response = self._last_response[pid]
        if cached_rid == request_id:
            return cached_response  # type: ignore[return-value]

    job = self._get_job(pid)
    stdout, stderr = await job.kill()
    result = KillResult(stdout=stdout, stderr=stderr)

    # Cache before cleanup
    if request_id:
        self._last_response[pid] = (request_id, result)

    self._cleanup_job(pid)
    return result
```

Same pattern for `write_stdin()` and `close_stdin()` — check cache, execute, cache result. These do not trigger job cleanup, so the pattern is simpler (no cleanup step).

Shared cleanup helper:
```python
def _cleanup_job(self, pid: int) -> None:
    """Remove job from registry and clean up start dedup map.

    Note: _last_response[pid] is intentionally kept so retries of the
    terminal poll/kill can still get the cached response.
    """
    if self._jobs.pop(pid, None) is not None:
        await job.cleanup()
    rid = self._pid_to_start_request_id.pop(pid, None)
    if rid:
        self._start_request_ids.pop(rid, None)
```

**`json_rpc_methods.py`** — Add `request_id=params.request_id` to each controller method call:
```python
# exec_remote_start
pid = await controller.submit(
    params.command,
    input=params.input,
    stdin_open=params.stdin_open,
    env=params.env,
    cwd=params.cwd,
    request_id=params.request_id,
)

# exec_remote_poll
result = await controller.poll(params.pid, request_id=params.request_id)

# exec_remote_kill
result = await controller.kill(params.pid, request_id=params.request_id)

# Same pattern for write_stdin, close_stdin
```

### Output in cached responses

When a response is lost and the retry hits the cache, the cached response includes the stdout/stderr that was drained during the original execution. This output is safe from duplication: the original response was never received by the client, so this is the first time the client sees it. Any *new* output produced between the original call and the retry will be picked up by the next poll — it is delayed, not lost.

### Memory bounds

- `_start_request_ids` / `_pid_to_start_request_id`: One entry per active job. Cleaned up on completion.
- `_last_response`: One entry per job that has ever had an RPC call. Each new RPC for a job overwrites the previous entry, so there is at most one entry per pid (active or completed). Completed entries linger until pid reuse or controller destruction. Bounded by total distinct pids over the controller lifetime (typically a single eval run). Each entry holds one small response object.

### Backward compatibility

**New client → old server**: `SubmitParams` and other param types use `model_config = {"extra": "forbid"}`, so an old server rejects requests with the unknown `request_id` field. Since the host injects the server binary into the container, both sides update atomically in practice. We accept this tight coupling.

**Old client → new server**: Works unchanged. Missing `request_id` defaults to `None`, all caching/dedup is skipped.

### PID recycling safety

If the OS recycles a pid (a completed job's pid is assigned to a new process), the stale `_last_response[pid]` entry from the old job is harmlessly overwritten by the first RPC to the new job. The `_start_request_ids` map is already cleaned up on completion, so no collision there. The stale cache entry cannot produce incorrect results because the new job's RPCs use fresh `request_id` values that will never match the old cached `request_id`.

### Terminal response retention

When a terminal poll or kill response is cached, the `_last_response[pid]` entry is intentionally *not* removed during job cleanup. This ensures that if the terminal response was lost, the retry can still return the cached result even though the job no longer exists in `_jobs`. The entry lingers harmlessly and is overwritten if the pid is reused.
