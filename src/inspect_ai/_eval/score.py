import asyncio
import re
from copy import deepcopy
from typing import Callable, cast

from inspect_ai._display import display
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import (
    registry_create,
    registry_info,
    registry_log_name,
    registry_params,
    registry_unqualified_name,
)
from inspect_ai.log import EvalLog, EvalMetric, EvalResults, EvalScorer
from inspect_ai.model import ModelName
from inspect_ai.scorer import Metric, Score, Scorer, Target
from inspect_ai.scorer._scorer import SCORER_METRICS, scorer_metrics
from inspect_ai.solver import TaskState


def score(log: EvalLog, scorer: Scorer) -> EvalLog:
    """Score an evaluation log.

    Args:
       log (EvalLog): Evaluation log.
       scorer (Scorer): Scorer to apply to log
       metrics: (list[Metric]): Additional metrics to compute
         (Scorer built-in metrics are always computed).

    Returns:
       Log with scores yielded by scorer.
    """
    # standard platform init for top level entry points
    platform_init()

    return asyncio.run(score_async(log, scorer))


async def score_async(log: EvalLog, scorer: Scorer) -> EvalLog:
    """Score an evaluation log.

    Args:
       log (EvalLog): Evaluation log.
       scorer (Scorer): Scorer to apply to log

    Returns:
       Log with scores yielded by scorer.
    """
    # deepcopy so we don't mutate the passed log
    log = deepcopy(log)

    # confirm we have samples
    if log.samples is None or len(log.samples) == 0:
        raise ValueError("There are no samples to score in the log.")

    # prime the scoring tasks
    states = [
        TaskState(
            model=ModelName(log.eval.model),
            sample_id=sample.id,
            epoch=sample.epoch,
            input=sample.input,
            choices=sample.choices,
            messages=sample.messages,
            output=sample.output,
            completed=True,
            metadata=sample.metadata,
        )
        for sample in log.samples
    ]
    with display().progress(total=len(states)) as p:

        def progress() -> None:
            p.update(1)

        tasks = [
            run_score_task(state, Target(sample.target), scorer, progress)
            for (sample, state) in zip(log.samples, states)
        ]

        # do scoring
        scores = await asyncio.gather(*tasks)

        # write them back (gather ensures that they come back in the same order)
        for index, score in enumerate(scores):
            log.samples[index].score = score

        # collect metrics from EvalLog (they may overlap w/ the scorer metrics,
        # that will be taken care of in eval_results)
        log_metrics = metrics_from_log(log)

        # compute metrics
        log.results = eval_results(scores, scorer, log_metrics)

    return log


async def run_score_task(
    state: TaskState,
    target: Target,
    scorer: Scorer,
    progress: Callable[..., None],
) -> Score:
    result = await scorer(state, target)
    progress()
    return result


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


def metrics_from_log(log: EvalLog) -> list[Metric]:
    return (
        [metric_from_log(metric) for metric in log.results.metrics.values()]
        if log.results
        else []
    )


def metric_from_log(metric: EvalMetric) -> Metric:
    return cast(Metric, registry_create("metric", metric.name, **metric.options))
