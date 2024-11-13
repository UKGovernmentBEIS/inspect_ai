from datetime import datetime
from typing import Sequence, Set

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from inspect_ai.log import EvalStats
from inspect_ai.log._log import rich_traceback

from .config import task_config, task_dict
from .display import (
    TaskCancelled,
    TaskError,
    TaskProfile,
    TaskSuccess,
    TaskWithResult,
)
from .panel import task_panel
from .rich import rich_theme


def tasks_results(tasks: Sequence[TaskWithResult]) -> RenderableType:
    def render_task(task: TaskWithResult) -> RenderableType:
        if isinstance(task.result, TaskCancelled):
            return task_result_cancelled(task.profile, task.result)
        elif isinstance(task.result, TaskError):
            return task_result_error(task.profile, task.result)
        elif isinstance(task.result, TaskSuccess):
            return task_result_summary(task.profile, task.result)
        else:
            return ""

    return Group(*[render_task(task) for task in tasks])


def task_result_cancelled(
    profile: TaskProfile, cancelled: TaskCancelled
) -> RenderableType:
    return task_panel(
        profile=profile,
        show_model=True,
        body=task_stats(profile, cancelled.stats),
        footer=task_interrupted(profile, cancelled.samples_completed),
        log_location=profile.log_location,
    )


def task_results(profile: TaskProfile, success: TaskSuccess) -> RenderableType:
    theme = rich_theme()

    # do we have more than one scorer name?
    results = success.results
    scorer_names: Set[str] = {score.name for score in results.scores}
    reducer_names: Set[str] = {
        score.reducer for score in results.scores if score.reducer is not None
    }
    show_reducer = len(reducer_names) > 1 or "avg" not in reducer_names
    output: dict[str, str] = {}
    for score in results.scores:
        for name, metric in score.metrics.items():
            value = (
                "1.0"
                if metric.value == 1
                else (
                    str(metric.value)
                    if isinstance(metric.value, int)
                    else f"{metric.value:.3g}"
                )
            )
            name = (
                rf"{name}\[{score.reducer}]"
                if show_reducer and score.reducer is not None
                else name
            )
            key = f"{score.name}/{name}" if (len(scorer_names) > 1) else name
            output[key] = value

    if output:
        message = f"[{theme.metric}]{task_dict(output, True)}[/{theme.metric}]"
    else:
        message = ""

    # note if some of our samples had errors
    if success.samples_completed < profile.samples:
        sample_errors = profile.samples - success.samples_completed
        sample_error_pct = int(float(sample_errors) / float(profile.samples) * 100)
        if message:
            message = f"{message}\n\n"
        message = f"{message}[{theme.warning}]WARNING: {sample_errors} of {profile.samples} samples ({sample_error_pct}%) had errors and were not scored.[/{theme.warning}]"

    return message


def task_result_summary(profile: TaskProfile, success: TaskSuccess) -> RenderableType:
    return task_panel(
        profile=profile,
        show_model=True,
        body=task_stats(profile, success.stats),
        footer=task_results(profile, success),
        log_location=profile.log_location,
    )


def task_result_error(profile: TaskProfile, error: TaskError) -> RenderableType:
    return task_panel(
        profile=profile,
        show_model=True,
        body=rich_traceback(error.exc_type, error.exc_value, error.traceback),
        footer=task_interrupted(profile, error.samples_completed),
        log_location=profile.log_location,
    )


def task_stats(profile: TaskProfile, stats: EvalStats) -> RenderableType:
    theme = rich_theme()
    panel = Table.grid(expand=True)
    panel.add_column()
    config = task_config(profile)
    if config:
        panel.add_row(config)
        panel.add_row()
    elif len(stats.model_usage) < 2:
        panel.add_row()

    table = Table.grid(expand=True)
    table.add_column(style="bold")
    table.add_column()

    # eval time
    started = datetime.fromisoformat(stats.started_at)
    completed = datetime.fromisoformat(stats.completed_at)
    elapsed = completed - started
    table.add_row(Text("total time:", style="bold"), f"  {elapsed}", style=theme.light)

    # token usage
    for model, usage in stats.model_usage.items():
        if (
            usage.input_tokens_cache_read is not None
            or usage.input_tokens_cache_write is not None
        ):
            input_tokens_cache_read = usage.input_tokens_cache_read or 0
            input_tokens_cache_write = usage.input_tokens_cache_write or 0
            input_tokens = f"[bold]I: [/bold]{usage.input_tokens:,}, [bold]CW: [/bold]{input_tokens_cache_write:,}, [bold]CR: [/bold]{input_tokens_cache_read:,}"
        else:
            input_tokens = f"[bold]I: [/bold]{usage.input_tokens:,}"

        table.add_row(
            Text(model, style="bold"),
            f"  {usage.total_tokens:,} tokens [{input_tokens}, [bold]O: [/bold]{usage.output_tokens:,}]",
            style=theme.light,
        )

    panel.add_row(table)
    return panel


def task_can_retry(profile: TaskProfile) -> bool:
    return profile.file is not None or "/" in profile.name


def task_interrupted(profile: TaskProfile, samples_completed: int) -> RenderableType:
    log_location = profile.log_location
    theme = rich_theme()
    message = f"[bold][{theme.error}]Task interrupted ("
    if samples_completed > 0:
        message = f"{message}{samples_completed:,} of {profile.samples:,} total samples logged before interruption)."
        if task_can_retry(profile):
            message = (
                f"{message} Resume task with:[/{theme.error}][/bold]\n\n"
                + f"[bold][{theme.light}]inspect eval-retry {log_location}[/{theme.light}][/bold]"
            )
        else:
            message = f"{message}[/{theme.error}][/bold]"
    else:
        message = (
            f"{message}no samples completed before interruption)[/{theme.error}][/bold]"
        )

    return message
