
### write_file()

``` python
async def write_file(
    self, file: str, contents: str | bytes
) -> None:
    """
    Raises:
      TimeoutError: If the operation times out.
      PermissionError: If the user does not have
        permission to write to the specified path.
      IsADirectoryError: If the file exists already and
        is a directory.
    """
    ...
```

Note that `write_file()` automatically creates parent directories as required if they don't exist.

### read_file()

``` python
async def read_file(
    self, file: str, text: bool = True
) -> Union[str | bytes]:
    """
    Raises:
      TimeoutError: If the operation times out.
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
```

The `read_file()` method should enforce the `SandboxEnvironmentLimits.MAX_READ_FILE_SIZE` limit (default 100MB, configurable via the `INSPECT_SANDBOX_MAX_READ_FILE_SIZE` environment variable) and raise an `OutputLimitExceededError` when it is exceeded.

The `read_file()` method should preserve newline constructs (e.g. crlf should be preserved not converted to lf). This is equivalent to specifying `newline=""` in a call to the Python `open()` function.

### connection()

``` python
async def connection(self, *, user: str | None = None) -> SandboxConnection:
    """
    Raises:
       NotImplementedError: For sandboxes that don't provide connections
       ConnectionError: If sandbox is not currently running.
    """
    ...
```

The `connection()` method is optional, and provides commands that can be used to login to the sandbox container from a terminal or IDE.

### Expected and Unexpected Errors

For each method there is a documented set of errors that are raised: these are _expected_ errors and can either be caught by tools or allowed to propagate in which case they will be reported to the model for potential recovery. In addition, _unexpected_ errors may occur (e.g. a networking error connecting to a remote container): these errors are not reported to the model and fail the `Sample` with an error state.
