"""CLI command for comparing evaluation runs."""

from __future__ import annotations

import json
from typing import Any

import anyio
import click
import rich
from rich.panel import Panel
from rich.table import Table
from typing_extensions import Unpack

from inspect_ai._display.core.rich import rich_theme
from inspect_ai._util._async import configured_async_backend
from inspect_ai._util.platform import platform_init
from inspect_ai.analysis.comparison._compare import compare_evals
from inspect_ai.analysis.comparison._types import ComparisonResult

from .common import CommonOptions, common_options, process_common_options


@click.command("compare")
@click.argument("baseline", type=str, required=True)
@click.argument("candidate", type=str, required=True)
@click.option(
    "--scorer",
    multiple=True,
    type=str,
    envvar="INSPECT_COMPARE_SCORER",
    help="Scorer(s) to compare (default: all common scorers).",
)
@click.option(
    "--significance",
    type=float,
    default=0.05,
    envvar="INSPECT_COMPARE_SIGNIFICANCE",
    help="P-value threshold for significance tests (default: 0.05).",
)
@click.option(
    "--show-regressions",
    is_flag=True,
    default=False,
    help="Show per-sample regression details.",
)
@click.option(
    "--show-improvements",
    is_flag=True,
    default=False,
    help="Show per-sample improvement details.",
)
@click.option(
    "--output-file",
    type=click.Path(dir_okay=False, writable=True),
    envvar="INSPECT_COMPARE_OUTPUT_FILE",
    help="Write comparison results to JSON file.",
)
@common_options
def compare_command(
    baseline: str,
    candidate: str,
    scorer: tuple[str, ...],
    significance: float,
    show_regressions: bool,
    show_improvements: bool,
    output_file: str | None,
    **common: Unpack[CommonOptions],
) -> None:
    """Compare results from two evaluation runs."""
    process_common_options(common)

    async def run_compare() -> None:
        platform_init()

        scorers = list(scorer) if scorer else None

        result = compare_evals(
            baseline=baseline,
            candidate=candidate,
            scorers=scorers,
            significance=significance,
        )

        _print_comparison(result, show_regressions, show_improvements)

        if output_file:
            _write_json(result, output_file)

    anyio.run(run_compare, backend=configured_async_backend())


def _print_comparison(
    result: ComparisonResult,
    show_regressions: bool,
    show_improvements: bool,
) -> None:
    """Print comparison results using Rich formatting."""
    theme = rich_theme()
    console = rich.get_console()

    grid = Table.grid(expand=True)
    grid.add_column()

    # Header info
    grid.add_row("")
    grid.add_row(f" Baseline:  {result.baseline_model} ({result.baseline_task})")
    grid.add_row(f" Candidate: {result.candidate_model} ({result.candidate_task})")
    grid.add_row(
        f" Samples:   {result.aligned_count} aligned, "
        f"{result.missing_count} missing, {result.new_count} new"
    )
    grid.add_row("")

    # Metrics table
    if result.metrics:
        metrics_table = Table(show_header=True, header_style="bold")
        metrics_table.add_column("Scorer/Metric", style="cyan")
        metrics_table.add_column("Baseline", justify="right")
        metrics_table.add_column("Candidate", justify="right")
        metrics_table.add_column("Delta", justify="right")
        metrics_table.add_column("Sig.", justify="center")

        for m in result.metrics:
            delta_str = f"{m.delta:+.4f}"
            if m.relative_delta is not None:
                delta_str += f" ({m.relative_delta:+.1%})"

            sig_str = ""
            if m.p_value is not None:
                if m.significant:
                    sig_str = f"[bold green]p={m.p_value:.3f}[/bold green]"
                else:
                    sig_str = f"p={m.p_value:.3f}"

            metrics_table.add_row(
                f"{m.scorer}/{m.name}",
                f"{m.baseline_value:.4f}",
                f"{m.candidate_value:.4f}",
                delta_str,
                sig_str,
            )

        grid.add_row(metrics_table)
        grid.add_row("")

    # Regression/improvement summary
    reg_count = len(result.regressions)
    imp_count = len(result.improvements)
    unch_count = len(result.unchanged)

    summary_parts = []
    if reg_count > 0:
        summary_parts.append(f"[red]{reg_count} regressions[/red]")
    else:
        summary_parts.append(f"{reg_count} regressions")
    if imp_count > 0:
        summary_parts.append(f"[green]{imp_count} improvements[/green]")
    else:
        summary_parts.append(f"{imp_count} improvements")
    summary_parts.append(f"{unch_count} unchanged")

    grid.add_row(f" {', '.join(summary_parts)}")
    grid.add_row("")

    # Regression details
    if show_regressions and result.regressions:
        reg_table = Table(show_header=True, title="Regressions", title_style="bold red")
        reg_table.add_column("Sample ID")
        reg_table.add_column("Epoch", justify="right")
        reg_table.add_column("Scorer")
        reg_table.add_column("Baseline", justify="right")
        reg_table.add_column("Candidate", justify="right")
        reg_table.add_column("Delta", justify="right")

        for s in result.regressions[:50]:
            reg_table.add_row(
                str(s.id),
                str(s.epoch),
                s.scorer,
                f"{s.baseline_score:.4f}" if s.baseline_score is not None else "-",
                f"{s.candidate_score:.4f}" if s.candidate_score is not None else "-",
                f"{s.delta:+.4f}" if s.delta is not None else "-",
            )

        if len(result.regressions) > 50:
            reg_table.add_row(
                "...", "", "", "", "", f"({len(result.regressions) - 50} more)"
            )

        grid.add_row(reg_table)
        grid.add_row("")

    # Improvement details
    if show_improvements and result.improvements:
        imp_table = Table(
            show_header=True, title="Improvements", title_style="bold green"
        )
        imp_table.add_column("Sample ID")
        imp_table.add_column("Epoch", justify="right")
        imp_table.add_column("Scorer")
        imp_table.add_column("Baseline", justify="right")
        imp_table.add_column("Candidate", justify="right")
        imp_table.add_column("Delta", justify="right")

        for s in result.improvements[:50]:
            imp_table.add_row(
                str(s.id),
                str(s.epoch),
                s.scorer,
                f"{s.baseline_score:.4f}" if s.baseline_score is not None else "-",
                f"{s.candidate_score:.4f}" if s.candidate_score is not None else "-",
                f"{s.delta:+.4f}" if s.delta is not None else "-",
            )

        if len(result.improvements) > 50:
            imp_table.add_row(
                "...", "", "", "", "", f"({len(result.improvements) - 50} more)"
            )

        grid.add_row(imp_table)
        grid.add_row("")

    panel = Panel(
        title=f"[bold][{theme.meta}]Evaluation Comparison[/bold][/{theme.meta}]",
        title_align="left",
        renderable=grid,
    )

    console.print("")
    console.print(panel)


def _write_json(result: ComparisonResult, output_file: str) -> None:
    """Write comparison results to a JSON file."""
    data: dict[str, Any] = {
        "baseline": {
            "log": result.baseline_log,
            "task": result.baseline_task,
            "model": result.baseline_model,
        },
        "candidate": {
            "log": result.candidate_log,
            "task": result.candidate_task,
            "model": result.candidate_model,
        },
        "summary": {
            "aligned": result.aligned_count,
            "missing": result.missing_count,
            "new": result.new_count,
            "regressions": len(result.regressions),
            "improvements": len(result.improvements),
            "unchanged": len(result.unchanged),
        },
        "metrics": [
            {
                "scorer": m.scorer,
                "name": m.name,
                "baseline": m.baseline_value,
                "candidate": m.candidate_value,
                "delta": m.delta,
                "relative_delta": m.relative_delta,
                "significant": m.significant,
                "p_value": m.p_value,
                "ci_lower": m.ci_lower,
                "ci_upper": m.ci_upper,
            }
            for m in result.metrics
        ],
        "samples": [
            {
                "id": s.id,
                "epoch": s.epoch,
                "scorer": s.scorer,
                "baseline_score": s.baseline_score,
                "candidate_score": s.candidate_score,
                "delta": s.delta,
                "direction": s.direction,
            }
            for s in result.samples
        ],
    }

    with open(output_file, "w") as f:
        json.dump(data, f, indent=2, default=str)

    console = rich.get_console()
    console.print(f"\nResults written to: {output_file}")
