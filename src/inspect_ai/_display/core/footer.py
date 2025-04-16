from rich.console import RenderableType
from rich.text import Text

from inspect_ai._util.retry import http_retries_count
from inspect_ai.util._concurrency import concurrency_status_display
from inspect_ai.util._throttle import throttle

from .config import task_dict


@throttle(1)
def task_footer(
    counters: dict[str, str], style: str = ""
) -> tuple[RenderableType, RenderableType]:
    return (
        Text.from_markup(task_resources(), style=style),
        Text.from_markup(task_counters(counters), style=style),
    )


def task_resources() -> str:
    resources: dict[str, str] = {}
    for model, resource in concurrency_status_display().items():
        resources[model] = f"{resource[0]}/{resource[1]}"
    return task_dict(resources)


def task_counters(counters: dict[str, str]) -> str:
    return task_dict(counters | task_http_retries())


def task_http_retries() -> dict[str, str]:
    return {"HTTP retries": f"{http_retries_count():,}"}


def task_http_retries_str() -> str:
    return f"HTTP retries: {http_retries_count():,}"
