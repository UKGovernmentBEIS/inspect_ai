# inspect_eval-retry – Inspect

Retry failed evaluation(s)

#### Usage

``` text
inspect eval-retry [OPTIONS] LOG_FILES...
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--max-samples` | integer | Maximum number of samples to run in parallel (default is running all samples in parallel) | None |
| `--max-tasks` | integer | Maximum number of tasks to run in parallel (default is 1 for eval and 10 for eval-set) | None |
| `--max-subprocesses` | integer | Maximum number of subprocesses to run in parallel (default is os.cpu_count()) | None |
| `--max-sandboxes` | integer | Maximum number of sandboxes (per-provider) to run in parallel. | None |
| `--no-sandbox-cleanup` | boolean | Do not cleanup sandbox environments after task completes | `False` |
| `--fail-on-error` | float | Threshold of sample errors to tolerage (by default, evals fail when any error occurs). Value between 0 to 1 to set a proportion; value greater than 1 to set a count. | None |
| `--no-fail-on-error` | boolean | Do not fail the eval if errors occur within samples (instead, continue running other samples) | `False` |
| `--continue-on-fail` | boolean | Do not immediately fail the eval if the error threshold is exceeded (instead, continue running other samples until the eval completes, and then possibly fail the eval). | `False` |
| `--retry-on-error` | text | Retry samples if they encounter errors (by default, no retries occur). Specify –retry-on-error to retry a single time, or specify e.g. `--retry-on-error=3` to retry multiple times. | None |
| `--score-on-error` | boolean | Score samples that error rather than failing the eval mid-run. Errors still count toward the –fail-on-error threshold for marking the log as ‘error’. Only fires after retries (if any) are exhausted. | `False` |
| `--no-log-samples` | boolean | Do not include samples in the log file. | `False` |
| `--no-log-realtime` | boolean | Do not log events in realtime (affects live viewing of samples in inspect view) | `False` |
| `--log-images` / `--no-log-images` | boolean | Include base64 encoded versions of filename or URL based images in the log file. | `True` |
| `--log-model-api` / `--no-log-model-api` | boolean | Log raw model api requests and responses. Note that error requests/responses are always logged. | None |
| `--log-refusals` / `--no-log-refusals` | boolean | Log warnings for model refusals. | `False` |
| `--log-buffer` | integer | Number of samples to buffer before writing log file. If not specified, an appropriate default for the format and filesystem is chosen (10 for most all cases, 100 for JSON logs on remote filesystems). | None |
| `--log-shared` | text | Sync sample events to log directory so that users on other systems can see log updates in realtime (defaults to no syncing). If enabled will sync every 10 seconds (or pass a value to sync every `n` seconds). | None |
| `--no-score` | boolean | Do not score model output (use the inspect score command to score output later) | `False` |
| `--no-score-display` | boolean | Do not display scoring metrics in realtime. | `False` |
| `--acp-server` | text | Override the original eval’s Agent Client Protocol server. Bare flag enables a default AF_UNIX socket; pass an integer to bind a TCP loopback port; pass `host:port` to bind on a specific interface (e.g. `0.0.0.0:4444`); pass a filesystem path for a custom UNIX socket; pass `false` to disable. Omit to replay whatever transport the original log used. | None |
| `--max-connections` | integer | Maximum number of concurrent connections to Model API (defaults to 10) | None |
| `--adaptive-connections` | text | Adaptive concurrency for Model API connections, automatically scaling between bounds based on rate-limit feedback (default: enabled, with min=4, start=20, max=100). Pass `false` to opt out, an integer N for a custom max (e.g. `200`), or bounds as `min-max` (e.g. `4-80`) or `min-start-max` (e.g. `4-20-80`). Explicit `--max-connections` and `--batch` take precedence. | None |
| `--max-retries` | integer | Maximum number of times to retry model API requests (defaults to unlimited) | None |
| `--timeout` | integer | Model API request timeout in seconds (defaults to no timeout) | None |
| `--attempt-timeout` | integer | Timeout (in seconds) for any given attempt (if exceeded, will abandon attempt and retry according to max_retries). | None |
| `--log-level-transcript` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical` \| `notset`) | Set the log level of the transcript (defaults to ‘info’) | `info` |
| `--scanner` | text | Scanner(s) to apply after each sample. Pass a YAML/JSON config file (ScannerConfig schema), a Python file with @scanner functions (use <file.py@func> to pick one), or a registry reference (pkg/name). | None |
| `--scanner-arg` | text | One or more scanner arguments (e.g. –scanner-arg key=value). | None |
| `--scans` | text | Location to write scan results to (defaults to /scans/). | None |
| `--scan-name` | text | Scan name written to \_scan.json (defaults to “eval_set”). | None |
| `--scan-tags` | text | Comma-separated tags written to the scan spec. | None |
| `--scan-metadata` | text | Metadata written to the scan spec (e.g. –scan-metadata key=value). | None |
| `-F`, `--scan-filter` | text | SQL WHERE clause(s) applied per-sample to skip transcripts that don’t match (e.g. -F “error = ’’”). | None |
| `--scan-model` | text | Model used by scanners’ get_model() (overrides the eval model). | None |
| `--scan-model-base-url` | text | Base URL for the scanner-side model API. | None |
| `--scan-model-arg` | text | One or more scanner-side model arguments (e.g. –scan-model-arg key=value). | None |
| `--scan-model-config` | text | YAML or JSON config file with scanner-side model arguments. | None |
| `--scan-model-role` | text | Named scanner-side model role with model name or YAML/JSON config (e.g. –scan-model-role grader=mockllm/model). | None |
| `--scan-generate-config` | text | YAML or JSON config file with GenerateConfig for scanner model calls. | None |
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical` \| `notset`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--log-dir` | text | Directory for log files. | `./logs` |
| `--display` | choice (`full` \| `conversation` \| `rich` \| `plain` \| `log` \| `none`) | Set the display type (defaults to ‘full’) | `full` |
| `--traceback-locals` | boolean | Include values of local variables in tracebacks (note that this can leak private data e.g. API keys so should typically only be enabled for targeted debugging). | `False` |
| `--env` | text | Define an environment variable e.g. –env NAME=value (–env can be specified multiple times) | None |
| `--debug` | boolean | Wait to attach debugger | `False` |
| `--debug-port` | integer | Port number for debugger | `5678` |
| `--debug-errors` | boolean | Raise task errors (rather than logging them) so they can be debugged. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |
