from typing import cast

from pydantic import JsonValue

from inspect_ai._util.json import jsonable_python
from inspect_ai._util.path import native_path
from inspect_ai.log._log import EvalLog


def scores_dict(log: EvalLog) -> JsonValue:
    if log.results is not None:
        metrics: JsonValue = [
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


def list_as_str(x: JsonValue) -> str:
    return ",".join([str(e) for e in (x if isinstance(x, list) else [x])])


def log_to_record(log: EvalLog) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], jsonable_python(log))


def eval_log_location(log: EvalLog) -> str:
    return native_path(log.location)
