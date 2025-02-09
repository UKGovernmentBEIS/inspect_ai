# inspect sandbox


Manage Sandbox Environments.

#### Usage

``` text
inspect sandbox [OPTIONS] COMMAND [ARGS]...
```

#### Subcommands

|                                     |                               |
|-------------------------------------|-------------------------------|
| [cleanup](#inspect-sandbox-cleanup) | Cleanup Sandbox Environments. |

## inspect sandbox cleanup

Cleanup Sandbox Environments.

TYPE specifies the sandbox environment type (e.g. ‘docker’)

Pass an ENVIRONMENT_ID to cleanup only a single environment (otherwise
all environments will be cleaned up).

#### Usage

``` text
inspect sandbox cleanup [OPTIONS] TYPE [ENVIRONMENT_ID]
```

#### Options

| Name     | Type    | Description                 | Default |
|----------|---------|-----------------------------|---------|
| `--help` | boolean | Show this message and exit. | `False` |
