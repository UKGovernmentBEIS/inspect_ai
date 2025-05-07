import hashlib
import uuid
from typing import Any, cast

import shortuuid
from pydantic import BaseModel, JsonValue

from inspect_ai._util.json import jsonable_python
from inspect_ai._util.path import native_path
from inspect_ai.log._log import EvalLog, EvalSample, EvalSampleSummary


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


def model_to_record(model: BaseModel) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], jsonable_python(model))


def eval_log_location(log: EvalLog) -> str:
    return native_path(log.location)


def score_values(x: JsonValue) -> dict[str, JsonValue]:
    scores = cast(dict[str, Any], x)
    return {k: v["value"] for k, v in scores.items()}


def input_as_str(x: JsonValue) -> str:
    if isinstance(x, str):
        return x
    else:
        return messages_as_str(x)


def messages_as_str(x: JsonValue) -> str:
    if isinstance(x, list):
        messages = cast(list[dict[str, Any]], x)
        return "\n\n".join([message_as_str(message) for message in messages])
    else:
        raise ValueError(f"Unexpected type for messages: {type(x)}")


def message_as_str(message: dict[str, Any]) -> str:
    return f"{message['role']}:\n{content_as_str(message['content'])}"


def content_as_str(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content
    else:
        return "\n".join([c["text"] if c["type"] == "text" else "" for c in content])


def auto_sample_id(eval_id: str, sample: EvalSample | EvalSampleSummary) -> str:
    return auto_id(eval_id, f"{sample.id}_{sample.epoch}")


def auto_detail_id(sample_id: str, name: str, index: int) -> str:
    return auto_id(sample_id, f"{name}_{index}")


def auto_id(base: str, index: str) -> str:
    seed = f"{base}_{index}"
    hash_bytes = hashlib.md5(seed.encode("utf-8")).digest()
    long_uuid = uuid.UUID(bytes=hash_bytes)
    return shortuuid.encode(long_uuid)
