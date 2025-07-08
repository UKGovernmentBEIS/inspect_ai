import fnmatch
import inspect
import logging
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Tuple, TypeGuard, cast, get_args, get_origin, get_type_hints

import numpy as np

from inspect_ai._util.logger import warn_once
from inspect_ai._util.registry import (
    registry_info,
    registry_log_name,
    registry_params,
    registry_unqualified_name,
)
from inspect_ai.log import (
    EvalMetric,
    EvalResults,
    EvalSampleScore,
    EvalScore,
)
from inspect_ai.log._log import EvalSampleReductions
from inspect_ai.scorer import Metric, Score, Scorer
from inspect_ai.scorer._metric import (
    MetricDeprecated,
    MetricProtocol,
    SampleScore,
    Value,
)
from inspect_ai.scorer._metrics.accuracy import accuracy
from inspect_ai.scorer._metrics.std import stderr
from inspect_ai.scorer._reducer import ScoreReducer, mean_score, reducer_log_name
from inspect_ai.scorer._scorer import (
    SCORER_METRICS,
    scorer_metrics,
    unique_scorer_name,
)

logger = logging.getLogger(__name__)


@dataclass
class ScorerInfo:
    name: str
    metrics: list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]]
    params: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_scorer(scorer: Scorer) -> "ScorerInfo":
        name = registry_unqualified_name(scorer)
        metrics = scorer_metrics(scorer)
        metadata = deepcopy(registry_info(scorer).metadata)
        del metadata[SCORER_METRICS]
        params = registry_params(scorer)
        return ScorerInfo(name=name, metrics=metrics, params=params, metadata=metadata)

    @staticmethod
    def from_name(name: str) -> "ScorerInfo":
        return ScorerInfo(name=name, metrics=[accuracy(), stderr()])


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

    # extract scorers info from scorers then create scorers info for any
    # scores not already accounted for by a scorer name
    scorers_info = [ScorerInfo.from_scorer(scorer) for scorer in (scorers or [])]
    scorer_names = {info.name for info in scorers_info}
    for sample_scores in scores:
        for name, sample_score in sample_scores.items():
            if sample_score.scorer is None and name not in scorer_names:
                scorers_info.append(ScorerInfo.from_name(name))
                scorer_names.add(name)

    # record scorer
    if len(scorers_info) > 0:
        result_scores: list[EvalScore] = []
        sample_reductions: list[EvalSampleReductions] = []
        for scorer_info in scorers_info:
            # this scorer
            scorer_name = unique_scorer_name(
                scorer_info.name, [eval_score.name for eval_score in result_scores]
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
                    samples=[
                        EvalSampleScore(**ss.score.__dict__, sample_id=ss.sample_id)
                        for ss in reduced_scores
                    ],
                )
                sample_reductions.append(reduced_samples)

                # Compute metrics for this scorer
                targets = metrics if metrics is not None else scorer_info.metrics
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
                            scorer_info=scorer_info,
                            sample_scores=reduced_scores,
                            metrics=simple_metrics,
                            reducer_name=reducer_display_nm,
                        )
                    )
                    for dict_metric in dict_metrics:
                        result_scores.extend(
                            scorers_from_metric_dict(
                                scorer_name=scorer_name,
                                scorer_info=scorer_info,
                                sample_scores=reduced_scores,
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
                            scorer_info=scorer_info,
                            sample_scores=reduced_scores,
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
    scorer_info: ScorerInfo,
    sample_scores: list[SampleScore],
    metrics: list[Metric],
    reducer_name: str | None = None,
) -> list[EvalScore]:
    results: list[EvalScore] = []

    ## filter the sample_scores to exclude Nan values, which will not be scored
    ## unscored_samples to note the number of samples that were not scored
    sample_scores_with_values = []
    for sample_score in sample_scores:
        if not isinstance(sample_score.score.value, float) or not np.isnan(
            sample_score.score.value
        ):
            sample_scores_with_values.append(sample_score)

    unscored_samples = len(sample_scores) - len(sample_scores_with_values)
    scored_samples = len(sample_scores_with_values)

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
        params = registry_params(metric)
        # process metric values
        if len(sample_scores_with_values) > 0:
            metric_value = call_metric(metric, sample_scores_with_values)
        else:
            metric_value = float("Nan")
        base_metric_name = registry_log_name(metric)

        # If the metric value is a dictionary, turn each of the entries
        # in the dictionary into a result
        if isinstance(metric_value, Mapping):
            for metric_key, value in metric_value.items():
                if value is not None:
                    name = metrics_unique_key(metric_key, list(list_metrics.keys()))
                    list_metrics[name] = EvalMetric(
                        name=name, value=float(value), params=params
                    )

        # If the metric value is a list, turn each element in the list
        # into a result
        elif isinstance(metric_value, Sequence):
            for index, value in enumerate(metric_value):
                if value is not None:
                    count = str(index + 1)
                    name = metrics_unique_key(
                        with_suffix(key, count), list(list_metrics.keys())
                    )

                    list_metrics[name] = EvalMetric(
                        name=name, value=float(value), params=params
                    )

        # the metric is a float, str, or int
        else:
            list_metrics[key] = EvalMetric(
                name=base_metric_name, value=float(metric_value), params=params
            )

    # build results
    results.append(
        EvalScore(
            scorer=scorer_name,
            reducer=reducer_name,
            name=scorer_name,
            params=scorer_info.params,
            metadata=scorer_info.metadata
            if len(scorer_info.metadata.keys()) > 0
            else None,
            metrics=list_metrics,
            scored_samples=scored_samples,
            unscored_samples=unscored_samples,
        )
    )
    return results


def scorers_from_metric_dict(
    scorer_name: str,
    scorer_info: ScorerInfo,
    sample_scores: list[SampleScore],
    metrics: dict[str, list[Metric]],
    reducer_name: str | None = None,
) -> list[EvalScore]:
    results: list[EvalScore] = []

    # Expand any metric keys
    resolved_metrics = (
        resolve_glob_metric_keys(metrics, sample_scores[0].score)
        if len(sample_scores) > 0
        else metrics
    )

    for metric_key, metric_list in resolved_metrics.items():
        # filter scores to a list of scalars with the value of the metric name
        metric_scores: list[SampleScore] = []

        ## filter the sample_scores to exclude Nan values, which will not be scored
        ## unscored_samples to note the number of samples that were not scored
        unscored_samples = 0
        scored_samples = 0

        for sample_score in sample_scores:
            if isinstance(sample_score.score.value, dict):
                if metric_key in sample_score.score.value:
                    # Convert the score into a simple scalar value to apply metrics
                    metric_score = deepcopy(sample_score)
                    metric_score.score.value = cast(
                        float, sample_score.score.value[metric_key]
                    )
                    if isinstance(metric_score.score.value, float) and np.isnan(
                        metric_score.score.value
                    ):
                        unscored_samples += 1
                    else:
                        scored_samples += 1
                        metric_scores.append(metric_score)
                else:
                    raise TypeError(
                        f"key '{metric_key}' isn't present in the score value dictionary"
                    )
            else:
                raise TypeError(
                    "A dictionary of metrics specified for a non-dictionary score"
                )

        result_metrics: dict[str, EvalMetric] = {}
        for target_metric in metric_list:
            # compute the metric value
            metric_name = registry_log_name(target_metric)
            metric_params = registry_params(target_metric)
            if len(metric_scores) > 0:
                value = call_metric(target_metric, metric_scores)
            else:
                value = float("Nan")

            # convert the value to a float (either by expanding the dict or array)
            # or by casting to a float
            if isinstance(value, dict):
                for key, val in value.items():
                    name = f"{metric_name}_{key}"
                    result_metrics[name] = EvalMetric(
                        name=name, value=cast(float, val), params=metric_params
                    )
            elif isinstance(value, list):
                for idx, item in enumerate(value):
                    name = f"{metric_name}_{idx}"
                    result_metrics[name] = EvalMetric(
                        name=name, value=cast(float, item), params=metric_params
                    )
            else:
                result_metrics[metric_name] = EvalMetric(
                    name=metric_name, value=cast(float, value), params=metric_params
                )

        # create a scorer result for this metric
        # TODO: What if there is separate simple scorer which has a name collision with
        # a score created by this scorer
        results.append(
            EvalScore(
                scorer=scorer_name,
                reducer=reducer_name,
                name=metric_key,
                params=scorer_info.params,
                metadata=scorer_info.metadata
                if len(scorer_info.metadata.keys()) > 0
                else None,
                metrics=result_metrics,
                scored_samples=scored_samples,
                unscored_samples=unscored_samples,
            )
        )
    return results


def call_metric(metric: Metric, sample_scores: list[SampleScore]) -> Value:
    if is_metric_deprecated(metric):
        warn_once(
            logger,
            f"Metric {registry_log_name(metric)} should be updated to take list[SampleScore]. "
            f"Metrics with list[Score] are deprecated.",
        )
        scores = [sample_score.score for sample_score in sample_scores]
        return metric(scores)
    else:
        metric = cast(MetricProtocol, metric)
        return metric(sample_scores)


def is_metric_deprecated(metric: Metric) -> TypeGuard[MetricDeprecated]:
    """Type guard to check if a metric follows the deprecated signature."""
    try:
        # signature and params
        sig = inspect.signature(metric)
        param_types = get_type_hints(metric)

        # there should be only one param, check it
        first_param = next(iter(sig.parameters.values()), None)
        if first_param is None:
            # No parameters, who knows what this is, treat it as deprecated
            return True

        expected_type: Any = param_types.get(first_param.name, None)

        if expected_type is None or expected_type is Any:
            # no helpful type info, treat it as deprecated
            return True

        # Extract generic base type and arguments to check if it matches list[Score]
        origin = get_origin(expected_type)
        args = get_args(expected_type)

        return origin is list and args == (Score,)
    except (AttributeError, ValueError, TypeError):
        return False


def resolve_glob_metric_keys(
    metrics: dict[str, list[Metric]], base_score: Score
) -> dict[str, list[Metric]]:
    if not isinstance(base_score.value, dict):
        # this value isn't a dictionary (unexpected)
        raise TypeError(
            "A dictionary of metrics was specified for a non-dictionary score. Dictionaries of metrics are only valid when the score value is a dictionary."
        )

    # Expand any metric keys
    resolved_metrics: dict[str, list[Metric]] = {}

    # the value is a dictionary, so go through the dictionary
    # and expand any metric globs into their literal values
    # and apply matching metrics to those keys
    for metric_key, metric_list in metrics.items():
        # compile the key as a glob into a regex and use that to match keys
        key_glob_re = re.compile(fnmatch.translate(metric_key))

        for score_key in base_score.value.keys():
            if key_glob_re.match(score_key):
                # The key matched, so either create a new entry for it and add metrics
                # or add metrics to the existing key
                resolved_metrics.setdefault(score_key, [])
                existing_metric_names = {
                    registry_log_name(m) for m in resolved_metrics[score_key]
                }

                # Add metrics that aren't already in the list
                for metric in metric_list:
                    metric_name = registry_log_name(metric)
                    if metric_name not in existing_metric_names:
                        resolved_metrics[score_key].append(metric)
                        existing_metric_names.add(metric_name)
    return resolved_metrics


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
        reduced = reducer([score.score for score in scores])
        reduced_scores.append(
            SampleScore(
                sample_id=scores[0].sample_id,
                sample_metadata=scores[0].sample_metadata,
                score=reduced,
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
