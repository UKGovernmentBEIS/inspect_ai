# Design: Provider-Classified Transient Errors

## Problem

exec_remote retries transport failures from `sandbox.exec()`, but it decides what's transient using a deny-list (`_should_retry`). PR #3468 reviewer JJ objects: the provider has locality of knowledge about which errors are transient — exec_remote should not be classifying errors from providers it knows nothing about.

The current deny-list approach retries everything except four exception types. This means any new provider's permanent errors (permission denied, container deleted) get silently retried unless they happen to match one of the four excluded types.

## Insight

Split the responsibility: the provider classifies, exec_remote retries. A new `SandboxTransientError` exception in the sandbox API lets providers explicitly mark transient failures. exec_remote retries only that type — zero provider knowledge needed.

## Design

### New exception in sandbox API

```python
# src/inspect_ai/util/_sandbox/environment.py
class SandboxTransientError(RuntimeError):
    """Raised by sandbox providers for transient transport failures.

    Providers MUST only raise this for failures they believe are transient
    (connection drops, API server rotation, WebSocket failures, etc.) —
    never for permanent errors (permission denied, container not found, etc.).

    Callers that support retry (exec_remote, bash_session) MAY retry when
    they see this exception. Callers without retry logic will see it as a
    regular RuntimeError.
    """
```

### exec_remote `_should_retry` simplification

```python
def _should_retry(exc: BaseException) -> bool:
    """Retry only what the provider told us is transient."""
    return isinstance(exc, SandboxTransientError)
```

Replaces the current deny-list (CancelledError, SystemExit, KeyboardInterrupt, OutputLimitExceededError). No special cases needed — if the provider didn't raise `SandboxTransientError`, it's not retried.

### What stays unchanged

- `_rpc()` structural split: transport `call()` → `parse_json_rpc_response()` (application errors never retried)
- `_RetryPolicy`, `_POLL_RETRY`, `_CLEANUP_RETRY` constants
- `ExecRemoteTransportError` raised on retry exhaustion
- `request_id` injection and server-side idempotency/caching
- `_log_retry()` callback

### What changes

| Before | After |
|--------|-------|
| `_should_retry` deny-list (4 exception types) | `isinstance(exc, SandboxTransientError)` |
| Retries everything except 4 types | Retries only 1 type |
| exec_remote decides what's transient | Provider decides what's transient |

### Provider-side change (out of scope for this PR)

The k8s provider (`inspect-k8s-sandbox`, separate repo) would add:

```python
except (K8sError, ConnectionError, ...) as e:
    raise SandboxTransientError(str(e)) from e
```

This is a future PR to that repo. For the PoC, tests mock the provider raising `SandboxTransientError`.

## Testing

### Updated tests

- Flaky sandbox helpers raise `SandboxTransientError` instead of `ConnectionError`
- `test_not_retried` parametrized cases:
  - `ConnectionError` → not retried (provider didn't classify)
  - `RuntimeError` → not retried
  - `asyncio.CancelledError` → not retried
  - `OutputLimitExceededError` → not retried
- Existing retry-success and retry-exhaustion tests work unchanged (just different exception type in mock)

### Removed tests

- No `_should_retry` deny-list tests needed (the function is one line)

## Files Changed

| File | Change |
|------|--------|
| `src/inspect_ai/util/_sandbox/environment.py` | Add `SandboxTransientError` |
| `src/inspect_ai/util/_sandbox/exec_remote.py` | Simplify `_should_retry` to one line |
| `tests/util/sandbox/test_exec_remote.py` | Update mock exceptions and not-retried test cases |

## Consequences

**Positive:**
- Addresses JJ's "locality of knowledge" objection directly
- exec_remote has zero provider knowledge
- New providers get retry by raising one exception type
- Existing providers that don't raise it get no retry (safe default)
- `_should_retry` is trivially correct — no edge cases

**Negative:**
- Until the k8s provider is updated, no retry actually happens in production (k8s raises `K8sError`, not `SandboxTransientError`)
- Adds a new public exception type to the sandbox API surface
- Requires a coordinated change: inspect_ai defines the type, each provider adopts it separately
