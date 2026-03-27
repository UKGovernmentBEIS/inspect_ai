# Design: exec_remote Transport Encapsulation

## Problem

exec_remote uses `sandbox.exec()` as an internal transport for its JSON-RPC protocol. Currently, transport failures (K8s WebSocket drops, connection errors) and application errors (JSON-RPC error responses) both surface as Python exceptions, requiring `_is_transient()` to classify them after the fact. This classification is fragile — it must enumerate provider-specific exception types — and was rejected in PR #3468 review as overstepping exec_remote's responsibility.

## Insight

The transport/application distinction should be structural, not heuristic. `sandbox.exec()` either succeeds (returns stdout) or fails (raises an exception). If it succeeds, the JSON-RPC response in stdout is an application-level result — success or error. If it fails, it's always a transport problem. By splitting the `_rpc()` method to call the transport and parse the response in separate steps, the distinction becomes impossible to confuse.

## Design

### Core change: split `_rpc()` into transport + parse

Currently `_rpc()` calls `exec_model_request()`, which combines transport and JSON-RPC parsing. After this change, `_rpc()` calls the transport directly and parses separately:

```python
async def _rpc(self, method, params, result_type, retry_policy=None):
    if retry_policy is not None:
        params = {**params, "request_id": shortuuid.uuid()}

    async def call() -> str:
        # Only thing that can raise — always transport.
        return await self._transport(
            method=method, params=params, is_notification=False,
            timeout=RPC_TIMEOUT, user=self._options.user,
            concurrency=self._options.concurrency,
        )

    if retry_policy is None:
        raw = await call()
    else:
        try:
            retrying = retry(
                wait=retry_policy.wait, stop=retry_policy.stop,
                retry=retry_if_exception(_should_retry),
                before_sleep=log_retry(method),
            )
            raw = await retrying(call)()
        except RetryError as e:
            raise ExecRemoteTransportError(
                f"Failed to reach sandbox after retries: method={method}, "
                f"last_error={e.last_attempt.exception()!r}"
            ) from e.last_attempt.exception()

    # Application-level — never retried
    result = parse_json_rpc_response(raw, method, params, GenericJSONRPCErrorMapper)
    return result_type.model_validate(result, strict=True)
```

### `_should_retry()` replaces `_is_transient()`

Nearly eliminates exception-type enumeration. Only excludes system signals and one inspect-owned boundary error:

```python
def _should_retry(exc: BaseException) -> bool:
    """Everything from the transport is retryable, except system signals and resource limits."""
    return not isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError, OutputLimitExceededError))
```

**Why `OutputLimitExceededError`?** `SandboxEnvironmentProxy` wraps every `sandbox.exec()` call and raises `OutputLimitExceededError` if output exceeds 10 MiB — this happens *inside* the transport `call()`, before JSON-RPC parsing. It's a permanent resource limit, not a transport failure. This is the one inspect-owned exception that leaks through the structural boundary; provider-specific exceptions (K8sError, ConnectionError, etc.) still require no enumeration.

This works because `call()` only contains the transport call. Any exception from it is, by definition, a transport failure — with the single exception above. The function doesn't need to know about `K8sError`, `ConnectionError`, `RuntimeError`, `SandboxExecError`, or any other provider type.

### New error type

```python
class ExecRemoteTransportError(RuntimeError):
    """Raised when exec_remote cannot communicate with the sandbox after retries."""
```

Callers of exec_remote only see:
- **Application errors** from JSON-RPC error mapper (`RuntimeError`, `ValueError`) — the command failed, bad params, etc.
- **`ExecRemoteTransportError`** — transport is down after retries exhausted
- **`OutputLimitExceededError`** — output too large (raised by `SandboxEnvironmentProxy` inside the transport call; excluded from retry)

No provider-specific exceptions leak through exec_remote.

### What stays from PR #3468

The idempotency layer is unchanged:
- `request_id` injection in `_rpc()` when retry_policy is set
- Server-side response caching in Controller (`_last_response`, `_check_cache`, `_store_cache`)
- Server-side start dedup (`_start_request_ids`, `_pid_to_start_request_id`)
- `request_id` field on all `tool_types` param models
- Retry policies (`_POLL_RETRY`, `_CLEANUP_RETRY`)
- `log_retry()` callback

### What changes

- `_is_transient()` → replaced with `_should_retry()` (3 lines instead of 15)
- `_rpc()` → calls transport directly, parses JSON-RPC response separately
- New `ExecRemoteTransportError` for retry exhaustion
- `SandboxExecError` no longer load-bearing for retry classification (can remain for error messages)

### What's removed

The concept of "transient error classification." exec_remote no longer attempts to identify which provider errors are transient. It simply encapsulates its own transport: any exception from `sandbox.exec()` is exec_remote's problem to handle.

## Testing

### New/updated tests
- Transport exception (any type) → retried
- Transport exception after retries exhausted → `ExecRemoteTransportError`
- `CancelledError` → not retried, propagates immediately
- `OutputLimitExceededError` from transport → not retried, propagates immediately
- Successful transport + JSON-RPC success → returns parsed result
- Successful transport + JSON-RPC error → raises application error, not retried
- Malformed JSON-RPC response (valid transport, invalid JSON) → not retried, raises parse error
- `request_id` injected when retry_policy set, absent when None

### Unchanged tests
- Server-side controller caching/dedup
- Start dedup

### Removed tests
- `_is_transient()` classification tests

## Files Changed

| File | Change |
|------|--------|
| `src/inspect_ai/util/_sandbox/exec_remote.py` | Rewrite `_rpc()`, replace `_is_transient` with `_should_retry`, add `ExecRemoteTransportError` |
| `tests/util/sandbox/test_exec_remote.py` | Update retry tests to match new behavior |
