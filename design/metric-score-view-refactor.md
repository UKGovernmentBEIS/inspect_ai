# Metric Score-View Refactor

## Goal

Make epoch reduction a metric-level input contract while preserving legacy
behavior for existing metrics and `--no-epochs-reducer`.

Today one scorer gets one score view, so `frequency()` can force neighbouring
metrics like `accuracy()` onto unreduced epoch scores. The refactor should let
each metric choose its input view independently.

## Metric Modes

```python
MetricScores = Literal["auto", "reduced", "unreduced"]
```

| Mode | Meaning |
| --- | --- |
| `auto` / omitted | Legacy behavior. Use reduced scores unless reducers are explicitly disabled. |
| `reduced` | Requires one score per sample. |
| `unreduced` | Requires one score per sample epoch. |

Compatibility requirement: omitted `scores=` must mean `auto`, not explicit
`"reduced"`.

```python
def metric_scores(metric: Metric) -> MetricScores:
    return cast(
        MetricScores,
        registry_info(metric).metadata.get(METRIC_SCORES, "auto"),
    )
```

```python
def metric(..., scores: MetricScores = "auto"):
    metadata = {} if scores == "auto" else {METRIC_SCORES: scores}
```

`frequency()` should remain explicit:

```python
@metric(name="frequency", scores="unreduced")
def _frequency(...) -> Metric:
    ...
```

## Effective Behavior

| Epoch config | `auto` metrics | `reduced` metrics | `unreduced` metrics |
| --- | --- | --- | --- |
| `Epochs(5)` | implicit mean | implicit mean | raw epoch scores |
| `Epochs(5, "mode")` | mode | mode | raw epoch scores |
| `Epochs(5, ["mean", "max"])` | one result per reducer | one result per reducer | one raw result |
| `Epochs(5, [])` / `--no-epochs-reducer` | raw epoch scores, current behavior | error if multiple epochs | raw epoch scores |

This preserves `--no-epochs-reducer` for existing metrics, because existing
metrics are `auto`.

## Result Computation Shape

The core change should be in `eval_results()` / `compute_eval_scores()`.

Instead of choosing one reducer per scorer, build score views and run only the
metrics assigned to each view:

```python
@dataclass(frozen=True)
class ScoreViewKey:
    kind: Literal["reduced", "unreduced"]
    reducer_name: str | None
```

Pseudo-flow:

```python
unreduced_scores = resolved_scores

reduced_views = []
if reducers is None:
    reduced_views = [(None, reduce_scores(resolved_scores, mean_score()))]
elif reducers == []:
    reduced_views = []
else:
    reduced_views = [
        (reducer_log_name(reducer), reduce_scores(resolved_scores, reducer))
        for reducer in reducers
    ]

# auto metrics use unreduced only when reducers == []
# explicit unreduced metrics always use unreduced
# explicit reduced metrics require a reduced view
```

The risky implementation detail is result shape. If reduced and unreduced
metrics are mixed, they may have different `scored_samples` counts, so they
should not be placed in the same `EvalScore` row unless we decide those counts
are no longer precise. Safer: partition metrics by score view and emit separate
`EvalScore` rows.

To avoid duplicate row ambiguity for default implicit mean plus unreduced
metrics, mixed-view results label the implicit reduced row with reducer `"mean"`
and leave the unreduced row with no reducer. Downstream dataframe extraction can
then disambiguate rows without changing the old unlabeled default row when all
metrics use the same reduced view.

## Compatibility Risks To Guard

1. Do not record `"reduced"` metadata for old metrics by default.
2. Preserve `--no-epochs-reducer` for `auto` metrics.
3. Recompute from old logs must treat missing metric metadata as `auto`.
4. Dict-valued metric handling must still preserve scorer/key expansion.
5. Multiple reducers should not duplicate unreduced metric rows.
6. `EvalScore.scored_samples` should remain meaningful when mixed views are
   emitted.

## Tests To Add

1. `Epochs(2)` with `metrics=[accuracy(), frequency()]`: accuracy uses reduced
   sample scores; frequency uses all epoch scores.
2. `Epochs(2, "mode")` with `frequency()`: frequency still uses unreduced epoch
   scores.
3. `Epochs(2, ["mean", "max"])` with `accuracy()` and `frequency()`: accuracy
   appears for each reducer; frequency appears once.
4. `Epochs(2, [])` with existing/auto `accuracy()`: preserves current unreduced
   behavior.
5. Explicit `@metric(scores="reduced")` with `Epochs(2, [])`: errors clearly.
6. Dict scorer with `metrics={"*": [accuracy(), frequency()]}`: per-key metrics
   still compute and recompute.
7. `recompute_metrics()` from log: metric metadata round-trips through registry
   reconstruction.
8. Duplicate scorer names plus mixed score views: no phantom scorer names or
   dataframe collisions.

## Docs Needed

Update scoring docs to explain:

1. Metric score modes.
2. Default vs explicit reducers.
3. `--no-epochs-reducer` compatibility behavior.
4. `frequency()` denominator: scored observations; with unreduced epochs, this
   means sample-epoch observations.
