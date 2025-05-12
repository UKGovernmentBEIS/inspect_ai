from typing import Callable

from jsonpath_ng import JSONPath  # type: ignore
from pydantic import JsonValue

from inspect_ai.log._log import EvalSample, EvalSampleSummary

from ..extract import auto_id, messages_as_str


def sample_input_as_str(sample: EvalSample) -> str:
    return messages_as_str(sample.input)


def sample_messages_as_str(sample: EvalSample) -> str:
    return messages_as_str(sample.messages)


def sample_path_requires_full(
    path: str
    | JSONPath
    | Callable[[EvalSampleSummary], JsonValue]
    | Callable[[EvalSample], JsonValue],
) -> bool:
    if callable(path):
        return False
    else:
        path = str(path)
        return any(
            [
                path.startswith(prefix)
                for prefix in [
                    "choices",
                    "sandbox",
                    "files",
                    "setup",
                    "messages",
                    "output",
                    "store",
                    "events",
                    "uuid",
                    "error_retries",
                    "attachments",
                ]
            ]
        )


def auto_sample_id(eval_id: str, sample: EvalSample | EvalSampleSummary) -> str:
    return auto_id(eval_id, f"{sample.id}_{sample.epoch}")


def auto_detail_id(sample_id: str, name: str, index: int) -> str:
    return auto_id(sample_id, f"{name}_{index}")
