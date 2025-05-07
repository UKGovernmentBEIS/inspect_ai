from typing import Callable

from jsonpath_ng import JSONPath  # type: ignore
from pydantic import JsonValue

from inspect_ai.log._log import EvalSample, EvalSampleSummary


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
