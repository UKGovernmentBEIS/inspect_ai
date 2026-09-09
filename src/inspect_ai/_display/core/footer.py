from rich.console import RenderableType
from rich.text import Text

from inspect_ai._util.retry import http_retries_count
from inspect_ai.log._refusal import refusal_count
from inspect_ai.model._throughput import throughput_footer_rate
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
    counters = counters | task_http_retries()
    refusals = refusal_count()
    if refusals > 0:
        counters = counters | {"Refusals": f"{refusals:,}"}

    return task_dict(counters)


def task_http_retries() -> dict[str, str]:
    counters = {"HTTP retries": f"{http_retries_count():,}"}
    # aggregate effective output rate, shown only once retries have occurred
    # this run (throughput_footer_rate returns None while the run is quiet)
    out_tok_rate = throughput_footer_rate()
    if out_tok_rate is not None:
        counters["out tok/s"] = f"{out_tok_rate:,.0f}"
    return counters


def task_http_retries_str() -> str:
    retries = f"HTTP retries: {http_retries_count():,}"
    out_tok_rate = throughput_footer_rate()
    if out_tok_rate is not None:
        retries = f"{retries}  out tok/s: {out_tok_rate:,.0f}"
    return retries


def task_refusals_str() -> str:
    refusals = refusal_count()
    if refusals > 0:
        return f"Refusals: {refusals:,}"
    else:
        return ""
