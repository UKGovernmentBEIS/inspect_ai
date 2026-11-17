# inspect_log – Inspect

Query, read, and convert logs.

Inspect supports two log formats: ‘eval’ which is a compact, high performance binary format and ‘json’ which represents logs as JSON.

The default format is ‘eval’. You can change this by setting the INSPECT_LOG_FORMAT environment variable or using the –log-format command line option.

The ‘log’ commands enable you to read Inspect logs uniformly as JSON no matter their physical storage format, and also enable you to read only the headers (everything but the samples) from log files, which is useful for very large logs.

Learn more about managing log files at <https://inspect.aisi.org.uk/eval-logs.html>.

#### Usage

``` text
inspect log [OPTIONS] COMMAND [ARGS]...
```

#### Subcommands

|  |  |
|----|----|
| [list](#inspect-log-list) | List all logs in the log directory. |
| [dump](#inspect-log-dump) | Print log file contents as JSON. |
| [convert](#inspect-log-convert) | Convert between log file formats. |
| [schema](#inspect-log-schema) | Print JSON schema for log files. |
| [export-config](#inspect-log-export-config) | Export the run configuration from a log file. |
| [recover](#inspect-log-recover) | Recover crashed eval logs from sample buffer databases. |
| [exclude](#inspect-log-exclude) | Exclude samples of a finished log from its metrics. |
| [zero](#inspect-log-zero) | Score samples of a finished log as empty attempts. |
| [merge-shards](#inspect-log-merge-shards) | Merge the shard logs of a sharded run into its merged log. |

## inspect log list

List all logs in the log directory.

#### Usage

``` text
inspect log list [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--status` | choice (`started` \| `success` \| `cancelled` \| `error`) | List only log files with the indicated status. | `Sentinel.UNSET` |
| `--absolute` | boolean | List absolute paths to log files (defaults to relative to the cwd). | `False` |
| `--json` | boolean | Output listing as JSON | `False` |
| `--no-recursive` | boolean | List log files recursively (defaults to True). | `False` |
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical` \| `notset`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--log-dir` | text | Directory for log files. | `./logs` |
| `--display` | choice (`full` \| `conversation` \| `rich` \| `plain` \| `log` \| `none`) | Set the display type (defaults to ‘full’) | `full` |
| `--traceback-locals` | boolean | Include values of local variables in tracebacks (note that this can leak private data e.g. API keys so should typically only be enabled for targeted debugging). | `False` |
| `--env` | text | Define an environment variable e.g. –env NAME=value (–env can be specified multiple times) | `Sentinel.UNSET` |
| `--debug` | boolean | Wait to attach debugger | `False` |
| `--debug-port` | integer | Port number for debugger | `5678` |
| `--debug-errors` | boolean | Raise task errors (rather than logging them) so they can be debugged. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |

## inspect log dump

Print log file contents as JSON.

#### Usage

``` text
inspect log dump [OPTIONS] PATH
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--header-only` | boolean | Read and print only the header of the log file (i.e. no samples). | `False` |
| `--resolve-attachments` | choice (`full` \| `core`) | Resolve attachments (duplicated content blocks) to their full content. | None |
| `--help` | boolean | Show this message and exit. | `False` |

## inspect log convert

Convert between log file formats.

#### Usage

``` text
inspect log convert [OPTIONS] PATH
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--to` | choice (`eval` \| `json`) | Target format to convert to. | `Sentinel.UNSET` |
| `--output-dir` | text | Directory to write converted log files to. | `Sentinel.UNSET` |
| `--overwrite` | boolean | Overwrite files in the output directory. | `False` |
| `--resolve-attachments` | choice (`full` \| `core`) | Resolve attachments (duplicated content blocks) to their full content. | None |
| `--stream` | text | Stream the samples through the conversion process instead of reading the entire log into memory. Useful for large logs. Set to an integer to limit the number of concurrent samples being converted. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |

## inspect log schema

Print JSON schema for log files.

#### Usage

``` text
inspect log schema [OPTIONS]
```

#### Options

| Name     | Type    | Description                 | Default |
|----------|---------|-----------------------------|---------|
| `--help` | boolean | Show this message and exit. | `False` |

## inspect log export-config

Export the run configuration from a log file.

Reads LOG_FILE and writes a YAML (or JSON) file that can be passed directly to ‘inspect eval –run-config’ to reproduce the run.

Example: inspect log export-config logs/my_run.eval \> run.yaml

    inspect eval --run-config run.yaml

#### Usage

``` text
inspect log export-config [OPTIONS] LOG_FILE
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--output` | text | Write output to this file instead of stdout. | None |
| `--format` | choice (`yaml` \| `json`) | Output format. | `yaml` |
| `--help` | boolean | Show this message and exit. | `False` |

## inspect log recover

Recover crashed eval logs from sample buffer databases.

#### Usage

``` text
inspect log recover [OPTIONS] [LOG_FILE]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--output` | text | Output path for the recovered log file. | None |
| `--overwrite` | boolean | Overwrite the crashed log file in-place instead of creating a new file. | `False` |
| `--no-cleanup` | boolean | Don’t remove the sample buffer database after recovery. | `False` |
| `--no-events` | boolean | Exclude event transcript from recovered samples (reduces output size). | `False` |
| `--incomplete-action` | choice (`retry` \| `error`) | Disposition for samples that were in progress at crash: ‘retry’ (default) marks them as cancelled errors that a later eval-retry re-runs; ‘error’ resolves them as operator terminations, finalizing the recovered log with status ‘success’ when every expected sample is final (nothing will retry it). | `retry` |
| `--incomplete-max` | float range (`0` and above) | Safety threshold for –incomplete-action error (count if \>= 1, or proportion of expected samples if strictly less than 1): refuse to recover when more than this many samples are in progress. Has no effect (a warning is logged) with –incomplete-action retry. | None |
| `--trust-log` | boolean | Import the log’s task file to load metrics that are not registered, and rebuild metric options that hold models or other objects. This runs the task file’s code, so use it only for logs you trust. | `False` |
| `--list` | boolean | List recoverable logs instead of recovering. | `False` |
| `--json` | boolean | Output listing as JSON (only with –list). | `False` |
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical` \| `notset`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--log-dir` | text | Directory for log files. | `./logs` |
| `--display` | choice (`full` \| `conversation` \| `rich` \| `plain` \| `log` \| `none`) | Set the display type (defaults to ‘full’) | `full` |
| `--traceback-locals` | boolean | Include values of local variables in tracebacks (note that this can leak private data e.g. API keys so should typically only be enabled for targeted debugging). | `False` |
| `--env` | text | Define an environment variable e.g. –env NAME=value (–env can be specified multiple times) | `Sentinel.UNSET` |
| `--debug` | boolean | Wait to attach debugger | `False` |
| `--debug-port` | integer | Port number for debugger | `5678` |
| `--debug-errors` | boolean | Raise task errors (rather than logging them) so they can be debugged. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |

## inspect log exclude

Exclude samples of a finished log from its metrics.

Each score of the sample becomes an unscored NaN with the reason ‘excluded’, recording the author and reason; the earlier score stays in its history. A sample with no score gets one under the log’s first scorer. Metrics are recomputed and LOG_FILE is rewritten in place.

The sample’s transcript and error are not changed, so eval-retry still re-runs an errored sample, which replaces the exclusion.

Metrics and epoch reducers must be registered in Inspect or an installed package; the log’s task file is not imported.

#### Usage

``` text
inspect log exclude [OPTIONS] LOG_FILE
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--sample` | text | Id of a sample to exclude (every epoch, unless –epoch is given). Repeat for more samples. | `Sentinel.UNSET` |
| `--epoch` | integer range (`1` and above) | Exclude only this epoch of each named sample. | None |
| `--reason` | text | Why the samples are excluded. | `Sentinel.UNSET` |
| `--author` | text | Author of the exclusion (default: the git identity, else the user name). | None |
| `--json` | boolean | Print the result as JSON. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |

## inspect log zero

Score samples of a finished log as empty attempts.

First run the samples again with ‘inspect eval TASK –solver inspect_ai/empty_attempt –sample-id ID’, a solver that does nothing, and write that log to a log directory of its own. Then pass it with –from. Each score of its sample is copied into the sample of LOG_FILE with the reason ‘zeroed’, recording the author and reason; the earlier score stays in its history. Metrics are recomputed and LOG_FILE is rewritten in place.

Only samples with string ids, and verdicts that count in metrics (a single value that is not NaN), can be zeroed. Exclude other samples instead.

The sample’s transcript and error are not changed, so eval-retry still re-runs an errored sample, which replaces the zero.

Metrics and epoch reducers must be registered in Inspect or an installed package; the log’s task file is not imported.

#### Usage

``` text
inspect log zero [OPTIONS] LOG_FILE
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--from` | text | Log of an eval of the same task run with the solver inspect_ai/empty_attempt. | `Sentinel.UNSET` |
| `--sample` | text | Id of a sample to zero (every epoch, unless –epoch is given). Repeat for more samples. | `Sentinel.UNSET` |
| `--epoch` | integer range (`1` and above) | Zero only this epoch of each named sample. | None |
| `--reason` | text | Why the samples are zeroed. | `Sentinel.UNSET` |
| `--author` | text | Author of the zero (default: the git identity, else the user name). | None |
| `--json` | boolean | Print the result as JSON. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |

## inspect log merge-shards

Merge the shard logs of a sharded run into its merged log.

LOG is the merged log (`<name>.eval`) or its shards directory (`<name>.shards`). Pass the task options the workers were given (`-T`, `--model`, `--model-role`, `--epochs`, …); they mean what they mean to `inspect eval`. Exits 1 on any failure.

Learn more at <https://inspect.aisi.org.uk/sharding.html>.

#### Usage

``` text
inspect log merge-shards [OPTIONS] LOG
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--task` | text | The task the shards ran, as for `inspect eval` (file.py, <file.py@name>, a registered name or a directory). | `Sentinel.UNSET` |
| `-T` | text | One or more task arguments (e.g. -T arg=value) | `Sentinel.UNSET` |
| `--task-config` | text | YAML or JSON config file with task arguments. | `Sentinel.UNSET` |
| `--model` | text | Model used to evaluate tasks. | `Sentinel.UNSET` |
| `--model-base-url` | text | Base URL for for model API | `Sentinel.UNSET` |
| `-M` | text | One or more native model arguments (e.g. -M arg=value) | `Sentinel.UNSET` |
| `--model-config` | text | YAML or JSON config file with model arguments. | `Sentinel.UNSET` |
| `--model-role` | text | Named model role with model name or YAML/JSON config, e.g. –model-role critic=openai/gpt-6-luna or –model-role grader=“{model: mockllm/model, temperature: 0.5}”. Bind multiple models to a role with a comma-separated list of names or a YAML/JSON list of configs, e.g. –model-role grader=openai/gpt-6-luna,google/gemini-2.0-flash | `Sentinel.UNSET` |
| `--epochs` | integer | Number of times to repeat dataset (defaults to 1) | `Sentinel.UNSET` |
| `--epochs-reducer` | text | Method for reducing per-epoch sample scores into a single score. Built in reducers include ‘mean’, ‘median’, ‘mode’, ‘max’, and ‘at_least\_{n}’. | `Sentinel.UNSET` |
| `--no-epochs-reducer` | boolean | Do not reduce per-epoch sample scores. | `False` |
| `--sample-id` | text | Intended selection as exact sample ids, comma separated. Not patterns; no ‘task:’ prefix. | `Sentinel.UNSET` |
| `--sample-count` | integer | Intended selection as a number of samples (exclusive with –sample-id). | `Sentinel.UNSET` |
| `--allow-incomplete` | boolean | Write a ‘started’ or ‘error’ merged log when the shard set is incomplete. | `False` |
| `--json` | boolean | Print one JSON object on stdout: the merged log’s location, status and whether it was written, or an error envelope. | `False` |
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical` \| `notset`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--log-dir` | text | Directory for log files. | `./logs` |
| `--display` | choice (`full` \| `conversation` \| `rich` \| `plain` \| `log` \| `none`) | Set the display type (defaults to ‘full’) | `full` |
| `--traceback-locals` | boolean | Include values of local variables in tracebacks (note that this can leak private data e.g. API keys so should typically only be enabled for targeted debugging). | `False` |
| `--env` | text | Define an environment variable e.g. –env NAME=value (–env can be specified multiple times) | `Sentinel.UNSET` |
| `--debug` | boolean | Wait to attach debugger | `False` |
| `--debug-port` | integer | Port number for debugger | `5678` |
| `--debug-errors` | boolean | Raise task errors (rather than logging them) so they can be debugged. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |
