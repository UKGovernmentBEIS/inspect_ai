# inspect eval-retry


Retry failed evaluation(s)

#### Usage

``` text
inspect eval-retry [OPTIONS] LOG_FILES...
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--max-samples` | integer | Maximum number of samples to run in parallel (default is running all samples in parallel) | `Sentinel.UNSET` |
| `--max-tasks` | integer | Maximum number of tasks to run in parallel (default is 1 for eval and 4 for eval-set) | `Sentinel.UNSET` |
| `--max-subprocesses` | integer | Maximum number of subprocesses to run in parallel (default is os.cpu_count()) | `Sentinel.UNSET` |
| `--max-sandboxes` | integer | Maximum number of sandboxes (per-provider) to run in parallel. | `Sentinel.UNSET` |
| `--no-sandbox-cleanup` | boolean | Do not cleanup sandbox environments after task completes | `False` |
| `--fail-on-error` | float | Threshold of sample errors to tolerage (by default, evals fail when any error occurs). Value between 0 to 1 to set a proportion; value greater than 1 to set a count. | `Sentinel.UNSET` |
| `--no-fail-on-error` | boolean | Do not fail the eval if errors occur within samples (instead, continue running other samples) | `False` |
| `--continue-on-fail` | boolean | Do not immediately fail the eval if the error threshold is exceeded (instead, continue running other samples until the eval completes, and then possibly fail the eval). | `False` |
| `--retry-on-error` | text | Retry samples if they encounter errors (by default, no retries occur). Specify –retry-on-error to retry a single time, or specify e.g. `--retry-on-error=3` to retry multiple times. | None |
| `--no-log-samples` | boolean | Do not include samples in the log file. | `False` |
| `--no-log-realtime` | boolean | Do not log events in realtime (affects live viewing of samples in inspect view) | `False` |
| `--log-images` / `--no-log-images` | boolean | Include base64 encoded versions of filename or URL based images in the log file. | `True` |
| `--log-buffer` | integer | Number of samples to buffer before writing log file. If not specified, an appropriate default for the format and filesystem is chosen (10 for most all cases, 100 for JSON logs on remote filesystems). | `Sentinel.UNSET` |
| `--log-shared` | text | Sync sample events to log directory so that users on other systems can see log updates in realtime (defaults to no syncing). If enabled will sync every 10 seconds (or pass a value to sync every `n` seconds). | None |
| `--no-score` | boolean | Do not score model output (use the inspect score command to score output later) | `False` |
| `--no-score-display` | boolean | Do not score model output (use the inspect score command to score output later) | `False` |
| `--max-connections` | integer | Maximum number of concurrent connections to Model API (defaults to 10) | `Sentinel.UNSET` |
| `--max-retries` | integer | Maximum number of times to retry model API requests (defaults to unlimited) | `Sentinel.UNSET` |
| `--timeout` | integer | Model API request timeout in seconds (defaults to no timeout) | `Sentinel.UNSET` |
| `--attempt-timeout` | integer | Timeout (in seconds) for any given attempt (if exceeded, will abandon attempt and retry according to max_retries). | `Sentinel.UNSET` |
| `--log-level-transcript` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical` \| `notset`) | Set the log level of the transcript (defaults to ‘info’) | `info` |
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical` \| `notset`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--log-dir` | text | Directory for log files. | `./logs` |
| `--display` | choice (`full` \| `conversation` \| `rich` \| `plain` \| `log` \| `none`) | Set the display type (defaults to ‘full’) | `full` |
| `--traceback-locals` | boolean | Include values of local variables in tracebacks (note that this can leak private data e.g. API keys so should typically only be enabled for targeted debugging). | `False` |
| `--env` | text | Define an environment variable e.g. –env NAME=value (–env can be specified multiple times) | `Sentinel.UNSET` |
| `--debug` | boolean | Wait to attach debugger | `False` |
| `--debug-port` | integer | Port number for debugger | `5678` |
| `--debug-errors` | boolean | Raise task errors (rather than logging them) so they can be debugged. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |
