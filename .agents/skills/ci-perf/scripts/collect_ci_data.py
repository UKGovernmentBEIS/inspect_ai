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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlencode

from publish_ci_findings import read_history
from summarize_ci_data import summarize

# Upstream is public, so any fork's PR triggers CI there and its logs, step
# names and run titles carry text the PR author wrote. Only these two head
# repositories can be pushed to by people who already have upstream write
# access (upstream's own branches and Meridian's fork, from which colleagues
# open upstream PRs), so runs from anywhere else never reach the analysis
# agent. Merge state is not a substitute: cancelled and failing runs feed the
# runner-waste analysis.
TRUSTED_HEAD_REPOS = frozenset(
    {"UKGovernmentBEIS/inspect_ai", "meridianlabs-ai/inspect_ai"}
)


def gh_api(path: str) -> Any:
    result = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def gh_api_pages(path: str) -> list[Any]:
    """Fetch every page of a paginated endpoint as a list of page payloads.

    `--slurp` collects each page's JSON response into one array, so the caller
    flattens the field it needs. publish_ci_findings.py uses the same idiom for
    the issues and comments listings.
    """
    result = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def gh_api_text(path: str) -> str:
    """Fetch a text API response (job logs).

    gh >= 2.97 refuses to print a response containing terminal escape
    sequences (pytest runs --color=yes, so logs always have them) unless
    --allow-escape-sequences is passed; older gh rejects that flag as
    unknown, hence the flagless retry.
    """
    result = subprocess.run(
        ["gh", "api", "--allow-escape-sequences", path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        result = subprocess.run(
            ["gh", "api", path], capture_output=True, text=True, check=True
        )
    return result.stdout


def parse_ts(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def seconds_between(start: str | None, end: str | None) -> float | None:
    s, e = parse_ts(start), parse_ts(end)
    return (e - s).total_seconds() if s and e else None


def is_trusted(run: dict[str, Any]) -> bool:
    """Whether a run's head repository is in TRUSTED_HEAD_REPOS.

    Checked on the run listing, before any per-run fetch, so no job metadata or
    log of an excluded run is requested. A run with no head repository (deleted
    fork) is untrusted.
    """
    return (run.get("head_repository") or {}).get("full_name") in TRUSTED_HEAD_REPOS


def is_action_required(run: dict[str, Any]) -> bool:
    """Whether a run never started: its conclusion is `action_required`.

    Such runs (e.g. release-please runs awaiting approval) have no jobs and 0s
    wall, so counting them toward the budget shrinks the analyzed sample.
    """
    return run.get("conclusion") == "action_required"


def is_kept(run: dict[str, Any]) -> bool:
    """Whether a run counts toward `--limit`: trusted head repo and started."""
    return is_trusted(run) and not is_action_required(run)


class FetchedRuns(NamedTuple):
    runs: list[dict[str, Any]]
    excluded_untrusted: int
    excluded_action_required: int


def fetch_runs(repo: str, limit: int, days: int = 7) -> FetchedRuns:
    """Collect `limit` kept runs from a bounded recent window.

    `limit` counts runs kept for analysis, not runs fetched. A kept run has a
    trusted head repository and a conclusion other than `action_required`:
    community forks are roughly half of upstream's PR run volume and never-
    started release runs come in bursts, so a fetch cap applied before those
    predicates would collapse the analyzed window. Paging continues until
    `limit` kept runs are in hand or the listing runs out, and both exclusion
    counts cover only the analyzed window (from the oldest kept run onward), so
    the last page's overshoot does not inflate them.

    The unfiltered endpoint has served weeks-old cached pages during live runs.
    Fix the created-at range for all pages and validate every returned record
    against it, and retry when a page repeats. Repeat detection counts fetched
    ids, not kept ones, so a page of purely excluded runs is not misread as a
    repeat. Do not publish a partial mix of current and stale pages.
    """
    until = datetime.now(timezone.utc).replace(microsecond=0)
    since = until - timedelta(days=days)
    for attempt in range(3):
        by_id: dict[int, dict[str, Any]] = {}
        kept: dict[int, dict[str, Any]] = {}
        page = 1
        stale = False
        exhausted = False
        while len(kept) < limit:
            query = urlencode(
                {
                    "event": "pull_request",
                    "status": "completed",
                    "per_page": 100,
                    "page": page,
                    "created": f"{since.isoformat()}..{until.isoformat()}",
                }
            )
            batch = gh_api(f"repos/{repo}/actions/runs?{query}")["workflow_runs"]
            if not batch:
                exhausted = True
                break
            for run in batch:
                created = parse_ts(run["created_at"])
                if created is None or not since <= created <= until:
                    stale = True
                    break
            if stale:
                break
            previous_count = len(by_id)
            by_id.update({run["id"]: run for run in batch})
            if len(by_id) == previous_count:
                stale = True
                break
            kept.update({run["id"]: run for run in batch if is_kept(run)})
            page += 1
        if not stale:
            fetched = sorted(
                by_id.values(), key=lambda r: r["run_started_at"], reverse=True
            )
            runs = [run for run in fetched if run["id"] in kept][:limit]
            if exhausted and len(runs) < limit:
                print(
                    f"WARNING: the run listing ran out after {len(runs)} kept "
                    f"runs; {limit} were requested (--days {days})",
                    file=sys.stderr,
                )
            # The analyzed window is every fetched run from the oldest kept run
            # onward, including excluded ones: they keep the gap check at full
            # listing density and bound the exclusion counts to the window that
            # is actually analyzed rather than the last page's overshoot.
            oldest = runs[-1]["run_started_at"] if runs else None
            window = [
                run
                for run in fetched
                if oldest is None or run["run_started_at"] >= oldest
            ]
            warn_on_time_gap(window)
            excluded_untrusted = sum(not is_trusted(run) for run in window)
            excluded_action_required = sum(
                is_trusted(run) and is_action_required(run) for run in window
            )
            return FetchedRuns(runs, excluded_untrusted, excluded_action_required)
        print(
            f"WARNING: stale or repeated CI page; retry {attempt + 1}/3",
            file=sys.stderr,
        )
    raise RuntimeError(
        "GitHub returned stale or repeated CI pages on all three collection attempts"
    )


def latest_window_end(summaries: list[dict[str, Any]], now: datetime) -> str | None:
    """`window.end` of the retained summary with the latest window end.

    Used to split the new snapshot's runs against the most recent previous
    window. The tracking issue stores summaries in posting order, but a re-run
    or manual dispatch can post an older window after a newer one, so take the
    latest end rather than the last entry. Returns None when no summary is
    retained, normalized to the `...Z` UTC form GitHub uses elsewhere otherwise.

    read_history already drops comments from non-publisher accounts, but a
    summary body is still attacker-influenced, so every `window.end` is parsed
    strictly: it must be an ISO-8601 string that resolves to a timezone-aware
    datetime no later than `now` (the collection time, passed in so tests are
    deterministic). A missing or malformed value raises rather than being
    coerced or skipped, because every published summary carries a valid one.
    """
    ends: list[datetime] = []
    for summary in summaries:
        window = summary.get("window")
        end = window.get("end") if isinstance(window, dict) else None
        if not isinstance(end, str):
            raise ValueError(f"Trend summary has no string window.end: {end!r}")
        parsed = datetime.fromisoformat(end.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError(f"Trend summary window.end is not timezone-aware: {end!r}")
        if parsed > now:
            raise ValueError(f"Trend summary window.end is after collection: {end!r}")
        ends.append(parsed)
    if not ends:
        return None
    return max(ends).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
            f"({starts[-1].isoformat()} .. {starts[0].isoformat()}) — the window "
            "may have missing observations or a quiet period; compare windows carefully.",
            file=sys.stderr,
        )


def fetch_jobs(repo: str, run_id: int) -> list[dict[str, Any]]:
    """All jobs across every page of a run's filter=all listing.

    filter=all lists every attempt, so a run re-run a few times can exceed one
    100-job page; page through the whole listing before dedupe drops the
    carried-over copies, or later pages' jobs are silently lost.
    """
    pages = gh_api_pages(
        f"repos/{repo}/actions/runs/{run_id}/jobs?filter=all&per_page=100"
    )
    return [job for page in pages for job in page["jobs"]]


def dedupe_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop carried-over duplicate jobs, keeping the earliest attempt's copy.

    With filter=all the jobs endpoint lists every attempt. A job carried over
    unchanged into a later attempt gets a NEW job id there, but keeps the same
    runner and start time, so dedupe by (runner_id, started_at) and keep the
    copy from the earliest attempt regardless of listing order. Only jobs that
    reached a runner can be carried over; skipped or never-started jobs have a
    null or zero runner_id and stay keyed by id so each is retained (distinct
    queued-cancelled jobs share runner_id 0 and can share a started_at).
    """
    kept: dict[Any, dict[str, Any]] = {}
    for job in jobs:
        runner_id = job.get("runner_id")
        key = (runner_id, job["started_at"]) if runner_id else job["id"]
        incumbent = kept.get(key)
        if incumbent is None or job["run_attempt"] < incumbent["run_attempt"]:
            kept[key] = job
    return list(kept.values())


def job_record(run: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": job["name"],
        "conclusion": job["conclusion"],
        # Empty or null when the job never got a runner (cancelled/failed while
        # queued); the summarizer then attributes no runner time to it.
        "runner_name": job.get("runner_name"),
        # The attempt that produced this job. filter=all returns earlier
        # attempts' jobs, so runner time per attempt and re-run totals are
        # recoverable even though the run only records its latest attempt.
        "run_attempt": job.get("run_attempt"),
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
                "conclusion": step.get("conclusion"),
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


# pytest final summary line, e.g.
# "== 1234 passed, 56 skipped, 7 deselected, 2 xfailed in 412.34s =="
SUMMARY_SECONDS = re.compile(r"=+.* in (\d+(?:\.\d+)?)s(?: \([^)]*\))? =+\s*$")
SUMMARY_COUNT = re.compile(
    r"(\d+) (passed|failed|skipped|deselected|xfailed|xpassed|errors?|warnings?)"
)
# CI runs pytest with --color=yes, so the summary line (unlike --durations
# lines) carries ANSI escapes that break both regexes unless stripped.
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def parse_summary(log_text: str) -> dict[str, Any] | None:
    """Outcome counts + total wall seconds from pytest's final summary line.

    The counts track suite size over time — distinct from --durations, which
    only sees the slow tail.
    """
    for raw in reversed(log_text.splitlines()):
        line = ANSI_ESCAPE.sub("", raw)
        if m := SUMMARY_SECONDS.search(line):
            counts = {
                # "1 error"/"2 errors" (and warning/warnings) would otherwise
                # produce different keys across runs, breaking aggregation.
                (kind.removesuffix("s") if kind in ("errors", "warnings") else kind): (
                    int(n)
                )
                for n, kind in SUMMARY_COUNT.findall(line)
            }
            if counts:
                return {**counts, "seconds": float(m.group(1))}
    return None


class TestLogData(NamedTuple):
    durations: dict[str, list[dict[str, Any]]]
    summaries: dict[str, dict[str, Any]]


def mine_test_logs(repo: str, runs: list[dict[str, Any]], max_runs: int) -> TestLogData:
    """Parse pytest --durations and summary lines from recent Build test-job logs.

    Durations come back empty silently when the flag isn't in CI yet — the
    skill's first proposed safe fix is adding it.
    """
    durations: dict[str, list[dict[str, Any]]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    build_runs = [
        r for r in runs if r["name"] == "Build" and r["conclusion"] == "success"
    ][:max_runs]
    for run in build_runs:
        # "Re-run all jobs" leaves a successful copy of a test job in more than
        # one attempt, all under the same {run_id}/{job_name} key; mine the
        # latest attempt's so the retained sample does not depend on listing order.
        latest: dict[str, dict[str, Any]] = {}
        for job in run["jobs"]:
            if not job["name"].startswith("test") or job["conclusion"] != "success":
                continue
            incumbent = latest.get(job["name"])
            if incumbent is None or (job.get("run_attempt") or 1) > (
                incumbent.get("run_attempt") or 1
            ):
                latest[job["name"]] = job
        for job in latest.values():
            try:
                log = gh_api_text(f"repos/{repo}/actions/jobs/{job['id']}/logs")
            except subprocess.CalledProcessError as error:
                print(
                    f"WARNING: unavailable test log {job['id']}: {error.stderr}",
                    file=sys.stderr,
                )
                continue  # logs expire after 90 days / may 404
            key = f"{run['id']}/{job['name']}"
            if parsed := parse_durations(log):
                durations[key] = [d._asdict() for d in parsed]
            if summary := parse_summary(log):
                summaries[key] = summary
    return TestLogData(durations, summaries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="UKGovernmentBEIS/inspect_ai")
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="max runs to analyze; untrusted and never-started runs are paged "
        "past and not counted",
    )
    parser.add_argument(
        "--days", type=int, default=7, help="maximum run creation age in days"
    )
    parser.add_argument(
        "--durations-runs",
        type=int,
        default=10,
        help="how many recent Build runs to mine for pytest --durations (0 to skip)",
    )
    parser.add_argument("--out", type=Path, required=True, help="snapshot JSON path")
    parser.add_argument("--summary-out", type=Path, help="compact aggregate JSON path")
    args = parser.parse_args()
    if any((parent / ".git").exists() for parent in args.out.resolve().parents):
        parser.error(
            "Raw snapshots must be written outside the repository, e.g. under /tmp"
        )
    if args.limit <= 0 or args.days <= 0 or args.durations_runs < 0:
        parser.error(
            "--limit and --days must be positive; --durations-runs must be nonnegative"
        )

    now = datetime.now(timezone.utc)
    raw_runs, excluded_untrusted, excluded_action_required = fetch_runs(
        args.repo, args.limit, args.days
    )
    # window.end of the most recent retained summary, so the summarizer can
    # split this window into runs new since then and runs it already covered.
    previous_window_end = latest_window_end(read_history(), now)
    print(
        f"kept {len(raw_runs)} runs; excluded {excluded_untrusted} from untrusted "
        f"head repositories and {excluded_action_required} never-started "
        "(action_required); fetching jobs...",
        file=sys.stderr,
    )

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
                for job in dedupe_jobs(fetch_jobs(args.repo, run["id"]))
            ],
        }
        for run in raw_runs
    ]

    log_data = (
        mine_test_logs(args.repo, runs, args.durations_runs)
        if args.durations_runs
        else TestLogData({}, {})
    )
    snapshot = {
        "generated_at": now.isoformat(),
        "repo": args.repo,
        "run_count": len(runs),
        "excluded_untrusted_runs": excluded_untrusted,
        "excluded_action_required_runs": excluded_action_required,
        "previous_window_end": previous_window_end,
        "runs": runs,
        "pytest_durations": log_data.durations,
        "pytest_summaries": log_data.summaries,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snapshot, indent=1))
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(summarize(snapshot), separators=(",", ":")) + "\n"
        )
    print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
