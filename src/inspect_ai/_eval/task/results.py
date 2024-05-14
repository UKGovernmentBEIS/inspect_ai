import re
from copy import deepcopy

from inspect_ai._util.registry import (
    registry_info,
    registry_log_name,
    registry_params,
    registry_unqualified_name,
)
from inspect_ai.log import (
    EvalMetric,
    EvalResults,
    EvalScorer,
)
from inspect_ai.scorer import Metric, Score, Scorer
from inspect_ai.scorer._scorer import SCORER_METRICS, scorer_metrics


def eval_results(
    scores: list[Score], scorer: Scorer | None, metrics: list[Metric] = []
) -> EvalResults:
    # record scorer
    results = EvalResults()
    if scorer:
        # extract non-metrics metadata
        metadata = deepcopy(registry_info(scorer).metadata)
        del metadata[SCORER_METRICS]

        # build results
        results.scorer = EvalScorer(
            name=registry_log_name(scorer),
            params=registry_params(scorer),
            metadata=metadata if len(metadata.keys()) > 0 else None,
        )

        # we want to use simple names for metrics in the metrics dict
        # (i.e. without package prefixes). we do this by getting the
        # unqualified name, then appending a suffix if there are duplicates
        # this keeps the code straightforward and intuitive for users
        # programming against the log (e.g. metrics["accuracy"]) vs.
        # metrics["pkgname/accuracy"])
        for metric in target_metrics(scorer, metrics):
            key = metrics_unique_key(
                registry_unqualified_name(metric), list(results.metrics.keys())
            )
            results.metrics[key] = EvalMetric(
                name=registry_log_name(metric), value=metric(scores)
            )
    return results


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


# build a list of metrics (scorer built-in metrics + de-duplicated additional metrics)
def target_metrics(scorer: Scorer, metrics: list[Metric]) -> list[Metric]:
    target_metrics = scorer_metrics(scorer)
    target_metrics_names = [registry_log_name(metric) for metric in target_metrics]
    target_metrics.extend(
        [
            metric
            for metric in metrics
            if registry_log_name(metric) not in target_metrics_names
        ]
    )
    return target_metrics
