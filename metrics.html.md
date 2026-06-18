# Scoring Metrics – Inspect

## Overview

Each scorer provides one or more built-in metrics (typically `accuracy` and `stderr`) corresponding to the most typically useful metrics for that scorer.

You can override scorer’s built-in metrics by passing an alternate list of `metrics` to the [Task](./reference/inspect_ai.html.md#task). For example:

``` python
Task(
    dataset=dataset,
    solver=[
        system_message(SYSTEM_MESSAGE),
        multiple_choice()
    ],
    scorer=choice(),
    metrics=[custom_metric()]
)
```

If you still want to compute the built-in metrics, we re-specify them along with the custom metrics:

``` python
metrics=[accuracy(), stderr(), custom_metric()]
```

## Built-In Metrics

Inspect includes some simple built in metrics for calculating accuracy, mean, etc. Built in metrics can be imported from the `inspect_ai.scorer` module. Below is a summary of these metrics. See the [`inspect_ai.scorer`](./reference/inspect_ai.scorer.html.md) reference for complete function signatures and options.

- [accuracy()](./reference/inspect_ai.scorer.html.md#accuracy)

  Compute proportion of total answers which are correct. For correct/incorrect scores assigned 1 or 0, can optionally assign 0.5 for partially correct answers.

- [mean()](./reference/inspect_ai.scorer.html.md#mean)

  Mean of all scores.

- `var()`

  Sample variance over all scores.

- [std()](./reference/inspect_ai.scorer.html.md#std)

  Standard deviation over all scores (see below for details on computing clustered standard errors).

- [stderr()](./reference/inspect_ai.scorer.html.md#stderr)

  Standard error of the mean.

- [bootstrap_stderr()](./reference/inspect_ai.scorer.html.md#bootstrap_stderr)

  Standard deviation of a bootstrapped estimate of the mean. 1000 samples are taken by default (modify this using the `num_samples` option).

- [frequency()](./reference/inspect_ai.scorer.html.md#frequency)

  Frequency of each distinct categorical score value. By default this reports proportions over scored observations; pass `normalize=False` to report counts. If a task uses epochs, [frequency()](./reference/inspect_ai.scorer.html.md#frequency) receives unreduced epoch scores, so each scored sample epoch is an observation.

- [categorical()](./reference/inspect_ai.scorer.html.md#categorical)

  Convenience helper for categorical scorers. Returns [frequency()](./reference/inspect_ai.scorer.html.md#frequency) with optional declared categories, typically from a [StrEnum](./reference/inspect_ai.util.html.md#strenum), so zero-count categories are included and metrics can be recomputed from logs.

## Metric Grouping

The [grouped()](./reference/inspect_ai.scorer.html.md#grouped) function applies a given metric to subgroups of samples defined by a key in sample `metadata`, creating a separate metric for each group along with an `"all"` metric that aggregates across all samples or groups. Each sample must have a value for whatever key is used for grouping.

For example, let’s say you wanted to create a separate accuracy metric for each distinct “category” variable defined in [Sample](./reference/inspect_ai.dataset.html.md#sample) metadata:

``` python
@task
def gpqa():
    return Task(
        dataset=read_gpqa_dataset("gpqa_main.csv"),
        solver=[
            system_message(SYSTEM_MESSAGE),
            multiple_choice(),
        ],
        scorer=choice(),
        metrics=[grouped(accuracy(), "category"), stderr()]
    )
```

The `metrics` passed to the [Task](./reference/inspect_ai.html.md#task) override the default metrics of the [choice()](./reference/inspect_ai.scorer.html.md#choice) scorer.

Note that the `"all"` metric by default takes the selected metric over all of the samples. If you prefer that it take the mean of the individual grouped values, pass `all="groups"`:

``` python
grouped(accuracy(), "category", all="groups")
```

You can customize the metric names using the `name_template` parameter. The template uses `{group_name}` as a placeholder for the group value:

``` python
grouped(accuracy(), "category", name_template="category_{group_name}")
```

This would produce metrics named `category_physics`, `category_chemistry`, etc. instead of just `physics`, `chemistry`. It does not affect the “all” metric, so that can be named separately.

## Clustered Stderr

The [stderr()](./reference/inspect_ai.scorer.html.md#stderr) metric supports computing [clustered standard errors](https://en.wikipedia.org/wiki/Clustered_standard_errors) via the `cluster` parameter. Most scorers already include [stderr()](./reference/inspect_ai.scorer.html.md#stderr) as a built-in metric, so to compute clustered standard errors you’ll want to specify custom `metrics` for your task (which will override the scorer’s built in metrics).

For example, let’s say you wanted to cluster on a “category” variable defined in [Sample](./reference/inspect_ai.dataset.html.md#sample) metadata:

``` python
@task
def gpqa():
    return Task(
        dataset=read_gpqa_dataset("gpqa_main.csv"),
        solver=[
            system_message(SYSTEM_MESSAGE),
            multiple_choice(),
        ],
        scorer=choice(),
        metrics=[accuracy(), stderr(cluster="category")]
    )
```

The `metrics` passed to the [Task](./reference/inspect_ai.html.md#task) override the default metrics of the [choice()](./reference/inspect_ai.scorer.html.md#choice) scorer.

## Custom Metrics

You can also add your own metrics with `@metric` decorated functions. For example, here is the implementation of the mean metric:

``` python
import numpy as np

from inspect_ai.scorer import Metric, Score, metric

@metric
def mean() -> Metric:
    """Compute mean of all scores.

    Returns:
       mean metric
    """

    def metric(scores: list[SampleScore]) -> float:
        return np.mean([score.score.as_float() for score in scores]).item()

    return metric
```

Note that the [Score](./reference/inspect_ai.scorer.html.md#score) class contains a [Value](./reference/inspect_ai.scorer.html.md#value) that is a union over several scalar and collection types. As a convenience, [Score](./reference/inspect_ai.scorer.html.md#score) includes a set of accessor methods to treat the value as a simpler form (e.g. above we use the `score.as_float()` accessor).

## Example

This task pairs a float-valued scorer with a custom `pass_rate()` metric (the fraction of samples scoring at or above a threshold), reported alongside the built-in [mean()](./reference/inspect_ai.scorer.html.md#mean) and [stderr()](./reference/inspect_ai.scorer.html.md#stderr):

``` python
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import (
    Metric,
    SampleScore,
    Score,
    Target,
    mean,
    metric,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState, generate


@metric
def pass_rate(threshold: float = 0.5) -> Metric:
    """Proportion of samples scoring at or above `threshold`."""

    def metric(scores: list[SampleScore]) -> float:
        if not scores:
            return 0.0
        passed = [s for s in scores if s.score.as_float() >= threshold]
        return len(passed) / len(scores)

    return metric


@scorer(metrics=[mean(), stderr(), pass_rate()])
def word_overlap():
    async def score(state: TaskState, target: Target) -> Score:
        output = state.output.completion.lower()
        words = target.text.lower().split()
        hits = sum(1 for word in words if word in output)
        return Score(value=hits / len(words) if words else 0.0)

    return score


@task
def colors():
    return Task(
        dataset=[Sample(input="Name three primary colors.", target="red green blue")],
        solver=generate(),
        scorer=word_overlap(),
    )
```

The eval log reports `mean`, `stderr`, and `pass_rate` for the `word_overlap` scorer. Because `pass_rate` is attached to the scorer via `@scorer(metrics=...)`, it is applied automatically; you can also override a scorer’s metrics per-task as shown in the [Overview](#overview).

## Reducing Epochs

If a task is run over more than one `epoch`, multiple scores will be generated for each sample. Metrics normally operate on a reduced score view, where epoch scores for each sample are combined into a single score.

By default, the reduced view is built with `mean`. You may specify other strategies by passing an [Epochs](./reference/inspect_ai.html.md#epochs), which includes both a count and one or more reducers to combine sample scores with. For example:

``` python
@task
def gpqa():
    return Task(
        dataset=read_gpqa_dataset("gpqa_main.csv"),
        solver=[
            system_message(SYSTEM_MESSAGE),
            multiple_choice(),
        ],
        scorer=choice(),
        epochs=Epochs(5, "mode"),
    )
```

You may also specify more than one reducer which will compute metrics using each of the reducers. For example:

``` python
@task
def gpqa():
    return Task(
        ...
        epochs=Epochs(5, ["at_least_2", "at_least_5"]),
    )
```

Some metrics require unreduced epoch scores. These metrics run once over the raw sample-epoch scores, even when an explicit reducer is configured:

``` python
@scorer(metrics=[accuracy(), frequency()])
def my_scorer() -> Scorer:
    ...
```

With `epochs=Epochs(5, "mode")`, [accuracy()](./reference/inspect_ai.scorer.html.md#accuracy) receives one mode-reduced score per sample, while [frequency()](./reference/inspect_ai.scorer.html.md#frequency) receives all scored sample-epoch values. With multiple reducers, reduced metrics run once for each reducer and unreduced metrics run once.

If you disable reducers with `Epochs(n, [])` or `--no-epochs-reducer`, legacy `scores="auto"` metrics receive unreduced sample-epoch scores, preserving existing behavior. Metrics that explicitly declare `scores="reduced"` require a reducer when multiple epochs are present.

### Built-in Reducers

Inspect includes several built in reducers which are summarised below.

| Reducer | Description |
|----|----|
| mean | Reduce to the average of all scores. |
| median | Reduce to the median of all scores |
| mode | Reduce to the most common score. |
| max | Reduce to the maximum of all scores. |
| pass_at\_{k} | Probability of at least 1 correct sample given `k` epochs (<https://arxiv.org/pdf/2107.03374>) |
| pass_k\_{k} | Probability that all `k` epoch attempts succeed (<https://arxiv.org/pdf/2406.12045>) |
| at_least\_{k} | `1` if at least `k` samples are correct, else `0`. |

> **NOTE: Note**
>
> The built in reducers will compute a reduced `value` for the score and populate the fields `answer` and `explanation` only if their value is equal across all epochs. The `metadata` field will always be reduced to the value of `metadata` in the first epoch. If your custom metrics function needs differing behavior for reducing fields, you should also implement your own custom reducer and merge or preserve fields in some way.

### Custom Reducers

You can also add your own reducer with `@score_reducer` decorated functions. Here’s a somewhat simplified version of the code for the `mean` reducer:

``` python
import statistics

from inspect_ai.scorer import (
    Score, ScoreReducer, score_reducer, value_to_float
)

@score_reducer(name="mean")
def mean_score() -> ScoreReducer:
    to_float = value_to_float()

    def reduce(scores: list[Score]) -> Score:
        """Compute a mean value of all scores."""
        values = [to_float(score.value) for score in scores]
        mean_value = statistics.mean(values)

        return Score(value=mean_value)

    return reduce
```

### Metrics and Reducers

Metrics can declare that they need unreduced scores in order to properly compute their value using `scores`. For example:

``` python
@metric(scores="unreduced")
def frequency_by_label() -> Metric:
    ...
```

By default `scores="auto"` so metrics receive reduced scores unless epoch reducers are explicitly disabled. Use `scores="reduced"` for metrics that require one score per sample, and `scores="unreduced"` for metrics that require one score per sample epoch.

| Metric score view | Input when epochs are used |
|----|----|
| `scores="auto"` | Reduced scores, unless epoch reducers are explicitly disabled. |
| `scores="reduced"` | Reduced scores; requires an epoch reducer when multiple epoch scores are present. |
| `scores="unreduced"` | Raw sample-epoch scores, one observation for each scored epoch. |

For example, [frequency()](./reference/inspect_ai.scorer.html.md#frequency) declares `scores="unreduced"` because it reports the distribution of categorical outcomes across all scored observations.
