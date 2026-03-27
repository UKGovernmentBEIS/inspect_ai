# Design: Retry Logic for bash_session()

## Problem

`bash_session()` uses the same `SandboxJSONRPCTransport` as `exec_remote` to communicate with sandbox containers via JSON-RPC over `sandbox.exec()`. When K8s API server rotations or other transient network events drop WebSocket connections, these RPCs fail and surface as errors to the model. Unlike `exec_remote`, `bash_session` has no retry logic — any transient transport failure kills the tool call.

## Goal

Add retry-with-idempotency to `bash_session()` RPCs, following the proven pattern from `exec_remote`. Transient transport errors should be retried transparently; application errors should propagate immediately.

## Design

### 1. Shared Retry Module

**New file:** `src/inspect_ai/util/_sandbox/_rpc_retry.py`

Extract from `exec_remote.py`:
- `RetryPolicy` dataclass — holds `wait` and `stop` tenacity config
- `is_transient()` — exception filter (retries `SandboxExecError`, `ConnectionError`, `K8sError`, etc.; skips `RuntimeError`, `ValueError`, `OutputLimitExceededError`, `ToolError`, `ToolParsingError`, `CancelledError`)
- `log_retry(method_name)` — tenacity `before_sleep` callback factory; uses generic "RPC retry" prefix (not hardcoded "exec_remote")
- Pre-built policies: `POLL_RETRY`, `CLEANUP_RETRY`

`exec_remote.py` imports from here (no behavior change). `bash_session.py` imports the same utilities.

**Error mapper compatibility:** `exec_remote` uses `GenericJSONRPCErrorMapper` (raises `RuntimeError`, `ValueError`). `bash_session` uses `SandboxToolsErrorMapper` (raises `ToolError`, `ToolParsingError`, `RuntimeError`). The shared `is_transient()` must exclude all four application-error types so neither mapper's errors get incorrectly retried.

### 2. Host-Side Changes (`_bash_session.py`)

Add two module-level `_rpc` async functions — one for model results, one for scalar results — since `new_session` uses `exec_model_request` and `interact` uses `exec_scalar_request`:

```python
async def _rpc_model(
    method: str,
    params: dict[str, object],
    result_type: type[T],
    transport: SandboxJSONRPCTransport,
    timeout: int,
    user: str | None,
    retry_policy: RetryPolicy | None = None,
) -> T:
    if retry_policy is not None:
        params = {**params, "request_id": shortuuid.uuid()}

    async def call() -> T:
        return await exec_model_request(
            method=method, params=params, result_type=result_type,
            transport=transport, error_mapper=SandboxToolsErrorMapper,
            timeout=timeout, user=user,
        )

    if retry_policy is None:
        return await call()

    retrying = retry(
        wait=retry_policy.wait, stop=retry_policy.stop,
        retry=retry_if_exception(is_transient),
        before_sleep=log_retry(method),
    )
    return await retrying(call)()


async def _rpc_scalar(
    method: str,
    params: dict[str, object],
    result_type: type[T],
    transport: SandboxJSONRPCTransport,
    timeout: int,
    user: str | None,
    retry_policy: RetryPolicy | None = None,
) -> T:
    # Same as _rpc_model but calls exec_scalar_request
    ...
```

Both RPC call sites use these wrappers:

| Call | Function | Policy | Rationale |
|------|----------|--------|-----------|
| `bash_session_new_session` | `_rpc_model` | `CLEANUP_RETRY` | Quick operation; dedup prevents orphan sessions |
| `bash_session` (interact/restart) | `_rpc_scalar` | `CLEANUP_RETRY` | All actions safe with server-side dedup |

### 3. Container-Side Changes

#### 3a. Type Changes (`tool_types.py`)

Add `request_id: str | None = None` to `BashBaseParams`. This propagates to `InteractParams` and `RestartParams` via inheritance. Note: `BashBaseParams` has `extra = "forbid"`, so the field must be added to the model — it cannot be passed as an extra kwarg. Host-side and container-side changes must ship in the same release.

Add a `NewSessionParams` model with `request_id: str | None = None` for the `bash_session_new_session` method (currently uses `NoParams`, which silently drops extra fields).

#### 3b. JSON-RPC Method Handlers (`json_rpc_methods.py`)

Pass `request_id` through to controller methods.

#### 3c. Controller Caching (`_controller.py`)

Add request_id-based dedup following exec_remote's pattern:

**`new_session(request_id)`:**
- `_new_session_request_ids: dict[str, str]` — maps request_id → session_name
- If request_id is in the dict, return existing session_name
- Otherwise create session, store mapping, return name
- This dict grows unbounded for the lifetime of the controller (one entry per new_session call). Acceptable since sessions are few per eval, but noted for awareness.

**`interact(session_name, ..., request_id)`:**
- `_last_response: dict[str, tuple[str, str]]` — maps session_name → (request_id, result)
- Before executing: check if request_id matches cached entry → return cached result
- After executing: store (request_id, result)
- Only caches the **last** response per session (sufficient because retries are always for the most recent call)
- For `read` actions specifically: the PTY read is destructive (buffer is consumed). If the first attempt succeeds server-side but the response is lost, the retry returns the cached output. Any new PTY output that accumulated between failure and retry is picked up on the next `read` call. If the first attempt never reached the server (transport failed before delivery), the retry has a new request_id and executes fresh — this is correct.

**`restart(session_name, ..., request_id)`:**
- `_last_restart: dict[str, str]` — maps session_name → request_id
- If request_id matches, return immediately (restart already happened)
- Otherwise restart, store request_id
- Without dedup, a double-restart could race: the session's PTY process may be in a torn-down state from the first restart when the second arrives, causing unpredictable behavior.

**`request_id=None` (backwards compat):** All caching is skipped when request_id is None. This maintains compatibility with older host-side code.

### 4. Idempotency Analysis by Action

| Action | Retry safe without dedup? | With dedup? | Notes |
|--------|--------------------------|-------------|-------|
| `new_session` | No — creates orphan session | Yes | Dedup returns existing session |
| `read` | No — PTY buffer consumed | Yes | Cache returns original output; new output on next read |
| `type` | No — double keystrokes | Yes | Cache prevents re-execution |
| `type_submit` | No — double keystrokes | Yes | Cache prevents re-execution |
| `interrupt` | No — could interrupt a new command if model sent type_submit right after | Yes | Cache for consistency |
| `restart` | No — race if session mid-teardown | Yes | Dedup skips redundant restart |

## Testing

### Shared retry module tests (`tests/util/sandbox/test_rpc_retry.py`)
- `is_transient()` correctly classifies: `SandboxExecError` (yes), `ConnectionError` (yes), `RuntimeError` (no), `ValueError` (no), `OutputLimitExceededError` (no), `ToolError` (no), `ToolParsingError` (no), `CancelledError` (no), `KeyboardInterrupt` (no)
- `log_retry()` produces generic "RPC retry" log messages (not tool-specific)

### Controller caching tests (`src/inspect_sandbox_tools/tests/test_bash_session_controller.py`)
- `new_session` with same request_id returns same session name
- `new_session` with different request_id creates new session
- `new_session` with `request_id=None` always creates new session (no caching)
- `interact` with same request_id returns cached result without re-executing
- `interact` with different request_id executes and caches
- `interact` with `request_id=None` always executes (no caching)
- `restart` dedup works correctly
- Param models accept `request_id` field without Pydantic validation error

### Host-side retry tests (`tests/tools/test_bash_session_retry.py`)
- Mock transport to fail transiently → verify retry succeeds (test both `_rpc_model` and `_rpc_scalar` paths)
- Mock transport to fail with `ToolError` → verify no retry
- Mock transport to fail with `ToolParsingError` → verify no retry
- Verify `request_id` is injected when retry_policy is set
- Verify `request_id` is NOT injected when retry_policy is None

### Existing test changes
- `tests/util/sandbox/test_exec_remote.py` — move `is_transient()` tests to `test_rpc_retry.py`; exec_remote-specific retry tests stay

## Files Changed

| File | Change |
|------|--------|
| `src/inspect_ai/util/_sandbox/_rpc_retry.py` | **New** — shared retry utilities |
| `src/inspect_ai/util/_sandbox/exec_remote.py` | Import from `_rpc_retry` instead of defining locally |
| `src/inspect_ai/tool/_tools/_bash_session.py` | Add `_rpc_model()`/`_rpc_scalar()` wrappers, use retry on both call sites |
| `src/inspect_sandbox_tools/.../bash_session/tool_types.py` | Add `request_id` to `BashBaseParams`; add `NewSessionParams` |
| `src/inspect_sandbox_tools/.../bash_session/json_rpc_methods.py` | Use `NewSessionParams`; pass `request_id` to controller |
| `src/inspect_sandbox_tools/.../bash_session/_controller.py` | Add response caching + dedup |
| `tests/util/sandbox/test_rpc_retry.py` | **New** — shared retry tests (moved from test_exec_remote) |
| `tests/tools/test_bash_session_retry.py` | **New** — bash_session host-side retry tests |
| `src/inspect_sandbox_tools/tests/test_bash_session_controller.py` | **New** — controller caching tests |
| `tests/util/sandbox/test_exec_remote.py` | Remove `is_transient()` tests (moved to test_rpc_retry) |
