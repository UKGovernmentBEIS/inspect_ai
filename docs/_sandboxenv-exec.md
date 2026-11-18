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
      SandboxTimeoutError: If the command or the sandbox operation times
        out. `reason` carries the provider's classification where it has
        one (see below).
      TimeoutError: Legacy provider timeout, wrapped as SandboxTimeoutError
        with `reason=None` when called through sandbox().
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

To deal with potential unreliability of container services, the `exec()` method includes a `timeout_retry` parameter that defaults to `True`. For sandbox implementations, this parameter is _advisory_: providers should retry only when their runtime may be unreliable. Providers should attempt at most two retries, each with a timeout of at most 60 seconds. Docker, for example, may retry when its host-side wait for the daemon times out. When Docker determines that the command itself reached its deadline, it reports the timeout without retrying. If a command is non-idempotent, set `timeout_retry=False` to avoid repeating its side effects.

#### Timeouts

A timeout can mean two different things: the command ran past its deadline, or the provider's request to the sandbox got no answer. `SandboxTimeoutError.reason` carries the provider's classification, with these values (`SandboxTimeoutReason`):

| `reason`        | What the provider is saying                                                                                                                                    |
|-----------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `"command"`     | The command's execution deadline expired. This is the provider's assessment and may rely on heuristics such as exit codes and elapsed time.                   |
| `"no_response"` | The command's deadline is enforced separately, and the provider's own, later wait for a response expired. The command may or may not still be running.         |
| `"unknown"`     | The provider supports the field and cannot classify this timeout, for example because one timer covers both the command and communication with the sandbox.   |
| `None`          | Unset. The provider does not classify timeouts, or raised a plain `TimeoutError` that `sandbox()` wrapped.                                                    |

Providers may raise `SandboxTimeoutError` directly and supply `reason`. A provider with a single timer should report `"command"` only if that timer directly stops the command and nothing else could explain the expiry, and `"unknown"` otherwise. Docker reports `"command"` when its in-container `timeout` ended the command, and `"no_response"` when its host-side wait on the Docker daemon expired. The local sandbox reports `"command"`. Partial output, when available, is in `truncated_output`; it does not indicate which kind of timeout occurred.

A scorer that counts a program overrun as a wrong answer, as code benchmarks do, can use `reason` to keep sandbox failures out of its scores. The `None` branch is where existing behaviour lives: before this field existed, such scorers scored every timeout, and a provider that has not adopted the field still produces that case.

```python
from inspect_ai.util import ExecResult, SandboxTimeoutError, sandbox

try:
    result = await sandbox().exec(["python", "solution.py"], timeout=30)
except SandboxTimeoutError as ex:
    if ex.reason in ("no_response", "unknown"):
        raise  # not known to be the command's fault; let the sample error
    # "command", or None from a provider that does not classify timeouts
    result = ExecResult(False, 1, "", "Timed out.")
```

A stricter scorer can raise unless `ex.reason == "command"`, at the cost of erroring on providers that report `"unknown"` or nothing. Existing handlers for `SandboxTimeoutError` or `TimeoutError` continue to catch every timeout; they only see a difference if they read `reason`.
