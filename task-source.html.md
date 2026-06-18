# Task Sources – Inspect

> **NOTE:**
>
> Task sources require the development version of Inspect, which you can install from GitHub:
>
> ``` bash
> pip install git+https://github.com/UKGovernmentBEIS/inspect_ai
> ```

## Overview

The `tasks` argument to [eval()](./reference/inspect_ai.html.md#eval) is normally static: you pass a [Task](./reference/inspect_ai.html.md#task) (or list of tasks) and the run executes those. A [TaskSource](./reference/inspect_ai.html.md#tasksource) generates tasks dynamically instead — a seed plus follow-ups that depend on results — all under one run id.

Use it when the next tasks to run depend on the results of the previous ones:

- Reinforcement-learning or curriculum loops that generate follow-ups from a batch’s scores.
- Open-ended generation that runs until some external condition stops it.
- Adaptive evaluation that branches the task set based on model performance.

A [TaskSource](./reference/inspect_ai.html.md#tasksource) is just a value the `tasks` parameter accepts, so there is no separate argument.

> **NOTE:**
>
> Task sources are supported by [eval()](./reference/inspect_ai.html.md#eval) / `eval_async()` (and `inspect eval`) only. `eval_set`, `eval_retry`, and `score` require a fixed, resumable set of tasks and raise an error if passed one.

## Defining a source

Subclass [TaskSource](./reference/inspect_ai.html.md#tasksource) and override the methods you need (the defaults are no-ops):

``` python
from inspect_ai import Task, TaskSource
from inspect_ai.log import EvalLog, EvalSample


class MySource(TaskSource):
    def initial_tasks(self) -> list[Task]:
        """Seed tasks to run first (synchronous)."""
        ...

    async def next_tasks(self) -> list[Task] | None:
        """The next batch, or None when the run is complete."""
        ...

    async def sample_complete(
        self, sample: EvalSample, task: Task
    ) -> list[Task] | None:
        """Observe a finished sample; optionally return follow-up tasks."""
        ...

    async def task_complete(self, log: EvalLog) -> list[Task] | None:
        """Observe a finished task; optionally return follow-up tasks."""
        ...
```

Pass an instance as `tasks`:

``` python
from inspect_ai import eval

eval(MySource(), model="openai/gpt-4o", limit=10)
```

`initial_tasks()` is synchronous and returns the seed. It is resolved up front like any task list, so it must return immediately rather than `await`. `next_tasks()` is async, called after each batch completes, and may block (for example, awaiting external input); return `None` to end the run.

Each task gets its own `eval_id`, `task_id`, and log file; all share one run id.

## Returning follow-up tasks

`sample_complete` and `task_complete` fire as work completes. Besides observing results, they can return tasks to add to the run, which run after the current batch. `sample_complete` also receives the [Task](./reference/inspect_ai.html.md#task) the sample ran under (the sample alone doesn’t identify its task):

``` python
class Curriculum(TaskSource):
    def initial_tasks(self) -> list[Task]:
        return [easy_task()]

    async def task_complete(self, log: EvalLog) -> list[Task] | None:
        # advance only if the model passed
        accuracy = log.results.scores[0].metrics["accuracy"].value
        if accuracy >= 0.8:
            return [harder_task()]
        return None
```

A source that returns follow-ups from these callbacks needs no `next_tasks()`: the run ends when the callbacks return nothing and `next_tasks()` returns `None`. Use `next_tasks()` for the blocking case a per-result callback can’t express.

## Sources from callbacks

`TaskSource.from_tasks()` builds a source from a seed and optional callbacks, without subclassing:

``` python
from inspect_ai import TaskSource

scores: list[float] = []

async def on_task(log):
    scores.append(log.results.scores[0].metrics["accuracy"].value)
    return [next_task()] if sum(scores) / len(scores) < 0.9 else None

source = TaskSource.from_tasks([seed_task()], task_complete=on_task)
eval(source, model="openai/gpt-4o")
```

`from_tasks(initial_tasks, *, next_tasks=None, sample_complete=None, task_complete=None)` delegates to the callables. Omitting `next_tasks` and returning nothing from the callbacks stops after the seed.

## The @task_source decorator

`@task_source` registers a named, parameterized source, like `@task`:

``` python
from inspect_ai import TaskSource, task_source


@task_source(name="curriculum")
def curriculum(target: float = 0.8) -> TaskSource:
    async def advance(log):
        accuracy = log.results.scores[0].metrics["accuracy"].value
        return [harder_task()] if accuracy >= target else None

    return TaskSource.from_tasks([easy_task()], task_complete=advance)
```

Run it from the CLI like a task, including `-T` arguments and a `file.py@name` spec:

``` bash
inspect eval curriculum.py@curriculum -T target=0.9 --model openai/gpt-4o
```

[eval()](./reference/inspect_ai.html.md#eval) accepts a [TaskSource](./reference/inspect_ai.html.md#tasksource) instance, a `@task_source` function, a registered name, or a `file.py@name` spec.

## Adding tasks imperatively

[enqueue_task()](./reference/inspect_ai.html.md#enqueue_task) adds tasks to the current run from any code — a solver, scorer, or tool — not only a [TaskSource](./reference/inspect_ai.html.md#tasksource):

``` python
from inspect_ai import enqueue_task
from inspect_ai.solver import Generate, TaskState, solver


@solver
def spawn_followup():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        enqueue_task(followup_task())
        return state

    return solve
```

Enqueued tasks run under the current run id, resolved against the run’s models and config, and share a buffer with tasks returned from `sample_complete` / `task_complete`. [enqueue_task()](./reference/inspect_ai.html.md#enqueue_task) raises if no eval is running.

## Concurrency

A [TaskSource](./reference/inspect_ai.html.md#tasksource) run is live: a task added mid-run starts as soon as there is free capacity, rather than waiting for a batch boundary.

Capacity is bounded by `max_tasks` (the number of concurrent task × model units). If the seed fills every slot, a follow-up waits until a slot frees, so to run follow-ups alongside the seed, set `max_tasks` above the number of seed units. A seed of two tasks across two models is four units, so `--max-tasks 6` leaves room:

``` bash
inspect eval curriculum.py@curriculum --max-tasks 6 --model openai/gpt-4o,openai/gpt-4o-mini
```

With the default `max_tasks` (the model count), follow-ups run after a seed task finishes rather than alongside it. See [Parallelism](./parallelism.html.md) for more on `max_tasks`.
