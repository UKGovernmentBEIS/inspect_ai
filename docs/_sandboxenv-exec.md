
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
      TimeoutError: If the specified `timeout` expires.
      UnicodeDecodeError: May be raised if the command
        output cannot be decoded as text.
      PermissionError: If the user does not have
        permission to execute the command.
    """
    ...
```

The `exec()` method should enforce an output limit of `SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE` (default 10MB, configurable via the `INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE` environment variable) and front-truncate its output to the limit when it is exceeded.

To deal with potential unreliability of container services, the `exec()` method includes a `timeout_retry` parameter that defaults to `True`. For sandbox implementations this parameter is _advisory_ (they should only use it if potential unreliability exists in their runtime). No more than 2 retries should be attempted and both with timeouts less than 60 seconds. If you are executing commands that are not idempotent (i.e. the side effects of a failed first attempt may affect the results of subsequent attempts) then you can specify `timeout_retry=False` to override this behavior.
