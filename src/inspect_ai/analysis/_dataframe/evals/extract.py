from typing import cast

from inspect_ai._util.path import native_path
from inspect_ai.log._headline import headline_metric
from inspect_ai.log._log import EvalLog

from ..extract import remove_namespace


def eval_log_location(log: EvalLog) -> str:
    return native_path(log.location)


def eval_log_task_display_name(log: EvalLog) -> str:
    if log.eval.task_display_name is not None:
        return log.eval.task_display_name
    else:
        return cast(str, remove_namespace(log.eval.task))


def eval_log_scores_dict(
    log: EvalLog,
) -> list[dict[str, dict[str, int | float]]] | None:
    if log.results is not None:
        # Only disambiguate by reducer when the base score column would collide
        # (e.g. epochs_reducer=["mean","max"] with the same metric key).
        # Mixed reduced/unreduced views often have different metric keys, so keep
        # the existing `score_<name>_<metric>` column names for those cases.
        column_counts: dict[tuple[str, str], int] = {}
        for score in log.results.scores:
            for metric_key in score.metrics.keys():
                column_key = (score.name, metric_key)
                column_counts[column_key] = column_counts.get(column_key, 0) + 1

        metrics: list[dict[str, dict[str, int | float]]] = []
        for score in log.results.scores:
            score_metrics: dict[str, dict[str, int | float]] = {}
            for metric_key, metric in score.metrics.items():
                score_key = (
                    f"{score.name}_{score.reducer}"
                    if column_counts[(score.name, metric_key)] > 1
                    and score.reducer is not None
                    else score.name
                )
                score_metrics.setdefault(score_key, {})[metric_key] = metric.value
            metrics.append(score_metrics)
        return metrics
    else:
        return None


def eval_log_headline_name(log: EvalLog) -> str | None:
    # the scorer, not the score: this column has always named the scorer, and
    # the two differ for scorers returning a dict of scores. `headline_score`
    # carries the score, which is what tells those apart
    resolved = headline_metric(log)
    return resolved.score.scorer if resolved is not None else None


def eval_log_headline_score(log: EvalLog) -> str | None:
    resolved = headline_metric(log)
    return resolved.score.name if resolved is not None else None


def eval_log_headline_metric(log: EvalLog) -> str | None:
    resolved = headline_metric(log)
    return resolved.name if resolved is not None else None


def eval_log_headline_value(log: EvalLog) -> int | float | None:
    resolved = headline_metric(log)
    return resolved.metric.value if resolved is not None else None


def eval_log_headline_stderr(log: EvalLog) -> float | None:
    resolved = headline_metric(log)
    if resolved is not None:
        stderr = resolved.score.metrics.get("stderr")
        if stderr is not None:
            return float(stderr.value)

    return None
