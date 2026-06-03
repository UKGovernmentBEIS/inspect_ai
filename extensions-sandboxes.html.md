# Sandboxes – Inspect

[Sandbox Environments](./sandboxing.html.md) provide a mechanism for sandboxing execution of tool code as well as providing more sophisticated infrastructure (e.g. creating network hosts for a cybersecurity eval). Inspect comes with two sandbox environments built in:

| Environment Type | Description |
|----|----|
| `local` | Run [sandbox()](./reference/inspect_ai.util.html.md#sandbox) methods in the same file system as the running evaluation (should *only be used* if you are already running your evaluation in another sandbox). |
| `docker` | Run [sandbox()](./reference/inspect_ai.util.html.md#sandbox) methods within a Docker container |

To create a custom sandbox environment, derive a class from [SandboxEnvironment](./reference/inspect_ai.util.html.md#sandboxenvironment), implement the required instance and static methods, and add the `@sandboxenv` decorator to it. The [Instance Methods](#sec-instance-methods) handle process execution and file I/O within the environment, while the [Lifecycle Methods](#sec-lifecycle-methods) manage the creation and cleanup of the underlying compute resources.

## Examples

The best way to learn about writing sandbox environments is to study existing implementations. The two built-in environments are a good starting point:

- [LocalSandboxEnvironment](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/src/inspect_ai/util/_sandbox/local.py) — runs in the same file system as the running evaluation.
- [DockerSandboxEnvironment](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/src/inspect_ai/util/_sandbox/docker/docker.py) — runs each sample within a Docker container.

Several third-party sandboxes are published as standalone packages, and are good references for implementing more sophisticated cloud and cluster runtimes:

- [inspect_sandboxes](https://github.com/meridianlabs-ai/inspect_sandboxes) — [Daytona](https://meridianlabs-ai.github.io/inspect_sandboxes/daytona.html) and [Modal](https://meridianlabs-ai.github.io/inspect_sandboxes/modal.html) cloud sandboxes.
- [inspect-k8s-sandbox](https://github.com/UKGovernmentBEIS/inspect_k8s_sandbox) — Kubernetes cluster sandbox.

See the [Inspect Extensions](./extensions/index.html.md) listing for the full set of available sandbox providers.

## Instance Methods

A custom [SandboxEnvironment](./reference/inspect_ai.util.html.md#sandboxenvironment) implements the instance methods below, which provide access to process execution and file input/output within the environment. These form the core contract that tools rely on, so it is important to implement them with the documented exception behaviour.

### exec()

``` python
async def exec(
    self,
    cmd: list[str],
    input: str | bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] = {},
    user: str | None = None,
    timeout: int | None = None,
    timeout_retry: bool = True,
    concurrency: bool = True
) -> ExecResult[str]:
    """
    Raises:
      TimeoutError: If the specified `timeout` expires.
      UnicodeDecodeError: If an error occurs while
        decoding the command output.
      PermissionError: If the user does not have
        permission to execute the command.
    """
    ...
```

The `exec()` method should enforce an output limit of `SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE` (default 10MB, configurable via the `INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE` environment variable) and front-truncate its output to the limit when it is exceeded.

To deal with potential unreliability of container services, the `exec()` method includes a `timeout_retry` parameter that defaults to `True`. For sandbox implementations this parameter is *advisory* (they should only use it if potential unreliability exists in their runtime). No more than 2 retries should be attempted and both with timeouts less than 60 seconds. If you are executing commands that are not idempotent (i.e. the side effects of a failed first attempt may affect the results of subsequent attempts) then you can specify `timeout_retry=False` to override this behavior.

### write_file()

``` python
async def write_file(
    self, file: str, contents: str | bytes
) -> None:
    """
    Raises:
      TimeoutError: If the operation times out.
      PermissionError: If the user does not have
        permission to write to the specified path.
      IsADirectoryError: If the file exists already and
        is a directory.
    """
    ...
```

Note that `write_file()` automatically creates parent directories as required if they don’t exist.

### read_file()

``` python
async def read_file(
    self, file: str, text: bool = True
) -> Union[str | bytes]:
    """
    Raises:
      TimeoutError: If the operation times out.
      FileNotFoundError: If the file does not exist.
      UnicodeDecodeError: If an encoding error occurs
        while reading the file.
        (only applicable when `text = True`)
      PermissionError: If the user does not have
        permission to read from the specified path.
      IsADirectoryError: If the file is a directory.
      OutputLimitExceededError: If the file size
        exceeds the 100 MiB limit.
    """
    ...
```

The [read_file()](./reference/inspect_ai.tool.html.md#read_file) method should enforce the `SandboxEnvironmentLimits.MAX_READ_FILE_SIZE` limit (default 100MB, configurable via the `INSPECT_SANDBOX_MAX_READ_FILE_SIZE` environment variable) and raise an `OutputLimitExceededError` when it is exceeded.

The [read_file()](./reference/inspect_ai.tool.html.md#read_file) method should preserve newline constructs (e.g. crlf should be preserved not converted to lf). This is equivalent to specifying `newline=""` in a call to the Python `open()` function.

### connection()

``` python
async def connection(self, *, user: str | None = None) -> SandboxConnection:
    """
    Raises:
       NotImplementedError: For sandboxes that don't provide connections
       ConnectionError: If sandbox is not currently running.
    """
    ...
```

The `connection()` method is optional, and provides commands that can be used to login to the sandbox container from a terminal or IDE.

### Expected and Unexpected Errors

For each method there is a documented set of errors that are raised: these are *expected* errors and can either be caught by tools or allowed to propagate in which case they will be reported to the model for potential recovery. In addition, *unexpected* errors may occur (e.g. a networking error connecting to a remote container): these errors are not reported to the model and fail the [Sample](./reference/inspect_ai.dataset.html.md#sample) with an error state.

## Lifecycle Methods

The static class methods control the lifecycle of containers and other computing resources associated with the [SandboxEnvironment](./reference/inspect_ai.util.html.md#sandboxenvironment):

    podman.py

``` python
class PodmanSandboxEnvironment(SandboxEnvironment):

    @classmethod
    def config_files(cls) -> list[str]:
        ...

    @classmethod
    def is_docker_compatible(cls) -> bool:
        ...

    @classmethod
    def default_concurrency(cls) -> int | None:
        ...

    @classmethod
    def default_polling_interval(cls) -> float | None:
       ...

    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        ...

    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str]
    ) -> dict[str, SandboxEnvironment]:
        ...

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        ...

    @classmethod
    async def task_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        cleanup: bool,
    ) -> None:
       ...

    @classmethod
    async def cli_cleanup(cls, id: str | None) -> None:
        ...

    # (instance methods shown above)
```

    providers.py

``` python
def podman():
    from .podman import PodmanSandboxEnvironment

    return PodmanSandboxEnvironment
```

The layer of indirection (creating a function that returns a SandboxEnvironment class) is done so that you can separate the registration of sandboxes from the importing of libraries they require (important for limiting dependencies).

The class methods take care of various stages of initialisation, setup, and teardown:

| Method | Lifecycle | Purpose |
|----|----|----|
| `task_init()` | Called once for each unique sandbox environment config before executing the tasks in an [eval()](./reference/inspect_ai.html.md#eval) run. | Expensive initialisation operations (e.g. pulling or building images) |
| `sample_init()` | Called at the beginning of each [Sample](./reference/inspect_ai.dataset.html.md#sample). | Create [SandboxEnvironment](./reference/inspect_ai.util.html.md#sandboxenvironment) instances for the sample. |
| `sample_cleanup()` | Called at the end of each [Sample](./reference/inspect_ai.dataset.html.md#sample) | Cleanup [SandboxEnvironment](./reference/inspect_ai.util.html.md#sandboxenvironment) instances for the sample. |
| `task_cleanup()` | Called once for each unique sandbox environment config after executing the tasks in an [eval()](./reference/inspect_ai.html.md#eval) run. | Last chance handler for any resources not yet cleaned up (see also discussion below). |
| `cli_cleanup()` | Called via `inspect sandbox cleanup` | CLI invoked manual cleanup of resources created by this [SandboxEnvironment](./reference/inspect_ai.util.html.md#sandboxenvironment). |
| `config_files()` | Called once to determine the names of ‘default’ config files for this provider (e.g. ‘compose.yaml’). |  |
| `is_docker_compatible()` | Called once to determine whether a provider is Docker compatible. | Can the provider take Dockerfile and compose.yaml as config? |
| `config_deserialize()` | Called when a custom sandbox config type is read from a log file. | Only required if a sandbox supports custom config types. |
| `default_concurrency()` | Called once to determine the default maximum number of sandboxes to run in parallel. Return `None` for no limit (the default behaviour). |  |
| `default_polling_interval()` | Called when sandbox services are created to determine the default polling interval (in seconds) for request checking. Defaults to 2 seconds. |  |

In the case of parallel execution of a group of tasks within the same working directory, the `task_init()` and `task_cleanup()` functions will be called once for each unique sandbox environment configuration (e.g. Docker Compose file). This is a performance optimisation derived from the fact that initialisation and cleanup are shared for tasks with identical configurations.

> **NOTE:**
>
> The “default” [SandboxEnvironment](./reference/inspect_ai.util.html.md#sandboxenvironment) i.e. that named “default” or marked as default in some other provider-specific way, **must** be the first key/value in the dictionary returned from `sample_init()`.

### Cleanup

The `task_cleanup()` has a number of important functions:

1.  There may be global resources that are not tied to samples that need to be cleaned up.
2.  It’s possible that `sample_cleanup()` will be interrupted (e.g. via a Ctrl+C) during execution. In that case its resources are still not cleaned up.
3.  The `sample_cleanup()` function might be long running, and in the case of error or interruption you want to provide explicit user feedback on the cleanup in the console (which isn’t possible when cleanup is run “inline” with samples). An `interrupted` flag is passed to `sample_cleanup()` which allows for varying behaviour for this scenario.
4.  Cleanup may be disabled (e.g. when the user passes `--no-sandbox-cleanup`) in which case it should print container IDs and instructions for cleaning up after the containers are no longer needed.

To implement `task_cleanup()` properly, you’ll likely need to track running environments using a per-coroutine `ContextVar`. The `DockerSandboxEnvironment` provides an example of this. Note that the `cleanup` argument passed to `task_cleanup()` indicates whether to actually clean up (it would be `False` if `--no-sandbox-cleanup` was passed to `inspect eval`). In this case you might want to print a list of the resources that were not cleaned up and provide directions on how to clean them up manually.

The `cli_cleanup()` function is a global cleanup handler that should be able to do the following:

1.  Cleanup *all* environments created by this provider (corresponds to e.g. `inspect sandbox cleanup docker` at the CLI).
2.  Cleanup a single environment created by this provider (corresponds to e.g. `inspect sandbox cleanup docker <id>` at the CLI).

The `task_cleanup()` function will typically print out the information required to invoke `cli_cleanup()` when it is invoked with `cleanup = False`. Try invoking the `DockerSandboxEnvironment` with `--no-sandbox-cleanup` to see an example.

## Docker Compatibility

Many Inspect tasks are defined using the “docker” sandbox provider along with a `Dockerfile` or `compose.yaml` configuration. Many other sandbox providers are capable of using some combination of `Dockerfile` and compose configuration, so can register themselves as docker compatible by implementing the `is_docker_compatible()` class method. For example:

``` python
class PodmanSandboxEnvironment(SandboxEnvironment):
    @classmethod
    def is_docker_compatible(cls) -> bool:
        return True
```

Note if a provider’s `config_files()` method returns `compose.yaml` in its list, then `is_docker_compatible()` will default to `True`.

If a provider is docker compatible, then the `config` argument passed to it’s method may be one of the following (in addition to whatever native configuration the provider supports):

1.  A path to a `Dockerfile`
2.  A path to a `compose.yaml` file.
3.  An instance of the [ComposeConfig](./reference/inspect_ai.util.html.md#composeconfig) class.

These input for `config` might be handled as follows:

``` python
from inspect_ai.util import (
    ComposeConfig,
    is_compose_yaml,
    is_dockerfile,
    parse_compose_yaml
)

if is_dockerfile(config):
   # handle dockerfile

elif is_compose_yaml(config, str):
   # parse and handle compose config
   compose_config = parse_compose_yaml(config)

elif isinstance(config, ComposeConfig):
   # handle compose config

else:
   # handle other config types (if any)
```

## Sandbox Registration

You should build your custom sandbox environment within a Python package, and then register an `inspect_ai` [setuptools entry point](https://setuptools.pypa.io/en/latest/userguide/entry_point.html). This will ensure that inspect loads your extension before it attempts to resolve a sandbox environment that uses your provider.

For example, if your package was named `evaltools` and your sandbox environment provider was exported from a source file named `_registry.py` at the root of your package, you would register it like this in `pyproject.toml`:

``` toml
[project.entry-points.inspect_ai]
evaltools = "evaltools._registry"
```

``` toml
[project.entry-points.inspect_ai]
evaltools = "evaltools._registry"
```

``` toml
[tool.poetry.plugins.inspect_ai]
evaltools = "evaltools._registry"
```

## Sandbox Usage

Once the package is installed, you can refer to the custom sandbox environment the same way you’d refer to a built in sandbox environment. For example:

``` python
Task(
    ...,
    sandbox="podman"
)
```

Sandbox environments can be invoked with an optional configuration parameter, which is passed as the `config` argument to the `startup()` and `setup()` methods. In Python this is done with a tuple

``` python
Task(
    ...,
    sandbox=("podman","config.yaml")
)
```

Specialised configuration types which derive from Pydantic’s `BaseModel` can also be passed as the `config` argument to `SandboxEnvironmentSpec`. Note: they must be hashable (i.e. `frozen=True`).

``` python
class PodmanSandboxEnvironmentConfig(BaseModel, frozen=True):
    socket: str
    runtime: str

Task(
    ...,
    sandbox=SandboxEnvironmentSpec(
        "podman",
        PodmanSandboxEnvironmentConfig(socket="/podman-socket", runtime="crun"),
    )
)
```
