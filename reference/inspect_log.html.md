# inspect log


Query, read, and convert logs.

Inspect supports two log formats: ‘eval’ which is a compact, high
performance binary format and ‘json’ which represents logs as JSON.

The default format is ‘eval’. You can change this by setting the
INSPECT_LOG_FORMAT environment variable or using the –log-format command
line option.

The ‘log’ commands enable you to read Inspect logs uniformly as JSON no
matter their physical storage format, and also enable you to read only
the headers (everything but the samples) from log files, which is useful
for very large logs.

Learn more about managing log files at
<https://inspect.aisi.org.uk/eval-logs.html>.

#### Usage

``` text
inspect log [OPTIONS] COMMAND [ARGS]...
```

#### Subcommands

|                                 |                                     |
|---------------------------------|-------------------------------------|
| [list](#inspect-log-list)       | List all logs in the log directory. |
| [dump](#inspect-log-dump)       | Print log file contents as JSON.    |
| [convert](#inspect-log-convert) | Convert between log file formats.   |
| [schema](#inspect-log-schema)   | Print JSON schema for log files.    |

## inspect log list

List all logs in the log directory.

#### Usage

``` text
inspect log list [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--status` | choice (`started` \| `success` \| `cancelled` \| `error`) | List only log files with the indicated status. | None |
| `--absolute` | boolean | List absolute paths to log files (defaults to relative to the cwd). | `False` |
| `--json` | boolean | Output listing as JSON | `False` |
| `--no-recursive` | boolean | List log files recursively (defaults to True). | `False` |
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--log-dir` | text | Directory for log files. | `./logs` |
| `--display` | choice (`full` \| `conversation` \| `rich` \| `plain` \| `log` \| `none`) | Set the display type (defaults to ‘full’) | `full` |
| `--traceback-locals` | boolean | Include values of local variables in tracebacks (note that this can leak private data e.g. API keys so should typically only be enabled for targeted debugging). | `False` |
| `--env` | text | Define an environment variable e.g. –env NAME=value (–env can be specified multiple times) | None |
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
| `--to` | choice (`eval` \| `json`) | Target format to convert to. | \_required |
| `--output-dir` | text | Directory to write converted log files to. | \_required |
| `--overwrite` | boolean | Overwrite files in the output directory. | `False` |
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
