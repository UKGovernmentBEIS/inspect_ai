import re
from collections import defaultdict
from copy import deepcopy
from typing import Any, Tuple, cast

from inspect_ai._util.registry import (
    registry_info,
    registry_log_name,
    registry_params,
    registry_unqualified_name,
)
from inspect_ai.log import (
    EvalMetric,
    EvalResults,
    EvalScore,
)
from inspect_ai.log._log import EvalSampleReductions
from inspect_ai.scorer import Metric, Score, Scorer
from inspect_ai.scorer._metric import SampleScore
from inspect_ai.scorer._reducer import ScoreReducer, mean_score, reducer_log_name
from inspect_ai.scorer._scorer import (
    SCORER_METRICS,
    scorer_metrics,
    unique_scorer_name,
)


def eval_results(
    samples: int,
    scores: list[dict[str, SampleScore]],
    reducers: ScoreReducer | list[ScoreReducer] | None,
    scorers: list[Scorer] | None,
    metrics: list[Metric] | dict[str, list[Metric]] | None,
) -> Tuple[EvalResults, list[EvalSampleReductions] | None]:
    # initialise results
    results = EvalResults(total_samples=samples, completed_samples=len(scores))
    reductions = None

    # record scorer
    if scorers:
        result_scores: list[EvalScore] = []
        sample_reductions: list[EvalSampleReductions] = []
        for scorer in scorers:
            # extract non-metrics metadata
            metadata = deepcopy(registry_info(scorer).metadata)
            del metadata[SCORER_METRICS]

            # this scorer
            scorer_name = unique_scorer_name(
                scorer, [eval_score.name for eval_score in result_scores]
            )

            # scores for this scorer
            resolved_scores = [
                score[scorer_name] for score in scores if scorer_name in score
            ]

            # Group the scores by sample_id
            reducers, use_reducer_name = resolve_reducer(reducers)
            for reducer in reducers:
                reducer_display_nm = (
                    reducer_log_name(reducer) if use_reducer_name else None
                )
                reduced_scores = reduce_scores(resolved_scores, reducer=reducer)

                # record this scorer's intermediate results
                reduced_samples = EvalSampleReductions(
                    scorer=scorer_name,
                    reducer=reducer_display_nm,
                    samples=reduced_scores,
                )
                sample_reductions.append(reduced_samples)

                # Compute metrics for this scorer
                simple_scores = cast(list[Score], reduced_scores)
                targets = metrics if metrics is not None else scorer_metrics(scorer)
                if isinstance(targets, list):
                    ## split the metrics into the simple metrics and any dictionary
                    ## metrics, to be processed independently
                    simple_metrics, dict_metrics = split_metrics(
                        cast(list[Metric | dict[str, list[Metric]]], targets)
                    )

                    # If there is a simple list of metrics
                    # just compute the metrics for this scorer
                    result_scores.extend(
                        scorer_for_metrics(
                            scorer_name=scorer_name,
                            scorer=scorer,
                            metadata=metadata,
                            scores=simple_scores,
                            metrics=simple_metrics,
                            reducer_name=reducer_display_nm,
                        )
                    )
                    for dict_metric in dict_metrics:
                        result_scores.extend(
                            scorers_from_metric_dict(
                                scorer_name=scorer_name,
                                scorer=scorer,
                                metadata=metadata,
                                scores=simple_scores,
                                metrics=dict_metric,
                                reducer_name=reducer_display_nm,
                            )
                        )
                else:
                    # If there is a dictionary of metrics, apply
                    # the metrics to the values within the scores
                    # (corresponding by key) and emit an EvalScorer for
                    # each key (which effectively creates multiple scorers
                    # by expanding a dictionary score value into multiple
                    # results with metrics)
                    result_scores.extend(
                        scorers_from_metric_dict(
                            scorer_name=scorer_name,
                            scorer=scorer,
                            metadata=metadata,
                            scores=simple_scores,
                            metrics=targets,
                            reducer_name=reducer_display_nm,
                        )
                    )
            # build results
        results.scores = result_scores
        reductions = sample_reductions

    return results, reductions


def resolve_reducer(
    reducers: ScoreReducer | list[ScoreReducer] | None,
) -> tuple[list[ScoreReducer], bool]:
    if reducers is None:
        return ([mean_score()], False)
    else:
        return (reducers if isinstance(reducers, list) else [reducers], True)


def split_metrics(
    metrics: list[Metric | dict[str, list[Metric]]],
) -> tuple[list[Metric], list[dict[str, list[Metric]]]]:
    metric_list: list[Metric] = []
    dict_list: list[dict[str, list[Metric]]] = []

    for metric in metrics:
        if isinstance(metric, Metric):
            metric_list.append(metric)
        elif isinstance(metric, dict):
            dict_list.append(metric)

    return metric_list, dict_list


def scorer_for_metrics(
    scorer_name: str,
    scorer: Scorer,
    metadata: dict[str, Any],
    scores: list[Score],
    metrics: list[Metric],
    reducer_name: str | None = None,
) -> list[EvalScore]:
    results: list[EvalScore] = []
    # we want to use simple names for metrics in the metrics dict
    # (i.e. without package prefixes). we do this by getting the
    # unqualified name, then appending a suffix if there are duplicates
    # this keeps the code straightforward and intuitive for users
    # programming against the log (e.g. metrics["accuracy"]) vs.
    # metrics["pkgname/accuracy"])
    list_metrics: dict[str, EvalMetric] = {}
    for metric in metrics:
        key = metrics_unique_key(
            registry_unqualified_name(metric), list(list_metrics.keys())
        )

        # process metric values
        metric_value = metric(scores)
        base_metric_name = registry_log_name(metric)

        # If the metric value is a dictionary, turn each of the entries
        # in the dictionary into a result
        if isinstance(metric_value, dict):
            for metric_key, value in metric_value.items():
                if value is not None:
                    name = metrics_unique_key(metric_key, list(list_metrics.keys()))
                    list_metrics[name] = EvalMetric(
                        name=name,
                        value=float(value),
                    )

        # If the metric value is a list, turn each element in the list
        # into a result
        elif isinstance(metric_value, list):
            for index, value in enumerate(metric_value):
                if value is not None:
                    count = str(index + 1)
                    name = metrics_unique_key(
                        with_suffix(key, count), list(list_metrics.keys())
                    )

                    list_metrics[name] = EvalMetric(name=name, value=float(value))

        # the metric is a float, str, or int
        else:
            list_metrics[key] = EvalMetric(
                name=base_metric_name,
                value=float(metric_value),
            )

    # build results
    results.append(
        EvalScore(
            scorer=scorer_name,
            reducer=reducer_name,
            name=scorer_name,
            params=registry_params(scorer),
            metadata=metadata if len(metadata.keys()) > 0 else None,
            metrics=list_metrics,
        )
    )
    return results


def scorers_from_metric_dict(
    scorer_name: str,
    scorer: Scorer,
    metadata: dict[str, Any],
    scores: list[Score],
    metrics: dict[str, list[Metric]],
    reducer_name: str | None = None,
) -> list[EvalScore]:
    results: list[EvalScore] = []
    for metric_key, metric_list in metrics.items():
        # filter scores to a list of scalars with the value of the metric name
        metric_scores: list[Score] = []
        for score in scores:
            if isinstance(score.value, dict):
                if metric_key in score.value:
                    # Convert the score into a simple scalar value to apply metrics
                    metric_score = deepcopy(score)
                    metric_score.value = cast(float, score.value[metric_key])
                    metric_scores.append(metric_score)
                else:
                    raise TypeError(
                        f"key '{metric_key}' isn't present in the score value dictionary"
                    )
            else:
                raise TypeError(
                    "dictionary of metrics specific for a non-dictionary score"
                )

        result_metrics: dict[str, EvalMetric] = {}
        for target_metric in metric_list:
            # compute the metric value
            metric_name = registry_log_name(target_metric)
            result_metrics[metric_name] = EvalMetric(
                name=metric_name,
                value=cast(float, target_metric(metric_scores)),
            )

        # create a scorer result for this metric
        # TODO: What if there is separate simple scorer which has a name collision with
        # a score created by this scorer
        results.append(
            EvalScore(
                scorer=scorer_name,
                reducer=reducer_name,
                name=metric_key,
                params=registry_params(scorer),
                metadata=metadata if len(metadata.keys()) > 0 else None,
                metrics=result_metrics,
            )
        )
    return results


def reduce_scores(
    scores: list[SampleScore], reducer: ScoreReducer
) -> list[SampleScore]:
    # Group the scores by sample_id
    grouped_scores: dict[str, list[SampleScore]] = defaultdict(list)
    for sample_score in scores:
        if sample_score.sample_id is not None:
            grouped_scores[str(sample_score.sample_id)].append(sample_score)

    # reduce the scores
    reduced_scores: list[SampleScore] = []
    for scores in grouped_scores.values():
        reduced = reducer(cast(list[Score], scores))
        reduced_scores.append(
            SampleScore(
                sample_id=scores[0].sample_id,
                value=reduced.value,
                answer=reduced.answer,
                explanation=reduced.explanation,
                metadata=reduced.metadata,
            )
        )

    return reduced_scores


def metrics_unique_key(key: str, existing: list[str]) -> str:
    if key not in existing:
        return key
    else:
        key_index = 2
        pattern = re.compile(f"{re.escape(key)}(\\d+)")
        for existing_key in existing:
            match = pattern.match(existing_key)
            index = int(match.group(1)) if match else None
            if index and (index >= key_index):
                key_index = index + 1
        return f"{key}{key_index}"


def with_suffix(prefix: str, suffix: str) -> str:
    return prefix + "-" + suffix
