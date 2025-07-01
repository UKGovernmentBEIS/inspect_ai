# inspect cache


Manage the inspect model output cache.

Learn more about model output caching at
<https://inspect.aisi.org.uk/caching.html>.

#### Usage

``` text
inspect cache [OPTIONS] COMMAND [ARGS]...
```

#### Subcommands

|  |  |
|----|----|
| [clear](#inspect-cache-clear) | Clear all cache files. Requires either –all or –model flags. |
| [path](#inspect-cache-path) | Prints the location of the cache directory. |
| [list](#inspect-cache-list) | Lists all current model caches with their sizes. |
| [prune](#inspect-cache-prune) | Prune all expired cache entries |

## inspect cache clear

Clear all cache files. Requires either –all or –model flags.

#### Usage

``` text
inspect cache clear [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical` \| `notset`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--all` | boolean | Clear all cache files in the cache directory. | `False` |
| `--model` | text | Clear the cache for a specific model (e.g. –model=openai/gpt-4). Can be passed multiple times. | None |
| `--help` | boolean | Show this message and exit. | `False` |

## inspect cache path

Prints the location of the cache directory.

#### Usage

``` text
inspect cache path [OPTIONS]
```

#### Options

| Name     | Type    | Description                 | Default |
|----------|---------|-----------------------------|---------|
| `--help` | boolean | Show this message and exit. | `False` |

## inspect cache list

Lists all current model caches with their sizes.

#### Usage

``` text
inspect cache list [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--pruneable` | boolean | Only list cache entries that can be pruned due to expiry (see inspect cache prune –help). | `False` |
| `--help` | boolean | Show this message and exit. | `False` |

## inspect cache prune

Prune all expired cache entries

Over time the cache directory can grow, but many cache entries will be
expired. This command will remove all expired cache entries for ease of
maintenance.

#### Usage

``` text
inspect cache prune [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--log-level` | choice (`debug` \| `trace` \| `http` \| `info` \| `warning` \| `error` \| `critical` \| `notset`) | Set the log level (defaults to ‘warning’) | `warning` |
| `--model` | text | Only prune a specific model (e.g. –model=openai/gpt-4). Can be passed multiple times. | None |
| `--help` | boolean | Show this message and exit. | `False` |
