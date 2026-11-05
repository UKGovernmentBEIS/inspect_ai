#!/usr/bin/env python3
"""Reduce a CI snapshot to aggregate trends without retaining individual runs."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def window_hours(start: str, end: str) -> float:
    """Span between two ISO-8601 run-start timestamps, in hours.

    A fixed run count covers a variable stretch of time, so two summaries
    cannot be weighed against each other without their spans.
    """
    return round((parse_ts(end) - parse_ts(start)).total_seconds() / 3600, 2)


def job_is_unstarted(job: dict[str, Any]) -> bool:
    """Whether a non-skipped job never got a runner, so has no runner time.

    The jobs API reports an empty or null `runner_name` for a job cancelled or
    failed while still queued (fail-fast or a concurrency cancel); its
    `started_at` is the queue time, so its exec span is wall clock, not compute.
    The live queued-cancel shape is `runner_name` `""` with no steps. A job that
    reached a runner records its steps, so a falsy `runner_name` with steps
    present still counts as started; this one check also covers legacy snapshots
    that predate the recorded `runner_name`.
    """
    return not job.get("runner_name") and not job.get("steps")


def stats(values: list[float]) -> dict[str, float | int] | None:
    """Return sample count, median, and linearly interpolated p90."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * 0.9
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return {
        "n": len(values),
        "median": round(median(values), 2),
        "p90": round(
            ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower]), 2
        ),
    }


def summarize(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Summarize successful timings and observed pytest logs by job.

    Wait-from-run-start includes dependency time, so it is not labeled queue
    time. Workflow wall uses the collector's updated_at proxy, not push time.
    Duration samples include only tests printed by pytest's slow-tail filter.
    A re-run run records only its latest attempt's start, so its wall and job
    waits measure from the re-run, not the original push; such runs are left
    out of those distributions and counted in `rerun_runs`.
    """
    runs = snapshot["runs"]
    if not runs:
        raise ValueError("Cannot summarize an empty CI window")
    workflows: dict[str, list[float]] = defaultdict(list)
    jobs: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    steps: dict[str, list[float]] = defaultdict(list)
    conclusions: dict[str, int] = defaultdict(int)
    runner_seconds = 0.0
    rerun_runner_seconds = 0.0
    rerun_attribution_unknown = False
    unavailable_jobs = 0
    unavailable_cancelled_jobs = 0
    unstarted_jobs = 0
    cancelled_seconds = 0.0
    rerun_runs = 0
    excluded = {"workflow_wall": 0, "job_wait": 0, "step": 0}
    for run in runs:
        conclusions[run["conclusion"]] += 1
        is_rerun = (run.get("run_attempt") or 1) > 1
        if is_rerun:
            rerun_runs += 1
            # A legacy job record omits the per-job attempt. If a re-run holds
            # any such record — whatever that job's conclusion — the snapshot
            # predates per-job attribution: the old collector listed only the
            # latest attempt, so earlier attempts' compute is absent and the
            # re-run's share cannot be isolated. Decide this per run, before any
            # per-job skip, so a re-run of only skipped or unstarted jobs still
            # reports re-run minutes unknown rather than a false zero.
            if any(job.get("run_attempt") is None for job in run["jobs"]):
                rerun_attribution_unknown = True
        if run["conclusion"] == "success" and not is_rerun:
            if run["wall_seconds"] is None or run["wall_seconds"] < 0:
                excluded["workflow_wall"] += 1
            else:
                workflows[run["name"]].append(run["wall_seconds"])
        for job in run["jobs"]:
            if job["conclusion"] == "skipped":
                continue
            if job_is_unstarted(job):
                unstarted_jobs += 1
                continue
            seconds = job["exec_seconds"]
            if seconds is None or seconds < 0:
                unavailable_jobs += 1
                if run["conclusion"] == "cancelled":
                    unavailable_cancelled_jobs += 1
                continue
            runner_seconds += seconds
            # A legacy record (no per-job attempt) already marked the re-run's
            # attribution unknown above; here only new-collector jobs, which
            # carry a per-job attempt, add to the re-run total.
            attempt = job.get("run_attempt")
            if attempt is not None and attempt > 1:
                rerun_runner_seconds += seconds
            if run["conclusion"] == "cancelled":
                cancelled_seconds += seconds
            if job["conclusion"] != "success":
                continue
            key = f"{run['name']} / {job['name']}"
            jobs[key]["exec_seconds"].append(seconds)
            if not is_rerun:
                wait = job["wait_from_run_start_seconds"]
                if wait is None or wait < 0:
                    excluded["job_wait"] += 1
                else:
                    jobs[key]["wait_from_run_start_seconds"].append(wait)
            for step in job.get("steps", []):
                if step.get("conclusion") == "skipped":
                    continue
                if step["seconds"] is None or step["seconds"] < 0:
                    excluded["step"] += 1
                else:
                    steps[f"{key} / {step['name']}"].append(step["seconds"])

    suites: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for key, summary in snapshot.get("pytest_summaries", {}).items():
        job_name = key.split("/", 1)[1]
        for field, value in summary.items():
            suites[job_name][field].append(value)

    tests: dict[str, list[float]] = defaultdict(list)
    for key, durations in snapshot.get("pytest_durations", {}).items():
        sample: dict[str, float] = defaultdict(float)
        for duration in durations:
            sample[duration["test"]] += duration["seconds"]
        job_name = key.split("/", 1)[1]
        for test, seconds in sample.items():
            tests[f"{job_name} / {test}"].append(seconds)

    step_stats = {
        key: value
        for key, samples in steps.items()
        if (value := stats(samples)) is not None
    }
    starts = sorted(run["run_started_at"] for run in runs)
    previous_end = snapshot.get("previous_window_end")
    new_runs: int | None
    overlap_runs: int | None
    if previous_end is not None:
        new_runs = sum(
            parse_ts(run["run_started_at"]) > parse_ts(previous_end) for run in runs
        )
        overlap_runs = len(runs) - new_runs
    else:
        new_runs = overlap_runs = None
    return {
        "schema_version": 1,
        "generated_at": snapshot["generated_at"],
        "repo": snapshot["repo"],
        "window": {
            "start": starts[0],
            "end": starts[-1],
            "hours": window_hours(starts[0], starts[-1]),
            "runs": len(runs),
            # From the raw snapshot; None in legacy files that lack the fields.
            "excluded_untrusted_runs": snapshot.get("excluded_untrusted_runs"),
            "excluded_action_required_runs": snapshot.get(
                "excluded_action_required_runs"
            ),
            # None (not zero) when no previous window was recorded.
            "previous_end": previous_end,
            "new_runs": new_runs,
            "overlap_runs": overlap_runs,
        },
        "conclusions": dict(conclusions),
        "runner_minutes": None if unavailable_jobs else round(runner_seconds / 60, 2),
        "rerun_runner_minutes": None
        if unavailable_jobs or rerun_attribution_unknown
        else round(rerun_runner_seconds / 60, 2),
        "rerun_runs": rerun_runs,
        "unstarted_jobs": unstarted_jobs,
        "unavailable_job_timings": unavailable_jobs,
        "excluded_timings": excluded,
        "cancelled_runner_minutes": None
        if unavailable_cancelled_jobs
        else round(cancelled_seconds / 60, 2),
        "workflow_wall_seconds": {
            key: stats(value) for key, value in sorted(workflows.items())
        },
        "jobs": {
            key: {field: stats(values) for field, values in fields.items()}
            for key, fields in sorted(jobs.items())
        },
        "suites": {
            key: {field: stats(values) for field, values in fields.items()}
            for key, fields in sorted(suites.items())
        },
        "slow_tests_seconds": {
            key: stats(tests[key])
            for key in sorted(tests, key=lambda key: median(tests[key]), reverse=True)[
                :15
            ]
        },
        "slow_steps_seconds": {
            key: step_stats[key]
            for key in sorted(
                step_stats, key=lambda key: step_stats[key]["p90"], reverse=True
            )[:15]
        },
    }


def overlap_line(window: dict[str, Any]) -> str:
    """State how much of the window the previous snapshot already covered.

    A null `previous_end` means no earlier summary was recorded (first run, or a
    history read that returned nothing), so overlap is unknown.
    """
    if window["previous_end"] is None:
        return (
            "Previous window: none recorded, so overlap with earlier summaries "
            "is unknown."
        )
    return (
        f"Previous window ended {window['previous_end']}: by run start time, "
        f"{window['new_runs']} started after it, "
        f"{window['overlap_runs']} at or before it."
    )


def render(summary: dict[str, Any]) -> str:
    """Render the aggregate baseline so the report needs no raw snapshot."""
    window = summary["window"]
    lines = [
        "# CI performance measurements",
        "",
        f"Source: {summary['repo']}. Collected: {summary['generated_at']}.",
        f"Window: {window['start']} to {window['end']} ({window['hours']}h), {window['runs']} runs.",
        overlap_line(window),
        f"Excluded from the run budget: {window['excluded_untrusted_runs']} runs from untrusted head repositories, {window['excluded_action_required_runs']} never-started (action_required) runs.",
        f"Runner minutes: {summary['runner_minutes']} ({summary['rerun_runner_minutes']} from re-run attempts). Cancelled-run runner minutes: {summary['cancelled_runner_minutes']}. Missing or invalid job timings: {summary['unavailable_job_timings']}. Unstarted (never got a runner) jobs: {summary['unstarted_jobs']}. Re-run runs out of wall/wait: {summary['rerun_runs']}. None means unavailable, not zero.",
        "",
        f"Excluded missing or inverted observations: workflow wall {summary['excluded_timings']['workflow_wall']}, job wait {summary['excluded_timings']['job_wait']}, steps {summary['excluded_timings']['step']}.",
        "Successful runs and jobs only for timings. Workflow wall is run start to updated_at, not push-to-green. Job wait includes dependencies. Pytest counts are per outcome, not a count of unique tests across matrix jobs. Skipped steps are excluded when their status was collected. Slow-test totals include only printed phases.",
    ]
    for field, title in (
        ("workflow_wall_seconds", "Workflow wall seconds"),
        ("jobs", "Job seconds"),
        ("suites", "Pytest outcomes and seconds"),
        ("slow_tests_seconds", "Slow tests, observed seconds"),
        ("slow_steps_seconds", "Slow steps, seconds"),
    ):
        lines.extend(
            [
                "",
                f"## {title}",
                "",
                "| Metric | n | Median | p90 |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for key, value in summary[field].items():
            metrics = (
                {key: value}
                if "n" in value
                else {f"{key} / {name}": item for name, item in value.items()}
            )
            for name, item in metrics.items():
                if item is not None:
                    name = name.replace("|", "\\|")
                    lines.append(
                        f"| {name} | {item['n']} | {item['median']} | {item['p90']} |"
                    )
        if not summary[field]:
            lines.append("| No observations | | | |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    summary = summarize(json.loads(args.snapshot.read_text()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, separators=(",", ":")) + "\n")
    if args.markdown:
        args.markdown.write_text(render(summary))


if __name__ == "__main__":
    main()
