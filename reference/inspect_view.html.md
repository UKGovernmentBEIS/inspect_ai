# inspect view


Inspect log viewer.

Learn more about using the log viewer at
<https://inspect.aisi.org.uk/log-viewer.html>.

#### Usage

``` text
inspect view [OPTIONS] COMMAND [ARGS]...
```

#### Subcommands

|                                |                        |
|--------------------------------|------------------------|
| [start](#inspect-view-start)   | View evaluation logs.  |
| [bundle](#inspect-view-bundle) | Bundle evaluation logs |

## inspect view start

View evaluation logs.

#### Usage

``` text
inspect view start [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--recursive` | boolean | Include all logs in log_dir recursively. | `True` |
| `--host` | text | Tcp/Ip host | `127.0.0.1` |
| `--port` | integer | TCP/IP port | `7575` |
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--log-dir` | text | Directory for log files. | `./logs` |
| `--display` | choice (`full` \| `conversation` \| `rich` \| `plain` \| `log` \| `none`) | Set the display type (defaults to ‘full’) | `full` |
| `--traceback-locals` | boolean | Include values of local variables in tracebacks (note that this can leak private data e.g. API keys so should typically only be enabled for targeted debugging). | `False` |
| `--env` | text | Define an environment variable e.g. –env NAME=value (–env can be specified multiple times) | None |
| `--debug` | boolean | Wait to attach debugger | `False` |
| `--debug-port` | integer | Port number for debugger | `5678` |
| `--debug-errors` | boolean | Raise task errors (rather than logging them) so they can be debugged. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |

## inspect view bundle

Bundle evaluation logs

#### Usage

``` text
inspect view bundle [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--log-dir` | text | Directory for log files. | `./logs` |
| `--display` | choice (`full` \| `conversation` \| `rich` \| `plain` \| `log` \| `none`) | Set the display type (defaults to ‘full’) | `full` |
| `--traceback-locals` | boolean | Include values of local variables in tracebacks (note that this can leak private data e.g. API keys so should typically only be enabled for targeted debugging). | `False` |
| `--env` | text | Define an environment variable e.g. –env NAME=value (–env can be specified multiple times) | None |
| `--debug` | boolean | Wait to attach debugger | `False` |
| `--debug-port` | integer | Port number for debugger | `5678` |
| `--debug-errors` | boolean | Raise task errors (rather than logging them) so they can be debugged. | `False` |
| `--output-dir` | text | The directory where bundled output will be placed. | \_required |
| `--overwrite` | boolean | Overwrite files in the output directory. | `False` |
| `--help` | boolean | Show this message and exit. | `False` |
