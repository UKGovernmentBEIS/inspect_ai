# Hooks – Inspect

Hooks enable you to run arbitrary code during certain events of Inspect’s lifecycle, for example when runs, tasks or samples start and end.

## Hooks Usage

Here is a very simple hypothetical integration with Weights & Biases.

``` python
import wandb

from inspect_ai.hooks import Hooks, RunEnd, RunStart, SampleEnd, hooks

@hooks(name="w&b_hooks", description="Weights & Biases integration")
class WBHooks(Hooks):
    async def on_run_start(self, data: RunStart) -> None:
        wandb.init(name=data.run_id)

    async def on_run_end(self, data: RunEnd) -> None:
        wandb.finish()

    async def on_sample_end(self, data: SampleEnd) -> None:
        if data.sample.scores:
            scores = {k: v.value for k, v in data.sample.scores.items()}
            wandb.log({
                "sample_id": data.sample_id,
                "scores": scores,
            })
```

For a more complete example of creating hooks see the [wandb_weave.py](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/examples/hooks/wandb_weave.py), [mlflow_tracking.py](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/examples/hooks/mlflow_tracking.py), and [mlflow_tracing.py](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/examples/hooks/mlflow_tracing.py) examples.

The example above overrides three lifecycle events; [Hook Events](#sec-hook-events) below lists the full set you can implement. A [Hooks](./reference/inspect_ai.hooks.html.md#hooks) subclass only needs to override the events it cares about, and a single class may handle any combination of events.

Alternatively, you may decorate a function which returns the type of a [Hooks](./reference/inspect_ai.hooks.html.md#hooks) subclass to create a layer of indirection so that you can separate the registration of hooks from the importing of libraries they require (important for limiting dependencies).

    providers.py

``` python
@hooks(name="w&b_hooks", description="Weights & Biases integration")
def wandb_hooks():
    from .wb_hooks import WBHooks

    return WBHooks
```

## Hook Events

Each event method is `async`, returns `None`, and receives a single immutable data object carrying the details of the event. Implement only the methods you need. The events below are grouped by lifecycle level, from the outermost scope (an entire [eval_set()](./reference/inspect_ai.html.md#eval_set)) down to individual model calls. All of the data types are importable from `inspect_ai.hooks`; see the [`inspect_ai.hooks`](./reference/inspect_ai.hooks.html.md) reference for their full field definitions.

### Run and Task

These events bracket the execution of evaluations. A single [eval()](./reference/inspect_ai.html.md#eval) (or [eval_retry()](./reference/inspect_ai.html.md#eval_retry)) is a *run*, which executes one or more *tasks*; an [eval_set()](./reference/inspect_ai.html.md#eval_set) groups multiple runs against a shared log directory.

| Method | Data | Called |
|----|----|----|
| `on_eval_set_start` | [EvalSetStart](./reference/inspect_ai.hooks.html.md#evalsetstart) | When an [eval_set()](./reference/inspect_ai.html.md#eval_set) for a log directory starts (`eval_set_id` is stable across re-invocations for the same log dir). |
| `on_eval_set_end` | [EvalSetEnd](./reference/inspect_ai.hooks.html.md#evalsetend) | When an eval set finishes. |
| `on_run_start` | [RunStart](./reference/inspect_ai.hooks.html.md#runstart) | At the start of a single [eval()](./reference/inspect_ai.html.md#eval) / [eval_retry()](./reference/inspect_ai.html.md#eval_retry) invocation (`data.task_names` lists the tasks to run). |
| `on_run_end` | [RunEnd](./reference/inspect_ai.hooks.html.md#runend) | At the end of a run — `data.exception` and `data.logs` carry the outcome. |
| `on_task_start` | [TaskStart](./reference/inspect_ai.hooks.html.md#taskstart) | When a task begins executing (`data.spec` is the [EvalSpec](./reference/inspect_ai.log.html.md#evalspec)). |
| `on_task_end` | [TaskEnd](./reference/inspect_ai.hooks.html.md#taskend) | When a task completes (`data.log` is the [EvalLog](./reference/inspect_ai.log.html.md#evallog)). |

### Sample

These events track the lifecycle of individual samples. Note the distinction between *epoch-level* events (fired once per sample per epoch) and *attempt-level* events (fired on every attempt, including retries).

| Method | Data | Called |
|----|----|----|
| `on_sample_init` | [SampleInit](./reference/inspect_ai.hooks.html.md#sampleinit) | When a sample is scheduled, before its sandbox environments are created. Once per epoch; not called on retries. |
| `on_sample_start` | [SampleStart](./reference/inspect_ai.hooks.html.md#samplestart) | When a sample is about to start executing. Once per epoch; not called on retries. |
| `on_sample_attempt_start` | [SampleAttemptStart](./reference/inspect_ai.hooks.html.md#sampleattemptstart) | At the beginning of every attempt, including retries (`data.attempt` is 1-based). |
| `on_sample_attempt_end` | [SampleAttemptEnd](./reference/inspect_ai.hooks.html.md#sampleattemptend) | At the end of every attempt — `data.error` and `data.will_retry` describe the outcome. |
| `on_sample_event` | [SampleEvent](./reference/inspect_ai.hooks.html.md#sampleevent) | Each time a sample event (e.g. a [ModelEvent](./reference/inspect_ai.event.html.md#modelevent) or [ToolEvent](./reference/inspect_ai.event.html.md#toolevent)) is logged. Fires many times per sample. |
| `on_sample_scoring` | `SampleScoring` | After the solver completes and before scoring begins. |
| `on_sample_end` | [SampleEnd](./reference/inspect_ai.hooks.html.md#sampleend) | When a sample completes (or errors with no retries remaining). Once per epoch; `data.sample` is the full [EvalSample](./reference/inspect_ai.log.html.md#evalsample). |

### Model

These events surround calls to model providers, and are useful for tracking usage/cost or modifying requests in flight.

| Method | Data | Called |
|----|----|----|
| `on_before_model_generate` | `BeforeModelGenerate` | Before a model’s [generate()](./reference/inspect_ai.solver.html.md#generate) is invoked. Mutating `data.input`, `data.tools`, or `data.config` affects both the cache key and the actual API call. Fires once per retry attempt. |
| `on_model_usage` | [ModelUsageData](./reference/inspect_ai.hooks.html.md#modelusagedata) | When a model call completes *without* hitting Inspect’s local cache (`data.usage`, `data.call_duration`, `data.retries`). |
| `on_model_cache_usage` | `ModelCacheUsageData` | When a model call is satisfied by Inspect’s local cache (`data.usage`). |

> **WARNING:**
>
> Event data is owned by the framework. In particular, objects reachable from `SampleEvent.event` and `SampleEnd.sample` **must not be mutated in place** — read what you need (and deep-copy if you need a mutable working copy). Mutating inputs in `on_before_model_generate` is the exception: it is explicitly supported and intended.

Hooks run within the evaluation, so keep them fast and resilient. Events from different samples and tasks may fire concurrently, and any exception raised by a hook is caught and logged as a warning (it does not fail the run) — with the exception of [LimitExceededError](./reference/inspect_ai.util.html.md#limitexceedederror), which is allowed to propagate so that hooks can enforce limits.

In addition to these lifecycle events, two non-event methods let you control hook behaviour: [`enabled()`](#disabling-hooks) gates whether a hook is active, and [`override_api_key()`](#api-key-override) can rewrite model API keys. Both are covered below.

## Registration

Packages that provide hooks should register an `inspect_ai` [setuptools entry point](https://setuptools.pypa.io/en/latest/userguide/entry_point.html). This will ensure that inspect loads the extension at startup.

For example, let’s say your package is named `evaltools` and has this structure:

    evaltools/
      wandb.py
      _registry.py
    pyproject.toml

The `_registry.py` file serves as a place to import things that you want registered with Inspect. For example:

    _registry.py

``` python
from .wandb import wandb_hooks
```

You can then register your `wandb_hooks` Inspect extension (and anything else imported into `_registry.py`) like this in `pyproject.toml`:

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

Once you’ve done this, your hook will be enabled for Inspect users that have this package installed.

## Disabling Hooks

You might not always want every installed hook enabled—for example, a Weights and Biases hook might only want to be enabled if a specific environment variable is defined. You can control this by implementing an `enabled()` method on your hook. For example:

``` python
@hooks(name="w&b_hooks", description="Weights & Biases integration")
class WBHooks(Hooks):
    def enabled(self) -> bool:
        return "WANDB_API_KEY" in os.environ
    ...
```

Because `enabled()` is consulted before every hook invocation (potentially many times per sample), keep its implementation cheap or cache the result.

## Requiring Hooks

Another thing you might want to do is *ensure* that all users in a given environment are running with a particular set of hooks enabled. To do this, define the `INSPECT_REQUIRED_HOOKS` environment variable, listing all of the hooks that are required:

``` bash
INSPECT_REQUIRED_HOOKS=w&b_hooks
```

If the required hooks aren’t installed then an appropriate error will occur at startup time.

## API Key Override

There is a hook event to optionally override the value of model API key environment variables. The `override_api_key()` hook is called during model initialization and automatically when authentication errors are detected.

This could be used to:

- Refresh API keys or tokens during long-running evaluations
- Inject API keys at runtime (e.g. fetched from a secrets manager), to avoid having to store these in your environment or .env file
- Use some custom model API authentication mechanism in conjunction with a custom reverse proxy for the model API to avoid Inspect ever having access to real API keys

``` python
from inspect_ai.hooks import hooks, Hooks, ApiKeyOverride

@hooks(name="api_key_fetcher", description="Fetches API key from secrets manager")
class ApiKeyFetcher(Hooks):
    def override_api_key(self, data: ApiKeyOverride) -> str | None:
        original_env_var_value = data.value
        if original_env_var_value.startswith("arn:aws:secretsmanager:"):
            return fetch_aws_secret(original_env_var_value)
        return None

def fetch_aws_secret(aws_arn: str) -> str:
    ...
```
