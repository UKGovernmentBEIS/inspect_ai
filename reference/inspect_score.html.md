# inspect score


Score a previous evaluation run.

#### Usage

``` text
inspect score [OPTIONS] TASK LOG_FILE
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--no-overwrite` | boolean | Do not overwrite unscored log_files with the scored version (instead write a new file w/ ‘-scored’ appended) | `False` |
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--log-dir` | text | Directory for log files. | `./logs` |
| `--display` | choice (`full` \| `conversation` \| `rich` \| `plain` \| `none`) | Set the display type (defaults to ‘full’) | `full` |
| `--debug` | boolean | Wait to attach debugger | `False` |
| `--debug-port` | integer | Port number for debugger | `5678` |
| `--debug-errors` | boolean | Raise task errors (rather than logging them) so they can be debugged. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |
