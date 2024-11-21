from rich.console import RenderableType
from rich.text import Text

from inspect_ai._util.logger import http_rate_limit_count
from inspect_ai._util.throttle import throttle
from inspect_ai.util._concurrency import concurrency_status

from .config import task_dict


@throttle(1)
def task_footer(style: str = "") -> tuple[RenderableType, RenderableType]:
    return (
        Text.from_markup(task_resources(), style=style),
        Text.from_markup(task_http_rate_limits(), style=style),
    )


def task_resources() -> str:
    resources: dict[str, str] = {}
    for model, resource in concurrency_status().items():
        resources[model] = f"{resource[0]}/{resource[1]}"
    return task_dict(resources)


def task_http_rate_limits() -> str:
    return f"HTTP rate limits: {http_rate_limit_count():,}"
