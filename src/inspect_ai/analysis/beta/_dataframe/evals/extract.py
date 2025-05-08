from inspect_ai._util.path import native_path
from inspect_ai.log._log import EvalLog


def eval_log_location(log: EvalLog) -> str:
    return native_path(log.location)


def eval_log_scores_dict(
    log: EvalLog,
) -> list[dict[str, dict[str, int | float]]] | None:
    if log.results is not None:
        metrics = [
            {
                score.name: {
                    metric.name: metric.value for metric in score.metrics.values()
                }
            }
            for score in log.results.scores
        ]
        return metrics
    else:
        return None
