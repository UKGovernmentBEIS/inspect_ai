# Task Configuration – Inspect

## Overview

When running an evaluation, there are four layers where you can set or override task parameters. Each layer takes precedence over any before it:

1.  **Task definition**: defaults baked into the `@task` function and `Task()` constructor.
2.  **[task_with()](./reference/inspect_ai.html.md#task_with)**: programmatic overrides applied to a task object before passing it to [eval()](./reference/inspect_ai.html.md#eval).
3.  **Environment variables / `.env` files**: project or session defaults set outside code.
4.  **[eval()](./reference/inspect_ai.html.md#eval) / CLI**: explicit runtime overrides that take highest precedence.

| Lowest |  |  | Highest |
|----|----|----|----|
| Task definition | [task_with()](./reference/inspect_ai.html.md#task_with) | `.env` / env vars | [eval()](./reference/inspect_ai.html.md#eval) / CLI |

Precedence order (each layer overrides those to its left) {.caption-top .table}

Understanding these layers is key to reusing and adapting tasks without modifying their source code. This article provides a complete reference for what can be overridden, where, and how. For task authoring patterns, see [Tasks](./tasks.html.md); for the full CLI and environment variable catalog, see [Options](./options.html.md); and for model-role-specific guidance, see [Model Roles](./models.html.md#model-roles).

## Configuration Layers

### Layer 1: Task Definition

A @`task`-decorated function returns a [Task](./reference/inspect_ai.html.md#task) object with all its defaults. These are the baseline values that apply when no overrides are specified:

``` python
@task
def security_guide() -> Task:
    return Task(
        dataset=json_dataset("security_guide.json"),
        solver=[chain_of_thought(), generate()],
        scorer=model_graded_fact(),
        epochs=3,
        message_limit=50,
    )
```

Task authors can also expose [parameters](./tasks.html.md#parameters) on the `@task` function, which users can set with `-T` on the CLI or `task_args` in [eval()](./reference/inspect_ai.html.md#eval). For a full guide to designing and using task parameters, see [Parameters](./tasks.html.md#parameters); here the focus is how they fit into the overall override model:

``` python
@task
def security_guide(
    difficulty: str = "medium", 
    temperature: float = 0.0,
) -> Task:
    dataset_file = f"security_guide_{difficulty}.json"
    return Task(
        dataset=json_dataset(dataset_file),
        solver=[chain_of_thought(), generate()],
        scorer=model_graded_fact(),
        config=GenerateConfig(temperature=temperature),
    )
```

Users can then set the task parameters from the command line using the `-T` flag:

``` bash
# CLI
inspect eval security_guide.py -T difficulty=hard -T temperature=1.0
```

> **IMPORTANT: Important**
>
> Duplicating framework parameters like `temperature` as task parameters is not recommended. They can be set directly using the framework’s built-in CLI flags or passing a [GenerateConfig](./reference/inspect_ai.model.html.md#generateconfig) object to `eval(my_task(), config=...)`, and this will override any value set in the task definition.
>
> ``` bash
> # CLI
> inspect eval security_guide.py --temperature 1.0
> ```

### Layer 2: [task_with()](./reference/inspect_ai.html.md#task_with)

Use [task_with()](./reference/inspect_ai.html.md#task_with) when you want to adapt a task you don’t control (e.g. one imported from a package) before passing it to [eval()](./reference/inspect_ai.html.md#eval). It modifies the task **in place** and returns it:

``` python
from inspect_ai import task_with
from inspect_evals.simpleqa import simpleqa

adapted = task_with(
    simpleqa(),
    solver=my_custom_solver(),
    scorer=my_scorer(),
    config=GenerateConfig(temperature=0.0),
    epochs=5,
)
```

[task_with()](./reference/inspect_ai.html.md#task_with) is the **only** way to override `dataset`, `scorer`, `setup`, and `cleanup` at runtime; none of these have CLI flags or [eval()](./reference/inspect_ai.html.md#eval) parameters. For the broader pattern of adapting published tasks, see [Task Reuse](./tasks.html.md#task-reuse).

> **IMPORTANT: ImportantIn-place mutation**
>
> [task_with()](./reference/inspect_ai.html.md#task_with) modifies the passed task in place. If you need multiple variations, create the underlying task multiple times:
>
> ``` python
> # Correct: two independent tasks
> task_a = task_with(simpleqa(), solver=agent_a())
> task_b = task_with(simpleqa(), solver=agent_b())
>
> # Wrong: both end up with agent_b's solver
> base = simpleqa()
> task_a = task_with(base, solver=agent_a())
> task_b = task_with(base, solver=agent_b())
> ```

See the [Override Reference](#override-reference) table below for the complete list of parameters that [task_with()](./reference/inspect_ai.html.md#task_with) accepts. Note that defaults are `NOT_GIVEN` (a sentinel), not `None`; this means you can explicitly pass `None` to clear a value that the base task set. See the API reference for [task_with()](./reference/inspect_ai.html.md#task_with) for the full signature.

### Layer 3: Environment Variables / `.env` Files

Every CLI flag can also be set as an environment variable using the `INSPECT_EVAL_` prefix (with hyphens converted to underscores). These can be set in the shell or placed in a `.env` file, which Inspect reads automatically from the current directory (searching parent directories if not found).

This layer is useful for setting project or session defaults — values you want applied across multiple eval runs without specifying them each time:

    .env

``` makefile
INSPECT_EVAL_MODEL=anthropic/claude-sonnet-4-5
INSPECT_EVAL_TEMPERATURE=0.0
INSPECT_EVAL_MAX_CONNECTIONS=20
INSPECT_EVAL_MAX_RETRIES=5
```

Environment variables set in the shell take precedence over values in `.env` files. See [Options](./options.html.md#env-files) for full details on `.env` file handling.

``` bash
# CLI
INSPECT_EVAL_LIMIT=1 inspect eval simpleqa.py
```

### Layer 4: [eval()](./reference/inspect_ai.html.md#eval) / CLI

Parameters passed to [eval()](./reference/inspect_ai.html.md#eval) or on the `inspect eval` command line are the outermost overrides and take highest precedence. They apply to **all tasks** being evaluated in that call.

**Python:**

``` python
from inspect_ai import eval

eval(
    simpleqa(),
    model="anthropic/claude-sonnet-4-5",
    temperature=0.0,
    max_tokens=4096,
    epochs=5,
    limit=100,
    message_limit=50,
    model_roles={"grader": "google/gemini-2.0-flash"},
)
```

**CLI:**

``` bash
inspect eval inspect_evals/simpleqa \
    --model anthropic/claude-sonnet-4-5 \
    --temperature 0.0 \
    --max-tokens 4096 \
    --epochs 5 \
    --limit 100 \
    --message-limit 50 \
    --model-role grader=google/gemini-2.0-flash
```

See [Eval Options](./options.html.md) for the full list of CLI flags.

## What Can Be Overridden Where

The table below shows every overridable parameter and which layers support it:

| Parameter | [Task](./reference/inspect_ai.html.md#task) | `task_with` | `eval` | CLI flag |
|----|----|----|----|----|
| **Task structure** |  |  |  |  |
| `dataset` | yes | yes |  |  |
| `setup` | yes | yes |  |  |
| `solver` | yes | yes | yes | `--solver` (name or `file.py@name`) |
| `cleanup` | yes | yes |  |  |
| `scorer` | yes | yes |  |  |
| `metrics` | yes | yes |  |  |
| **Model** |  |  |  |  |
| `model` | yes | yes | yes | `--model` |
| `config` [GenerateConfig](reference/inspect_ai.model.html.md#generateconfig) (includes `temperature`, `max_tokens`, etc.) | yes | yes | yes (via `**kwargs`) | individual flags or `--generate-config` |
| `model_roles` | yes | yes | yes | `--model-role` |
| **Execution limits** |  |  |  |  |
| `epochs` | yes | yes | yes | `--epochs` |
| `message_limit` | yes | yes | yes | `--message-limit` |
| `token_limit` | yes | yes | yes | `--token-limit` |
| `time_limit` | yes | yes | yes | `--time-limit` |
| `working_limit` | yes | yes | yes | `--working-limit` |
| `cost_limit` | yes | yes | yes | `--cost-limit` |
| `early_stopping` | yes | yes |  |  |
| **Error handling** |  |  |  |  |
| `fail_on_error` | yes | yes | yes | `--fail-on-error` |
| `continue_on_fail` | yes | yes | yes | `--continue-on-fail` |
| `retry_on_error` |  |  | yes | `--retry-on-error` |
| `debug_errors` |  |  | yes | `--debug-errors` |
| **Environment** |  |  |  |  |
| `sandbox` | yes | yes | yes | `--sandbox` |
| `sandbox_cleanup` |  | yes | yes | `--no-sandbox-cleanup` |
| `approval` | yes | yes | yes | `--approval` |
| **Task identity** |  |  |  |  |
| `name` | yes | yes |  |  |
| `version` | yes | yes |  |  |
| `metadata` | yes | yes (overwrites) | yes (merges) | `--metadata` |
| `tags` | yes | yes (overwrites) | yes (merges) | `--tags` |
| **Sample selection** |  |  |  |  |
| `limit` |  |  | yes | `--limit` |
| `sample_id` |  |  | yes | `--sample-id` |
| `sample_shuffle` |  |  | yes | `--sample-shuffle` |
| **Eval-level controls** |  |  |  |  |
| `task_args` | args/kwargs |  | yes | `-T key=value` |
| `score` |  |  | yes | `--no-score` |
| `score_display` |  |  | yes | `--no-score-display` |
| `trace` |  |  | yes | `--trace` |

Blank cells indicate that a parameter is not configurable at that layer. The `task_args` row indicates these fields are set as arguments of the [Task](./reference/inspect_ai.html.md#task) object, as opposed to passing a `task_args` dictionary.

## Generation Config

[GenerateConfig](./reference/inspect_ai.model.html.md#generateconfig) parameters (`temperature`, `max_tokens`, `top_p`, etc.) can be set at every layer:

**In the task definition** via `config`:

``` python
Task(
    ...,
    config=GenerateConfig(temperature=0.5, max_tokens=2048)
)
```

**With [task_with()](./reference/inspect_ai.html.md#task_with)** via `config`:

``` python
task_with(my_task(), config=GenerateConfig(temperature=0.0))
```

**With [eval()](./reference/inspect_ai.html.md#eval)** as keyword arguments:

``` python
eval(my_task(), temperature=0.0, max_tokens=4096)
```

**On the CLI** as individual flags:

``` bash
inspect eval my_task.py --temperature 0.0 --max-tokens 4096
```

**On the CLI** from a YAML/JSON file using `--generate-config`:

``` bash
inspect eval my_task.py --generate-config config.yaml
```

Where `config.yaml` contains [GenerateConfig](./reference/inspect_ai.model.html.md#generateconfig) fields:

    config.yaml

``` yaml
temperature: 0.5
max_tokens: 2048
```

The `--generate-config` option is useful when you want to bundle a set of generation parameters together, for example to capture the parameters specified in a paper for reproducibility. Individual CLI flags (e.g. `--temperature`) take precedence over values in the config file.

## Model Roles

Model roles let you assign different models to named purposes within a task (e.g. a “grader” model for scoring). They can be configured on [Task](./reference/inspect_ai.html.md#task), with [task_with()](./reference/inspect_ai.html.md#task_with), with [eval()](./reference/inspect_ai.html.md#eval), or on the CLI with `--model-role`; see the override table above for where each form fits into the precedence model.

For complete guidance, including inline YAML / JSON examples and role-resolution details, see [Model Roles](./models.html.md#model-roles). Here is the most common pattern:

``` python
Task(..., model_roles={"grader": "openai/gpt-4o"})
eval(my_task(), model_roles={"grader": "google/gemini-2.0-flash"})
```

Inside a solver or scorer, resolve the role with [get_model()](./reference/inspect_ai.model.html.md#get_model):

``` python
model = get_model(role="grader", default="openai/gpt-4o")
```

## Solver Override

The solver can be overridden at every layer:

**With [task_with()](./reference/inspect_ai.html.md#task_with)** — any solver or agent object:

``` python
task_with(my_task(), solver=my_custom_agent())
```

**With [eval()](./reference/inspect_ai.html.md#eval)** — solver objects, [SolverSpec](./reference/inspect_ai.solver.html.md#solverspec), agents, or a list of solvers:

``` python
eval(my_task(), solver=my_custom_agent())
```

**On the CLI** — by name or `file.py@name` reference:

``` bash
# solver registered via @solver decorator
inspect eval my_task.py --solver my_registered_solver -S attempts=5

# solver defined in a file (file.py@function_name)
inspect eval my_task.py --solver solvers.py@ctf_agent -S attempts=5
```

Any function decorated with `@solver` is automatically registered with Inspect and can be referenced by name (see [Custom Solvers](./solvers.html.md#custom-solvers)). The `file.py@name` syntax lets you reference a solver in any Python file without needing package registration. The `-S` flag passes arguments to the solver function; you can also use `--solver-config` to pass solver arguments from a YAML or JSON file. See [Tasks and Solvers](./options.html.md#tasks-and-solvers) for the corresponding CLI options.

> **NOTE: Note**
>
> When a solver is overridden, it **replaces** the task’s solver entirely. Solvers do not merge or chain across layers. However, the task’s `setup` solver (if any) always runs before the overridden solver. See [Setup Parameter](./tasks.html.md#setup-parameter) for details.

## Scorer Override

The scorer can **only** be overridden via [task_with()](./reference/inspect_ai.html.md#task_with) during a live eval. There is no [eval()](./reference/inspect_ai.html.md#eval) parameter or CLI flag for scorers:

``` python
task_with(my_task(), scorer=my_custom_scorer())
```

Some task authors expose scorer selection as a [task parameter](./tasks.html.md#parameters), which can then be set with `-T`:

``` bash
inspect eval my_task.py -T scorer=original
```

This is a convention, not a framework feature — the task’s `@task` function must explicitly handle the parameter.

> **TIP: TipRe-scoring existing logs**
>
> You can re-score an existing log file with a different scorer using `inspect score`. The `--scorer` flag accepts a name (any function decorated with `@scorer` — see [Custom Scorers](./scorers.html.md#custom-scorers)) or a `file.py@name` reference:
>
> ``` bash
> # scorer registered via @scorer decorator
> inspect score log_file.eval --scorer my_scorer
>
> # scorer defined in a file
> inspect score log_file.eval --scorer scorers.py@custom_scorer
> ```

## Precedence

When the same parameter is set at multiple levels, the outermost level wins. The full precedence chain is:

| Lowest |  |  |  | Highest |
|----|----|----|----|----|
| Task definition | [task_with()](./reference/inspect_ai.html.md#task_with) | `.env` file | env var | CLI flag / [eval()](./reference/inspect_ai.html.md#eval) |

Full precedence chain {.caption-top .table}

An explicit CLI flag overrides an environment variable, which overrides a value from a `.env` file, which overrides [task_with()](./reference/inspect_ai.html.md#task_with), which overrides the task definition.

For example, a task that sets `temperature=0.5` internally can be overridden at runtime:

``` bash
inspect eval my_task.py --temperature 0.0
```

Or via environment variable:

``` bash
export INSPECT_EVAL_TEMPERATURE=0.0
inspect eval my_task.py
```

Or in Python:

``` python
eval(my_task(), temperature=0.0)
```

For [GenerateConfig](./reference/inspect_ai.model.html.md#generateconfig) specifically, values from `--generate-config` (a YAML/JSON file) are merged with individual CLI flags, with individual flags taking precedence over the file.

## Common Patterns

When consuming a task from a package (like `inspect_evals`) and you need to customise it, here is the recommended approach for each scenario:

| Need | How |
|----|----|
| Different model | [eval()](./reference/inspect_ai.html.md#eval) / `--model` |
| Different temperature or max_tokens | [eval()](./reference/inspect_ai.html.md#eval) / `--temperature` / `--max-tokens` |
| Bundle of generation params | `--generate-config config.yaml` |
| Different solver | `eval(solver=...)` / `--solver` / [task_with()](./reference/inspect_ai.html.md#task_with) |
| Different scorer | `task_with(task, scorer=...)` |
| Different grader model | `--model-role grader=...` / `eval(model_roles=)` |
| Different metrics | `task_with(task, metrics=[...])` |
| Subset of samples | `--limit` / `--sample-id` |
| Different epochs | `--epochs` |

Most components except `scorer`, `dataset`, and `metrics` can be overridden without modifying the task’s source code. If the task author uses `get_model(role="grader")` for model-graded scoring, the grader model becomes overridable at runtime via `--model-role`.
