# inspect trace


List and read execution traces.

Inspect includes a TRACE log-level which is right below the HTTP and
INFO log levels (so not written to the console by default). However,
TRACE logs are always recorded to a separate file, and the last 10 TRACE
logs are preserved. The ‘trace’ command provides ways to list and read
these traces.

Learn more about execution traces at
<https://inspect.aisi.org.uk/tracing.html>.

#### Usage

``` text
inspect trace [OPTIONS] COMMAND [ARGS]...
```

#### Subcommands

|  |  |
|----|----|
| [list](#inspect-trace-list) | List all trace files. |
| [dump](#inspect-trace-dump) | Dump a trace file to stdout (as a JSON array of log records). |
| [http](#inspect-trace-http) | View all HTTP requests in the trace log. |
| [anomalies](#inspect-trace-anomalies) | Look for anomalies in a trace file (never completed or cancelled actions). |

## inspect trace list

List all trace files.

#### Usage

``` text
inspect trace list [OPTIONS]
```

#### Options

| Name     | Type    | Description                 | Default |
|----------|---------|-----------------------------|---------|
| `--json` | boolean | Output listing as JSON      | `False` |
| `--help` | boolean | Show this message and exit. | `False` |

## inspect trace dump

Dump a trace file to stdout (as a JSON array of log records).

#### Usage

``` text
inspect trace dump [OPTIONS] [TRACE_FILE]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--filter` | text | Filter (applied to trace message field). | `Sentinel.UNSET` |
| `--help` | boolean | Show this message and exit. | `False` |

## inspect trace http

View all HTTP requests in the trace log.

#### Usage

``` text
inspect trace http [OPTIONS] [TRACE_FILE]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--filter` | text | Filter (applied to trace message field). | `Sentinel.UNSET` |
| `--failed` | boolean | Show only failed HTTP requests (non-200 status) | `False` |
| `--help` | boolean | Show this message and exit. | `False` |

## inspect trace anomalies

Look for anomalies in a trace file (never completed or cancelled
actions).

#### Usage

``` text
inspect trace anomalies [OPTIONS] [TRACE_FILE]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--filter` | text | Filter (applied to trace message field). | `Sentinel.UNSET` |
| `--all` | boolean | Show all anomolies including errors and timeouts (by default only still running and cancelled actions are shown). | `False` |
| `--help` | boolean | Show this message and exit. | `False` |
