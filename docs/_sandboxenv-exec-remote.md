
### exec_remote()

``` python
async def exec_remote(
    self,
    cmd: list[str],
    options: (
      ExecRemoteStreamingOptions
      | ExecRemoteAwaitableOptions
      | None
  ) = None,
    *,
    stream: bool = True,
) -> ExecRemoteProcess | ExecResult[str]:
    """
    Raises:
      TimeoutError: If `timeout` is specified in
        ExecRemoteAwaitableOptions and the command
        exceeds it (only applicable when `stream=False`).
    """
    ...
```

The `exec_remote()` options (`ExecRemoteStreamingOptions` and `ExecRemoteAwaitableOptions`) include a `user` field that requests the command run as the specified user (equivalent to `docker exec --user`). This requires the sandbox tools server to be running as root inside the container. If the server cannot switch users, a `ToolException` is raised.
