from datetime import datetime
from typing import Sequence, Set

import numpy as np
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from inspect_ai.log import EvalStats
from inspect_ai.log._log import EvalScore, rich_traceback

from .config import task_config, task_dict
from .display import (
    TaskCancelled,
    TaskDisplayMetric,
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
    # The contents of the panel
    config = task_config(profile)
    body = task_stats(cancelled.stats)

    # The panel
    return task_panel(
        profile=profile,
        show_model=True,
        body=body,
        subtitle=config,
        footer=task_interrupted(profile, cancelled.samples_completed),
        log_location=profile.log_location,
    )


def task_results(profile: TaskProfile, success: TaskSuccess) -> RenderableType:
    theme = rich_theme()

    grid = Table.grid(expand=True)
    grid.add_column()

    if success.results.scores:
        for row in task_scores(success.results.scores):
            grid.add_row(row)

    # note if some of our samples had errors
    if success.samples_completed < profile.samples:
        sample_errors = profile.samples - success.samples_completed
        sample_error_pct = int(float(sample_errors) / float(profile.samples) * 100)
        message = f"\n[{theme.warning}]WARNING: {sample_errors} of {profile.samples} samples ({sample_error_pct}%) had errors and were not scored.[/{theme.warning}]"
        return Group(grid, message)
    else:
        return grid


SCORES_PER_ROW = 4


def task_scores(scores: list[EvalScore], pad_edge: bool = False) -> list[Table]:
    rows: list[Table] = []

    # Process scores in groups
    for i in range(0, len(scores), SCORES_PER_ROW):
        # Create a grid for this row of scores
        score_row = Table.grid(
            expand=False,
            padding=(0, 2, 0, 0),
        )

        # Add columns for each score in this row
        for _ in range(SCORES_PER_ROW):
            score_row.add_column()

        # Create individual score tables and add them to the row
        score_tables: list[Table | str] = []
        for score in scores[i : i + SCORES_PER_ROW]:
            table = Table(
                show_header=False,
                show_lines=False,
                box=None,
                show_edge=False,
                pad_edge=pad_edge,
            )
            table.add_column()
            table.add_column()

            # Add score name and metrics
            table.add_row(f"[bold]{score.name}[/bold]")
            for name, metric in score.metrics.items():
                table.add_row(f"{name}", f"{metric.value:.3f}")

            score_tables.append(table)

        # Fill remaining slots with empty tables if needed
        while len(score_tables) < SCORES_PER_ROW:
            score_tables.append("")

        # Add the score tables to this row
        score_row.add_row(*score_tables)

        # Add this row of scores to the main grid
        rows.append(score_row)

    return rows


def task_result_summary(profile: TaskProfile, success: TaskSuccess) -> RenderableType:
    # The contents of the panel
    config = task_config(profile)
    body = task_stats(success.stats)

    # the panel
    return task_panel(
        profile=profile,
        show_model=True,
        body=body,
        subtitle=config,
        footer=task_results(profile, success),
        log_location=profile.log_location,
    )


def task_result_error(profile: TaskProfile, error: TaskError) -> RenderableType:
    return task_panel(
        profile=profile,
        show_model=True,
        body=rich_traceback(error.exc_type, error.exc_value, error.traceback),
        subtitle=None,
        footer=task_interrupted(profile, error.samples_completed),
        log_location=profile.log_location,
    )


def task_stats(stats: EvalStats) -> RenderableType:
    theme = rich_theme()
    panel = Table.grid(expand=True)
    panel.add_column()
    if len(stats.model_usage) < 2:
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

        if usage.reasoning_tokens is not None:
            reasoning_tokens = f", [bold]R: [/bold]{usage.reasoning_tokens:,}"
        else:
            reasoning_tokens = ""

        table.add_row(
            Text(model, style="bold"),
            f"  {usage.total_tokens:,} tokens [{input_tokens}, [bold]O: [/bold]{usage.output_tokens:,}{reasoning_tokens}]",
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


def task_metric(metrics: list[TaskDisplayMetric], width: int | None = None) -> str:
    reducer_names: Set[str] = {
        metric.reducer for metric in metrics if metric.reducer is not None
    }
    show_reducer = len(reducer_names) > 1 or (
        len(reducer_names) == 1 and "avg" not in reducer_names
    )

    metric = metrics[0]
    if metric.value is None or np.isnan(metric.value):
        value = " n/a"
    else:
        value = f"{metric.value:.2f}"

    if show_reducer and metric.reducer is not None:
        metric_str = f"{metric.name}/{metric.reducer}: {value}"
    else:
        metric_str = f"{metric.name}: {value}"

    if width is not None:
        metric_str = metric_str.rjust(width)
    return metric_str


def task_metrics(scores: list[EvalScore]) -> str:
    theme = rich_theme()
    scorer_names: Set[str] = {score.name for score in scores}
    reducer_names: Set[str] = {
        score.reducer for score in scores if score.reducer is not None
    }
    show_reducer = len(reducer_names) > 1 or "avg" not in reducer_names
    output: dict[str, str] = {}
    for score in scores:
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
        return f"[{theme.metric}]{task_dict(output, True)}[/{theme.metric}]"
    else:
        return ""
