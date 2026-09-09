#!/usr/bin/env python3
"""Reduce a CI snapshot to aggregate trends without retaining individual runs."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any


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
    """
    runs = snapshot["runs"]
    if not runs:
        raise ValueError("Cannot summarize an empty CI window")
    workflows: dict[str, list[float]] = defaultdict(list)
    jobs: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    steps: dict[str, list[float]] = defaultdict(list)
    conclusions: dict[str, int] = defaultdict(int)
    runner_seconds = 0.0
    unavailable_jobs = 0
    unavailable_cancelled_jobs = 0
    cancelled_seconds = 0.0
    excluded = {"workflow_wall": 0, "job_wait": 0, "step": 0}
    for run in runs:
        conclusions[run["conclusion"]] += 1
        if run["conclusion"] == "success":
            if run["wall_seconds"] is None or run["wall_seconds"] < 0:
                excluded["workflow_wall"] += 1
            else:
                workflows[run["name"]].append(run["wall_seconds"])
        for job in run["jobs"]:
            if job["conclusion"] == "skipped":
                continue
            seconds = job["exec_seconds"]
            if seconds is None or seconds < 0:
                unavailable_jobs += 1
                if run["conclusion"] == "cancelled":
                    unavailable_cancelled_jobs += 1
                continue
            runner_seconds += seconds
            if run["conclusion"] == "cancelled":
                cancelled_seconds += seconds
            if job["conclusion"] != "success":
                continue
            key = f"{run['name']} / {job['name']}"
            jobs[key]["exec_seconds"].append(seconds)
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
    return {
        "schema_version": 1,
        "generated_at": snapshot["generated_at"],
        "repo": snapshot["repo"],
        "window": {"start": starts[0], "end": starts[-1], "runs": len(runs)},
        "conclusions": dict(conclusions),
        "runner_minutes": None if unavailable_jobs else round(runner_seconds / 60, 2),
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


def render(summary: dict[str, Any]) -> str:
    """Render the aggregate baseline so the report needs no raw snapshot."""
    lines = [
        "# CI performance measurements",
        "",
        f"Source: {summary['repo']}. Collected: {summary['generated_at']}.",
        f"Window: {summary['window']['start']} to {summary['window']['end']}, {summary['window']['runs']} runs.",
        f"Runner minutes: {summary['runner_minutes']}. Cancelled-run runner minutes: {summary['cancelled_runner_minutes']}. Missing or invalid job timings: {summary['unavailable_job_timings']}. None means unavailable, not zero.",
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
