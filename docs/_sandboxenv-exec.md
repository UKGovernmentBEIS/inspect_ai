
### exec()

``` python
async def exec(
    self,
    cmd: list[str],
    input: str | bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] = {},
    user: str | None = None,
    timeout: int | None = None,
    timeout_retry: bool = True,
    concurrency: bool = True
) -> ExecResult[str]:
    """
    Raises:
      SandboxCommandTimeoutError: If a command exceeds its execution timeout
        and the provider can distinguish this from a sandbox timeout.
      SandboxTimeoutError: If a sandbox operation times out, or the provider
        cannot distinguish the two cases.
      TimeoutError: Legacy provider timeout, wrapped as SandboxTimeoutError
        when called through sandbox().
      UnicodeDecodeError: May be raised if the sandbox provider
        cannot decode the command output to UTF-8 and does not
        support using the UTF-8 replacement character for
        characters which cannot be decoded.
      PermissionError: If the user does not have
        permission to execute the command.
    """
    ...
```

The `exec()` method should enforce an output limit of `SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE` (default 10MB, configurable via the `INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE` environment variable) and front-truncate its output to the limit when it is exceeded.

`SandboxCommandTimeoutError` is a subclass of `SandboxTimeoutError` and `TimeoutError`. Providers should raise it when they can identify that the command exceeded its execution timeout. Docker distinguishes this from a host-side Docker timeout. Providers that cannot distinguish the cases may continue raising `SandboxTimeoutError` or `TimeoutError`; an unclassified base timeout is not proof of infrastructure failure for those providers.

The `timeout_retry` parameter defaults to `True` and allows provider-specific retries for unreliable sandbox operations. Docker retries host-side timeouts up to twice, with retry timeouts of at most 60 and 30 seconds, but does not retry a known command timeout. Set `timeout_retry=False` when retrying a non-idempotent command could repeat side effects.

Callers that need the distinction should catch the command subtype first:

```python
from inspect_ai.util import SandboxCommandTimeoutError, SandboxTimeoutError, sandbox

try:
    result = await sandbox().exec(["python", "solution.py"], timeout=30)
except SandboxCommandTimeoutError:
    # The scorer can assign its command-timeout outcome here.
    raise
except SandboxTimeoutError:
    # Leave sandbox failures to the evaluation's error/retry policy.
    raise
```

The example re-raises both failures so callers can choose their scoring policy. Existing handlers for `SandboxTimeoutError` or `TimeoutError` continue to catch command timeouts. Partial output, when available, is in `truncated_output`; it is not a reliable way to identify which timeout occurred.
