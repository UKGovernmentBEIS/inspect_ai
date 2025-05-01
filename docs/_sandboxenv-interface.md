
``` python
class SandboxEnvironment:
   
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] = {},
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True
    ) -> ExecResult[str]:
        """
        Raises:
          TimeoutError: If the specified `timeout` expires.
          UnicodeDecodeError: If an error occurs while
            decoding the command output.
          PermissionError: If the user does not have
            permission to execute the command.
          OutputLimitExceededError: If an output stream
            exceeds the 10 MiB limit.
        """
        ...

    async def write_file(
        self, file: str, contents: str | bytes
    ) -> None:
        """
        Raises:
          PermissionError: If the user does not have
            permission to write to the specified path.
          IsADirectoryError: If the file exists already and 
            is a directory.
        """
        ...

    async def read_file(
        self, file: str, text: bool = True
    ) -> Union[str | bytes]:
        """
        Raises:
          FileNotFoundError: If the file does not exist.
          UnicodeDecodeError: If an encoding error occurs 
            while reading the file.
            (only applicable when `text = True`)
          PermissionError: If the user does not have
            permission to read from the specified path.
          IsADirectoryError: If the file is a directory.
          OutputLimitExceededError: If the file size
            exceeds the 100 MiB limit.
        """
        ...

    async def connection(self, *, user: str | None = None) -> SandboxConnection:
        """
        Raises:
           NotImplementedError: For sandboxes that don't provide connections
           ConnectionError: If sandbox is not currently running.
        """
```

The `read_file()` method should preserve newline constructs (e.g. crlf should be preserved not converted to lf). This is equivalent to specifying `newline=""` in a call to the Python `open()` function. Note that `write_file()` automatically creates parent directories as required if they don't exist.

The `connection()` method is optional, and provides commands that can be used to login to the sandbox container from a terminal or IDE.

Note that to deal with potential unreliability of container services, the `exec()` method includes a `timeout_retry` parameter that defaults to `True`. For sandbox implementations this parameter is _advisory_ (they should only use it if potential unreliability exists in their runtime). No more than 2 retries should be attempted and both with timeouts less than 60 seconds. If you are executing commands that are not idempotent (i.e. the side effects of a failed first attempt may affect the results of subsequent attempts) then you can specify `timeout_retry=False` to override this behavior.

For each method there is a documented set of errors that are raised: these are _expected_ errors and can either be caught by tools or allowed to propagate in which case they will be reported to the model for potential recovery. In addition, _unexpected_ errors may occur (e.g. a networking error connecting to a remote container): these errors are not reported to the model and fail the `Sample` with an error state. 