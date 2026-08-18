#!/usr/bin/env python3
"""Collect PR CI timing data into a JSON snapshot for the ci-perf skill.

Fetches recent completed pull_request workflow runs and their jobs via the
GitHub API (through the `gh` CLI, which must be authenticated), derives
per-job execution and wait times, and optionally parses pytest
`--durations` blocks out of test-job logs.

Analysis is deliberately NOT done here — the script records facts; the
skill's analyze phase interprets them (job dependency chains, trends,
proposals).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple


def gh_api(path: str) -> Any:
    result = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def gh_api_text(path: str) -> str:
    result = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, check=True
    )
    return result.stdout


def parse_ts(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def seconds_between(start: str | None, end: str | None) -> float | None:
    s, e = parse_ts(start), parse_ts(end)
    return (e - s).total_seconds() if s and e else None


def fetch_runs(repo: str, limit: int) -> list[dict[str, Any]]:
    by_id: dict[int, dict[str, Any]] = {}
    page = 1
    while len(by_id) < limit:
        batch = gh_api(
            f"repos/{repo}/actions/runs"
            f"?event=pull_request&status=completed&per_page=100&page={page}"
        )["workflow_runs"]
        if not batch:
            break
        by_id.update({run["id"]: run for run in batch})
        page += 1
    runs = sorted(by_id.values(), key=lambda r: r["run_started_at"], reverse=True)[
        :limit
    ]
    warn_on_time_gap(runs)
    return runs


def warn_on_time_gap(runs: list[dict[str, Any]]) -> None:
    """Warn when the snapshot's runs aren't one contiguous stretch of time.

    The runs endpoint occasionally serves a stale page, so pages that should
    be adjacent aren't, and the snapshot silently ends up with a multi-week
    hole in the middle — which skews every median and (if the older clump
    predates a CI change) can drop the pytest --durations data entirely.
    Re-running the collector gets a clean window.
    """
    starts = [t for r in runs if (t := parse_ts(r["run_started_at"]))]
    gaps = [(a - b).total_seconds() / 3600 for a, b in zip(starts, starts[1:])]
    if gaps and max(gaps) > 12:
        span = (starts[0] - starts[-1]).total_seconds() / 3600
        print(
            f"WARNING: {max(gaps):.0f}h gap inside the {span:.0f}h run window "
            f"({starts[-1].isoformat()} .. {starts[0].isoformat()}) — the API "
            "likely served a stale page; re-run the collector.",
            file=sys.stderr,
        )


def job_record(run: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": job["name"],
        "conclusion": job["conclusion"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
        "exec_seconds": seconds_between(job["started_at"], job["completed_at"]),
        # Wait from run start to job start. Only a true queue time for jobs
        # with no `needs`; for dependent jobs the analyze phase must subtract
        # predecessor completion (dependency map comes from the workflow files).
        "wait_from_run_start_seconds": seconds_between(
            run["run_started_at"], job["started_at"]
        ),
        # Per-step timings: job-level numbers hide which step costs what
        # (checkout vs install vs the actual work) and hide high-variance
        # steps whose median looks fine (e.g. full-pack git fetches that
        # take 30s or 4min depending on server pack-cache luck).
        "steps": [
            {
                "name": step["name"],
                "seconds": seconds_between(step["started_at"], step["completed_at"]),
            }
            for step in job.get("steps", [])
        ],
        "id": job["id"],
    }


class Duration(NamedTuple):
    seconds: float
    phase: str
    test: str


# pytest --durations lines, tolerating the Actions log timestamp prefix:
# "2026-08-04T19:40:01.123Z 12.34s call     tests/test_foo.py::test_bar"
DURATION_LINE = re.compile(
    r"(?:\S+ )?(\d+(?:\.\d+)?)s\s+(call|setup|teardown)\s+(\S+::\S+)\s*$"
)


def parse_durations(log_text: str) -> list[Duration]:
    return [
        Duration(float(m.group(1)), m.group(2), m.group(3))
        for line in log_text.splitlines()
        if (m := DURATION_LINE.match(line.strip()))
    ]


def collect_durations(
    repo: str, runs: list[dict[str, Any]], max_runs: int
) -> dict[str, list[dict[str, Any]]]:
    """Parse pytest --durations from test-job logs of recent Build runs.

    Returns {} silently when the durations flag isn't in CI yet — the
    skill's first proposed safe fix is adding it.
    """
    durations: dict[str, list[dict[str, Any]]] = {}
    build_runs = [
        r for r in runs if r["name"] == "Build" and r["conclusion"] == "success"
    ][:max_runs]
    for run in build_runs:
        for job in run["jobs"]:
            if not job["name"].startswith("test") or job["conclusion"] != "success":
                continue
            try:
                log = gh_api_text(f"repos/{repo}/actions/jobs/{job['id']}/logs")
            except subprocess.CalledProcessError:
                continue  # logs expire after 90 days / may 404
            if parsed := parse_durations(log):
                durations[f"{run['id']}/{job['name']}"] = [d._asdict() for d in parsed]
    return durations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="UKGovernmentBEIS/inspect_ai")
    parser.add_argument("--limit", type=int, default=200, help="max runs to fetch")
    parser.add_argument(
        "--durations-runs",
        type=int,
        default=10,
        help="how many recent Build runs to mine for pytest --durations (0 to skip)",
    )
    parser.add_argument("--out", type=Path, required=True, help="snapshot JSON path")
    args = parser.parse_args()

    raw_runs = fetch_runs(args.repo, args.limit)
    print(f"fetched {len(raw_runs)} runs; fetching jobs...", file=sys.stderr)

    runs = [
        {
            "id": run["id"],
            "name": run["name"],
            "head_branch": run["head_branch"],
            "conclusion": run["conclusion"],
            "run_attempt": run["run_attempt"],
            "run_started_at": run["run_started_at"],
            "updated_at": run["updated_at"],
            "wall_seconds": seconds_between(run["run_started_at"], run["updated_at"]),
            "jobs": [
                job_record(run, job)
                for job in gh_api(
                    f"repos/{args.repo}/actions/runs/{run['id']}/jobs?per_page=100"
                )["jobs"]
            ],
        }
        for run in raw_runs
    ]

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": args.repo,
        "run_count": len(runs),
        "runs": runs,
        "pytest_durations": (
            collect_durations(args.repo, runs, args.durations_runs)
            if args.durations_runs
            else {}
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snapshot, indent=1))
    print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
