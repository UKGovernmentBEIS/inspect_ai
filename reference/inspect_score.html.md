# inspect score


Score a previous evaluation run.

#### Usage

``` text
inspect score [OPTIONS] LOG_FILE
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--scorer` | text | Scorer to use for scoring | None |
| `-S` | text | One or more scorer arguments (e.g. -S arg=value) | None |
| `--action` | choice (`append` \| `overwrite`) | Whether to append or overwrite the existing scores. | None |
| `--overwrite` | boolean | Overwrite log file with the scored version | `False` |
| `--output-file` | file | Output file to write the scored log to. | None |
| `--stream` | text | Stream the samples through the scoring process instead of reading the entire log into memory. Useful for large logs. Set to an integer to limit the number of concurrent samples being scored. | `False` |
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical` \| `notset`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--log-dir` | text | Directory for log files. | `./logs` |
| `--display` | choice (`full` \| `conversation` \| `rich` \| `plain` \| `log` \| `none`) | Set the display type (defaults to ‘full’) | `full` |
| `--traceback-locals` | boolean | Include values of local variables in tracebacks (note that this can leak private data e.g. API keys so should typically only be enabled for targeted debugging). | `False` |
| `--env` | text | Define an environment variable e.g. –env NAME=value (–env can be specified multiple times) | None |
| `--debug` | boolean | Wait to attach debugger | `False` |
| `--debug-port` | integer | Port number for debugger | `5678` |
| `--debug-errors` | boolean | Raise task errors (rather than logging them) so they can be debugged. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |
