"""Tests for aggregation and the unattended publication boundary."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import publish_ci_findings as publisher
import pytest
from collect_ci_data import parse_summary
from publish_ci_findings import publish, validate_findings
from summarize_ci_data import render, stats, summarize


def _paged_gh_api(pages: dict[int, list[tuple[int, bool, str]]]) -> Any:
    """Build a fake `gh_api` paging the runs listing from a page table.

    Each entry is (run id, trusted head repository, conclusion). Run ids double
    as minute offsets from the page's `until` bound, so a smaller id is a newer
    run and every record validates inside the collector's created-at range.
    A page absent from the table returns an empty listing (exhausted).
    """
    from datetime import datetime, timedelta
    from urllib.parse import parse_qs, urlparse

    def fake(path: str) -> Any:
        query = parse_qs(urlparse(path).query)
        page = int(query["page"][0])
        until = datetime.fromisoformat(query["created"][0].split("..")[1])
        runs = []
        for run_id, trusted, conclusion in pages.get(page, []):
            moment = (
                (until - timedelta(minutes=run_id)).isoformat().replace("+00:00", "Z")
            )
            runs.append(
                {
                    "id": run_id,
                    "created_at": moment,
                    "run_started_at": moment,
                    "conclusion": conclusion,
                    "head_repository": {
                        "full_name": "UKGovernmentBEIS/inspect_ai"
                        if trusted
                        else "outsider/inspect_ai"
                    },
                }
            )
        return {"workflow_runs": runs}

    return fake


@pytest.fixture
def snapshot() -> dict[str, Any]:
    return {
        "generated_at": "2026-09-09T12:00:00Z",
        "repo": "UKGovernmentBEIS/inspect_ai",
        "runs": [
            {
                "id": index,
                "name": "Build",
                "conclusion": conclusion,
                "run_started_at": f"2026-09-09T0{index}:00:00Z",
                "wall_seconds": seconds + 5,
                "jobs": [
                    {
                        "name": "test (3.11)",
                        "conclusion": conclusion,
                        "exec_seconds": seconds,
                        "wait_from_run_start_seconds": 5,
                        "steps": [{"name": "pytest", "seconds": seconds}],
                    }
                ],
            }
            for index, (conclusion, seconds) in enumerate(
                [("success", 10), ("success", 30), ("cancelled", 80)]
            )
        ],
        "pytest_summaries": {
            "0/test (3.11)": {"passed": 100, "skipped": 20, "seconds": 10}
        },
        "pytest_durations": {
            "0/test (3.11)": [
                {"test": "tests/a.py::test_a", "phase": "setup", "seconds": 2},
                {"test": "tests/a.py::test_a", "phase": "call", "seconds": 3},
            ]
        },
    }


def test_summary_preserves_samples_and_separates_cancelled(
    snapshot: dict[str, Any],
) -> None:
    result = summarize(snapshot)
    assert result["workflow_wall_seconds"]["Build"] == {"n": 2, "median": 25, "p90": 33}
    assert result["runner_minutes"] == 2
    assert result["cancelled_runner_minutes"] == 1.33
    assert (
        result["slow_tests_seconds"]["test (3.11) / tests/a.py::test_a"]["median"] == 5
    )
    assert result["suites"]["test (3.11)"]["passed"]["median"] == 100
    assert "not push-to-green" in render(result)


def test_empty_samples_are_not_zero(snapshot: dict[str, Any]) -> None:
    assert stats([]) is None
    snapshot["pytest_durations"] = {}
    snapshot["pytest_summaries"] = {}
    result = summarize(snapshot)
    assert result["suites"] == {}
    assert result["slow_tests_seconds"] == {}
    snapshot["runs"] = []
    with pytest.raises(ValueError, match="empty"):
        summarize(snapshot)


def test_pytest_counts_keep_skips_and_warnings_separate() -> None:
    assert parse_summary("== 12 passed, 3 skipped, 2 warnings in 4.50s ==") == {
        "passed": 12,
        "skipped": 3,
        "warning": 2,
        "seconds": 4.5,
    }


@pytest.mark.parametrize(
    "value",
    [
        {},
        [{"key": "bad/key", "title": "a", "body": "b"}],
        [{"key": "good", "title": "a", "body": "@auto"}],
        [{"key": "good", "title": "a", "body": "b", "existing_issue": True}],
    ],
)
def test_invalid_findings_fail_before_publication(value: Any) -> None:
    with pytest.raises(ValueError):
        validate_findings(value)


def test_dry_run_never_calls_gh(
    tmp_path: Path, snapshot: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "summary.json").write_text(json.dumps(summarize(snapshot)))
    (tmp_path / "report.md").write_text("Measured evidence")
    (tmp_path / "findings.json").write_text(
        '[{"key":"slow-job","title":"Slow job","body":"Evidence"}]'
    )
    monkeypatch.setattr(sys, "argv", ["publish", "--directory", str(tmp_path)])

    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Dry-run called GitHub")

    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(publisher, "gh", fail)
    monkeypatch.setattr(publisher, "api", fail)
    publisher.main()


def test_publication_never_labels_or_triggers_and_retries_skip_evidence(
    snapshot: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publishing a finding must not authorize its implementation.

    A finding is model output. No `auto` label and no trigger comment on a
    create, on a retry of the same run, or on a later run (Claude Security
    finding 4628345 in meridianlabs-ai/actions: the machine account's label
    used to start the fork's coding agent).
    """
    stored: list[dict[str, Any]] = []
    posted: dict[int, list[dict[str, Any]]] = {}
    labeled: list[int] = []

    def fake_issues() -> list[dict[str, Any]]:
        return stored

    def fake_comments(number: int) -> list[dict[str, Any]]:
        return posted.get(number, [])

    def fake_api(path: str, fields: dict[str, Any]) -> dict[str, Any]:
        if path == "issues":
            number = len(stored) + 1
            issue = {
                **fields,
                "number": number,
                "html_url": f"https://github.com/{publisher.REPO}/issues/{number}",
                "state": "open",
                "labels": [],
            }
            stored.append(issue)
            return issue
        number = int(path.split("/")[1])
        if path.endswith("/labels"):
            labeled.append(number)
            return fields
        posted.setdefault(number, []).append(fields)
        return fields

    def fake_gh(*args: str) -> Any:
        return stored[int(args[-1].split("/")[-1]) - 1]

    monkeypatch.setattr(publisher, "issues", fake_issues)
    monkeypatch.setattr(publisher, "comments", fake_comments)
    monkeypatch.setattr(publisher, "api", fake_api)
    monkeypatch.setattr(publisher, "gh", fake_gh)
    findings = validate_findings(
        [{"key": "slow-job", "title": "Slow job", "body": "Measured evidence"}]
    )
    for _ in range(2):
        publish(
            findings,
            summarize(snapshot),
            "Report",
            "https://github.com/meridianlabs-ai/actions/actions/runs/123",
        )
    assert len(stored) == 2
    assert stored[0]["labels"] == [] and "labels" not in stored[0].get("body", "")
    assert labeled == []
    assert posted.get(1, []) == []  # the evidence is the issue body; no trigger
    assert len(posted[2]) == 1
    publish(
        findings,
        summarize(snapshot),
        "Report",
        "https://github.com/meridianlabs-ai/actions/actions/runs/123",
        run_attempt=2,
    )
    assert labeled == []
    assert not any("<!-- ci-perf-trigger:" in c["body"] for c in posted.get(1, []))
    assert len(posted[2]) == 2
    assert "<!-- ci-perf-summary:123:2 -->" in posted[2][-1]["body"]


def test_raw_output_in_checkout_rejected_before_network() -> None:
    script = Path(__file__).with_name("collect_ci_data.py")
    result = subprocess.run(
        [sys.executable, str(script), "--out", str(script.parent / "raw.json")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "outside the repository" in result.stderr


@pytest.mark.parametrize(
    "state,labels", [("closed", []), ("open", [{"name": "deferred"}])]
)
def test_closed_and_deferred_findings_are_not_retriggered(
    state: str,
    labels: list[dict[str, str]],
    snapshot: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publisher,
        "gh",
        lambda *args: {
            "number": 7,
            "html_url": "https://github.com/meridianlabs-ai/inspect_ai/issues/7",
            "title": "Slow job",
            "state": state,
            "labels": labels,
        },
    )
    monkeypatch.setattr(publisher, "issues", lambda: [])
    monkeypatch.setattr(publisher, "tracking_issue", lambda known=None: {"number": 8})
    monkeypatch.setattr(
        publisher,
        "comments",
        lambda number: [{"body": "<!-- ci-perf-summary:123:1 -->"}],
    )

    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Closed or deferred finding was written")

    monkeypatch.setattr(publisher, "api", fail)
    publish(
        [
            {
                "key": "slow-job",
                "title": "Slow job",
                "body": "Evidence",
                "existing_issue": 7,
            }
        ],
        summarize(snapshot),
        "Report",
        "https://github.com/meridianlabs-ai/actions/actions/runs/123",
    )


def test_only_open_non_deferred_issues_are_returned(
    snapshot: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    issues_by_number = {
        1: {"state": "open", "labels": []},
        2: {"state": "closed", "labels": []},
        3: {"state": "open", "labels": [{"name": "deferred"}]},
    }
    writes: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(publisher, "issues", lambda: [])
    monkeypatch.setattr(publisher, "tracking_issue", lambda known=None: {"number": 8})
    monkeypatch.setattr(publisher, "comments", lambda number: [])
    monkeypatch.setattr(
        publisher,
        "gh",
        lambda *args: {
            "number": int(args[1].rsplit("/", 1)[1]),
            "html_url": f"https://github.com/meridianlabs-ai/inspect_ai/issues/{args[1].rsplit('/', 1)[1]}",
            "title": "Slow job",
            **issues_by_number[int(args[1].rsplit("/", 1)[1])],
        },
    )
    monkeypatch.setattr(
        publisher, "api", lambda path, fields: writes.append((path, fields))
    )
    urls = publish(
        [
            {
                "key": f"slow-job-{number}",
                "title": "Slow job",
                "body": "Evidence",
                "existing_issue": number,
            }
            for number in issues_by_number
        ],
        summarize(snapshot),
        "Report",
        "https://github.com/meridianlabs-ai/actions/actions/runs/123",
    )
    assert urls == ["https://github.com/meridianlabs-ai/inspect_ai/issues/1"]
    tracking_comment = next(
        fields["body"] for path, fields in writes if path == "issues/8/comments"
    )
    for number in issues_by_number:
        assert (
            f"https://github.com/meridianlabs-ai/inspect_ai/issues/{number}"
            in tracking_comment
        )


@pytest.mark.parametrize("title", ["Slow job", "Unrelated issue"])
def test_existing_issue_identity_and_empty_body(
    title: str, snapshot: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    writes: list[dict[str, Any]] = []
    monkeypatch.setattr(publisher, "issues", lambda: [])
    monkeypatch.setattr(publisher, "tracking_issue", lambda known=None: {"number": 2})
    monkeypatch.setattr(
        publisher,
        "comments",
        lambda number: []
        if number == 1
        else [{"body": "<!-- ci-perf-summary:123:1 -->"}],
    )
    monkeypatch.setattr(
        publisher,
        "gh",
        lambda *args: {
            "number": 1,
            "title": title,
            "html_url": "https://github.com/meridianlabs-ai/inspect_ai/issues/1",
            "state": "open",
            "body": None,
        },
    )
    monkeypatch.setattr(publisher, "api", lambda path, fields: writes.append(fields))
    findings = [
        {
            "key": "slow-job",
            "title": "Slow job",
            "body": "Evidence",
            "existing_issue": 1,
        }
    ]
    if title == "Slow job":
        publish(
            findings,
            summarize(snapshot),
            "Report",
            "https://github.com/meridianlabs-ai/actions/actions/runs/123",
        )
        # The evidence comment alone: no label, no trigger comment.
        assert len(writes) == 1
        assert "<!-- ci-perf-evidence:123:1:slow-job -->" in writes[0]["body"]
    else:
        with pytest.raises(ValueError, match="title does not match"):
            publish(
                findings,
                summarize(snapshot),
                "Report",
                "https://github.com/meridianlabs-ai/actions/actions/runs/123",
            )
        assert writes == []


def test_issue_lookup_uses_paginated_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_gh(*args: str) -> Any:
        assert args[:3] == ("api", "--paginate", "--slurp")
        assert (
            args[-1] == "repos/meridianlabs-ai/inspect_ai/issues?state=all&per_page=100"
        )
        return [
            [{"number": 1, "body": None}, {"number": 2, "pull_request": {}}],
            [{"number": 3}],
        ]

    monkeypatch.setattr(publisher, "gh", fake_gh)
    assert [issue["number"] for issue in publisher.issues()] == [1, 3]


def test_history_uses_final_json_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publisher, "tracking_issue", lambda: {"number": 1})
    monkeypatch.setattr(
        publisher,
        "comments",
        lambda number: [
            {"user": {"id": 330132053}, "body": "A quoted <!-- ci-perf-summary:1 -->"},
            {
                "user": {"id": 330132053},
                "body": '<!-- ci-perf-summary:2 -->\n```json\n{"example":true}\n```\n```json\n{"schema_version":1}\n```',
            },
        ],
    )
    assert publisher.read_history() == [{"schema_version": 1}]


@pytest.mark.parametrize("report", ["@auto", "@review", "x" * 40001])
def test_unsafe_or_oversized_trend_comment_is_rejected(
    report: str, snapshot: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        publisher.validate_report(summarize(snapshot), report)


def test_raw_output_in_another_checkout_rejected(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    script = Path(__file__).with_name("collect_ci_data.py")
    result = subprocess.run(
        [sys.executable, str(script), "--out", str(tmp_path / "raw.json")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "outside the repository" in result.stderr


def test_tracking_identity_survives_rename_and_duplicate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = {
        "number": 1,
        "title": "Renamed",
        "state": "closed",
        "body": publisher.TRACKING_MARKER,
    }
    duplicate = {
        "number": 2,
        "title": publisher.TRACKING_TITLE,
        "state": "open",
        "body": publisher.TRACKING_MARKER,
    }
    assert publisher.tracking_issue([duplicate, original]) is original
    assert "duplicate CI issue markers" in capsys.readouterr().err


def test_bad_run_url_fails_before_github(
    snapshot: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Invalid run URL reached GitHub")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ValueError, match="actions-repo"):
        publish(
            [],
            summarize(snapshot),
            "Report",
            "https://github.com/other/repo/actions/runs/123",
        )


def test_history_recovers_summary_after_unclosed_report_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = 'Intro\n\n```json\n{"example":true}\n'
    body = (
        "<!-- ci-perf-summary:1 -->\nrun\n"
        + report
        + '\n\n```json\n{"schema_version":1}\n```'
    )
    monkeypatch.setattr(publisher, "tracking_issue", lambda: {"number": 1})
    monkeypatch.setattr(
        publisher,
        "comments",
        lambda number: [{"user": {"id": 330132053}, "body": body}],
    )
    assert publisher.read_history() == [{"schema_version": 1}]


def test_read_history_ignores_non_publisher_comments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the publisher accounts' summaries are trusted; the issue is public.

    330132053 is meridian-marvin[bot]; 999 is an untrusted outsider. The
    outsider's malformed comment would crash the parser if it were read, and
    their well-formed far-future summary would win max() in the collector, so
    both must be dropped before any parsing.
    """
    monkeypatch.setattr(publisher, "tracking_issue", lambda: {"number": 1})
    monkeypatch.setattr(
        publisher,
        "comments",
        lambda number: [
            {
                "user": {"id": 999},
                "body": "<!-- ci-perf-summary:1 -->\n```json\n{",
                "html_url": "outsider-malformed",
            },
            {
                "user": {"id": 999},
                "body": '<!-- ci-perf-summary:2 -->\nrun\n\n```json\n{"schema_version":1,"window":{"end":"2999-01-01T00:00:00Z"}}\n```',
                "html_url": "outsider-wellformed",
            },
            {
                "user": {"id": 330132053},
                "body": '<!-- ci-perf-summary:3 -->\nrun\n\n```json\n{"schema_version":1,"window":{"end":"2026-09-01T00:00:00Z"}}\n```',
                "html_url": "publisher",
            },
        ],
    )
    assert publisher.read_history() == [
        {"schema_version": 1, "window": {"end": "2026-09-01T00:00:00Z"}}
    ]


def test_read_history_raises_on_publisher_malformed_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed summary from a publisher account is a real publisher bug.

    The author filter does not soften it: it still raises, as before the filter.
    """
    monkeypatch.setattr(publisher, "tracking_issue", lambda: {"number": 1})
    monkeypatch.setattr(
        publisher,
        "comments",
        lambda number: [
            {
                "user": {"id": 294938113},
                "body": "<!-- ci-perf-summary:1 -->\nno json fence here",
                "html_url": "publisher-malformed",
            }
        ],
    )
    with pytest.raises(ValueError, match="Malformed trend summary"):
        publisher.read_history()


def test_read_history_ignores_null_user_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A comment whose author is null is dropped before parsing.

    The GitHub API types an issue comment's `user` as nullable, so a deleted
    account leaves `user` None. Such a comment is not a publisher, so it is
    skipped even when its body is malformed, and the real publisher summary is
    still returned.
    """
    monkeypatch.setattr(publisher, "tracking_issue", lambda: {"number": 1})
    monkeypatch.setattr(
        publisher,
        "comments",
        lambda number: [
            {
                "user": None,
                "body": "<!-- ci-perf-summary:1 -->\n```json\n{",
                "html_url": "null-user-malformed",
            },
            {
                "user": {"id": 330132053},
                "body": '<!-- ci-perf-summary:2 -->\nrun\n\n```json\n{"schema_version":1}\n```',
                "html_url": "publisher",
            },
        ],
    )
    assert publisher.read_history() == [{"schema_version": 1}]


def test_failed_finding_still_records_measurements(
    snapshot: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    writes: list[dict[str, Any]] = []
    monkeypatch.setattr(publisher, "issues", lambda: [])
    monkeypatch.setattr(publisher, "tracking_issue", lambda known=None: {"number": 2})
    monkeypatch.setattr(publisher, "comments", lambda number: [])
    monkeypatch.setattr(
        publisher, "gh", lambda *args: {"number": 1, "title": "Wrong issue"}
    )

    def fake_api(path: str, fields: dict[str, Any]) -> None:
        assert path == "issues/2/comments"
        writes.append(fields)

    monkeypatch.setattr(publisher, "api", fake_api)
    with pytest.raises(ValueError, match="title does not match"):
        publish(
            [
                {
                    "key": "slow-job",
                    "title": "Slow job",
                    "body": "Evidence",
                    "existing_issue": 1,
                }
            ],
            summarize(snapshot),
            "Report",
            "https://github.com/meridianlabs-ai/actions/actions/runs/123",
        )
    assert len(writes) == 1
    assert "<!-- ci-perf-summary:123:1 -->" in writes[0]["body"]
    assert "Finding publication failed" in writes[0]["body"]


def test_skipped_jobs_cannot_make_compute_negative(snapshot: dict[str, Any]) -> None:
    snapshot["runs"][0]["jobs"].append(
        {
            "name": "skipped job",
            "conclusion": "skipped",
            "exec_seconds": -15113,
            "runner_name": "ubuntu-latest",
        }
    )
    assert summarize(snapshot)["runner_minutes"] == 2
    snapshot["runs"][0]["jobs"][-1]["conclusion"] = "failure"
    result = summarize(snapshot)
    assert result["runner_minutes"] is None
    assert result["unavailable_job_timings"] == 1


def test_collection_retries_out_of_window_page(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.parse import parse_qs, urlparse

    import collect_ci_data as collector

    calls = 0

    def fake_api(path: str) -> Any:
        nonlocal calls
        calls += 1
        query = parse_qs(urlparse(path).query)
        until = query["created"][0].split("..")[1]
        created = "2000-01-01T00:00:00Z" if calls == 1 else until
        return {
            "workflow_runs": [
                {
                    "id": 1,
                    "created_at": created,
                    "run_started_at": created,
                    "conclusion": "success",
                    "head_repository": {"full_name": "UKGovernmentBEIS/inspect_ai"},
                }
            ]
        }

    monkeypatch.setattr(collector, "gh_api", fake_api)
    assert collector.fetch_runs("owner/repo", 1).runs[0]["id"] == 1
    assert calls == 2


def test_collection_fails_after_three_stale_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import collect_ci_data as collector

    calls = 0

    def fake_api(path: str) -> Any:
        nonlocal calls
        calls += 1
        return {"workflow_runs": [{"id": 1, "created_at": "2000-01-01T00:00:00Z"}]}

    monkeypatch.setattr(collector, "gh_api", fake_api)
    with pytest.raises(RuntimeError, match="all three"):
        collector.fetch_runs("owner/repo", 1)
    assert calls == 3


def test_collection_repeated_page_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.parse import parse_qs, urlparse

    import collect_ci_data as collector

    calls = 0

    def fake_api(path: str) -> Any:
        nonlocal calls
        calls += 1
        until = parse_qs(urlparse(path).query)["created"][0].split("..")[1]
        return {
            "workflow_runs": [{"id": 1, "created_at": until, "run_started_at": until}]
        }

    monkeypatch.setattr(collector, "gh_api", fake_api)
    with pytest.raises(RuntimeError, match="all three"):
        collector.fetch_runs("owner/repo", 2)
    assert calls == 6


def test_kept_runs_and_exclusion_counts_flow_into_snapshot_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Main fetches jobs only for kept runs and records what fetch_runs carries.

    The exclusion counts and the recorded previous window end reach raw.json and
    flow into the summary window.
    """
    import collect_ci_data as collector

    started, updated = "2026-09-09T00:00:00Z", "2026-09-09T00:10:00Z"

    def run(run_id: int, head_repo: str) -> dict[str, Any]:
        return {
            "id": run_id,
            "name": "Build",
            "head_branch": "topic",
            "conclusion": "success",
            "run_attempt": 1,
            "run_started_at": started,
            "updated_at": updated,
            "head_repository": {"full_name": head_repo},
        }

    kept = [
        run(1, "UKGovernmentBEIS/inspect_ai"),
        run(3, "meridianlabs-ai/inspect_ai"),
    ]
    requested: list[str] = []

    def fake_pages(path: str) -> Any:
        requested.append(path)
        run_id = int(path.split("/runs/")[1].split("/")[0])
        job = {
            "id": run_id * 10,
            "name": "test (3.11)",
            "conclusion": "success",
            "run_attempt": 1,
            "runner_name": "ubuntu-latest",
            "started_at": started,
            "completed_at": updated,
            "steps": [
                {
                    "name": "pytest",
                    "conclusion": "success",
                    "started_at": started,
                    "completed_at": updated,
                }
            ],
        }
        return [{"jobs": [job]}]

    def fake_log(path: str) -> str:
        requested.append(path)
        return "1.50s call tests/a.py::test_a\n== 1 passed in 1.50s =="

    monkeypatch.setattr(
        collector,
        "fetch_runs",
        lambda repo, limit, days: collector.FetchedRuns(kept, 2, 1),
    )
    monkeypatch.setattr(
        collector, "read_history", lambda: [{"window": {"end": "2026-09-01T00:00:00Z"}}]
    )
    monkeypatch.setattr(collector, "gh_api_pages", fake_pages)
    monkeypatch.setattr(collector, "gh_api_text", fake_log)
    out, summary_out = tmp_path / "raw.json", tmp_path / "summary.json"
    monkeypatch.setattr(
        sys, "argv", ["collect", "--out", str(out), "--summary-out", str(summary_out)]
    )
    collector.main()

    result = json.loads(out.read_text())
    assert [r["id"] for r in result["runs"]] == [1, 3]
    assert result["run_count"] == 2
    assert result["excluded_untrusted_runs"] == 2
    assert result["excluded_action_required_runs"] == 1
    assert result["previous_window_end"] == "2026-09-01T00:00:00Z"
    assert set(result["pytest_durations"]) == {"1/test (3.11)", "3/test (3.11)"}
    assert not [p for p in requested if "/runs/2/" in p or "/runs/4/" in p]
    assert all("filter=all" in p for p in requested if "/jobs?" in p)
    assert "excluded 2 from untrusted head repositories" in capsys.readouterr().err
    summary = json.loads(summary_out.read_text())
    assert summary["workflow_wall_seconds"]["Build"]["n"] == 2
    assert summary["window"]["excluded_untrusted_runs"] == 2
    assert summary["window"]["excluded_action_required_runs"] == 1


def test_invalid_distribution_timings_are_counted_and_excluded(
    snapshot: dict[str, Any],
) -> None:
    snapshot["runs"][0]["wall_seconds"] = -3
    snapshot["runs"][0]["jobs"][0]["wait_from_run_start_seconds"] = -4
    snapshot["runs"][0]["jobs"][0]["steps"][0].update(
        conclusion="skipped", seconds=-999
    )
    snapshot["runs"][1]["jobs"][0]["steps"][0]["seconds"] = -8
    result = summarize(snapshot)
    assert result["excluded_timings"] == {"workflow_wall": 1, "job_wait": 1, "step": 1}
    assert result["workflow_wall_seconds"]["Build"]["n"] == 1
    assert result["jobs"]["Build / test (3.11)"]["wait_from_run_start_seconds"] == {
        "n": 1,
        "median": 5,
        "p90": 5,
    }
    assert result["slow_steps_seconds"] == {}
    assert "job wait 1" in render(result)


def test_collector_preserves_step_status() -> None:
    from collect_ci_data import job_record

    run = {"run_started_at": "2026-09-09T00:00:00Z"}
    job = {
        "id": 1,
        "name": "job",
        "conclusion": "success",
        "started_at": run["run_started_at"],
        "completed_at": "2026-09-09T00:01:00Z",
        "steps": [
            {
                "name": "conditional",
                "conclusion": "skipped",
                "started_at": "2026-09-09T00:01:00Z",
                "completed_at": run["run_started_at"],
            }
        ],
    }
    record = job_record(run, job)
    assert record["steps"][0]["conclusion"] == "skipped"
    assert record["steps"][0]["seconds"] == -60


def test_slow_steps_rank_by_reported_p90(snapshot: dict[str, Any]) -> None:
    template = snapshot["runs"][0]
    snapshot["runs"] = [
        {
            **template,
            "jobs": [
                {
                    **template["jobs"][0],
                    "steps": [{"name": "spiky", "seconds": seconds}]
                    + [
                        {"name": f"steady-{index}", "seconds": 15}
                        for index in range(15)
                    ],
                }
            ],
        }
        for seconds in [10] * 9 + [90]
    ]
    steps = summarize(snapshot)["slow_steps_seconds"]
    assert len(steps) == 15
    assert next(iter(steps)).endswith("spiky")
    assert next(iter(steps.values()))["p90"] == 18


@pytest.mark.parametrize("already_labeled", [True, False])
def test_no_label_write_whether_or_not_a_human_labelled_the_issue(
    snapshot: dict[str, Any], monkeypatch: pytest.MonkeyPatch, already_labeled: bool
) -> None:
    """A reused issue whose evidence is already recorded gets no write at all.

    In particular no `auto` label when it has none (the write that
    commissioned the coding agent) and no removal when a human applied one (a
    human's label is theirs to keep).
    """
    writes: list[str] = []
    monkeypatch.setattr(publisher, "issues", lambda: [])
    monkeypatch.setattr(publisher, "tracking_issue", lambda known=None: {"number": 2})
    monkeypatch.setattr(
        publisher,
        "comments",
        lambda number: [{"body": "@auto"}]
        if number == 1
        else [{"body": "<!-- ci-perf-summary:123:1 -->"}],
    )
    monkeypatch.setattr(
        publisher,
        "gh",
        lambda *args: {
            "number": 1,
            "title": "Slow job",
            "html_url": "https://github.com/meridianlabs-ai/inspect_ai/issues/1",
            "state": "open",
            "body": "<!-- ci-perf-evidence:123:1:slow-job -->",
            "labels": [{"name": "auto"}] if already_labeled else [],
        },
    )

    def fake_api(path: str, fields: dict[str, Any]) -> None:
        writes.append(path)
        if path.endswith("/labels"):
            raise RuntimeError("label request failed")

    monkeypatch.setattr(publisher, "api", fake_api)
    args = (
        [
            {
                "key": "slow-job",
                "title": "Slow job",
                "body": "Evidence",
                "existing_issue": 1,
            }
        ],
        summarize(snapshot),
        "Report",
        "https://github.com/meridianlabs-ai/actions/actions/runs/123",
    )
    publish(*args)
    assert writes == []


@pytest.mark.parametrize("human", [True, False])
def test_reused_issue_evidence_cadence_and_human_handoff(
    snapshot: dict[str, Any], monkeypatch: pytest.MonkeyPatch, human: bool
) -> None:
    posted: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    monkeypatch.setattr(publisher, "issues", lambda: [])
    monkeypatch.setattr(publisher, "tracking_issue", lambda known=None: {"number": 2})
    monkeypatch.setattr(
        publisher,
        "comments",
        lambda number: list(posted)
        if number == 1
        else [
            {"body": "<!-- ci-perf-summary:123:1 -->"},
            {"body": "<!-- ci-perf-summary:124:1 -->"},
        ],
    )
    monkeypatch.setattr(
        publisher,
        "gh",
        lambda *args: {
            "number": 1,
            "title": "Slow job",
            "html_url": "https://github.com/meridianlabs-ai/inspect_ai/issues/1",
            "state": "open",
            "body": "Existing human issue",
            "labels": labels,
        },
    )

    def fake_api(path: str, fields: dict[str, Any]) -> None:
        if path.endswith("/labels"):
            labels.append({"name": "auto"})
        else:
            posted.append(fields)

    monkeypatch.setattr(publisher, "api", fake_api)
    findings = validate_findings(
        [
            {
                "key": "slow-job",
                "title": "Slow job",
                "body": "Full measured evidence",
                "existing_issue": 1,
                "human_implementation": human,
            }
        ]
    )
    results = [
        publish(
            findings,
            summarize(snapshot),
            "Report",
            f"https://github.com/meridianlabs-ai/actions/actions/runs/{run_id}",
        )
        for run_id in [123, 124, 124]
    ]
    assert results == [["https://github.com/meridianlabs-ai/inspect_ai/issues/1"]] * 3
    evidence = [item["body"] for item in posted if "ci-perf-evidence:" in item["body"]]
    assert len(evidence) == 2
    assert "Full measured evidence" in evidence[0]
    assert "Full measured evidence" not in evidence[1]
    assert (
        "Still observed: https://github.com/meridianlabs-ai/actions/actions/runs/124"
        in evidence[1]
    )
    # No label and no trigger comment whether or not a human is needed: the
    # publisher records the need, a maintainer decides what happens next.
    assert labels == []
    assert not any("ci-perf-trigger:" in item["body"] for item in posted)
    assert len(posted) == 2
    assert all(("Needs a human to implement" in body) is human for body in evidence)
    assert not any("auto" in body for body in evidence)


@pytest.mark.parametrize("value", ["true", 1, None])
def test_human_implementation_requires_boolean(value: Any) -> None:
    with pytest.raises(ValueError, match="human_implementation must be a boolean"):
        validate_findings(
            [
                {
                    "key": "slow-job",
                    "title": "Slow job",
                    "body": "Evidence",
                    "human_implementation": value,
                }
            ]
        )


# --- Issue 493 + 592: --limit counts kept runs, not fetched runs -------------


def test_fetch_counts_kept_runs_and_scopes_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A majority-untrusted first page still yields `limit` kept runs.

    The excluded count covers only the analyzed window (no last-page overshoot).
    """
    import collect_ci_data as collector

    pages = {
        1: [
            (0, True, "success"),
            (1, False, "success"),
            (2, False, "success"),
            (3, False, "success"),
            (4, False, "success"),
        ],
        2: [
            (5, True, "success"),
            (6, True, "success"),
            (7, False, "success"),
            (8, False, "success"),
            (9, False, "success"),
        ],
    }
    monkeypatch.setattr(collector, "gh_api", _paged_gh_api(pages))
    result = collector.fetch_runs("owner/repo", 3)
    assert [r["id"] for r in result.runs] == [0, 5, 6]
    # ids 1-4 are untrusted and inside the window; ids 7-9 overshoot it.
    assert result.excluded_untrusted == 4
    assert result.excluded_action_required == 0


def test_all_untrusted_page_is_not_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """A page of only untrusted runs adds fetched ids, so it is not stale.

    Paging continues to the trusted runs on the next page.
    """
    import collect_ci_data as collector

    pages = {
        1: [(0, False, "success"), (1, False, "success"), (2, False, "success")],
        2: [(3, True, "success"), (4, True, "success")],
    }
    monkeypatch.setattr(collector, "gh_api", _paged_gh_api(pages))
    result = collector.fetch_runs("owner/repo", 2)
    assert [r["id"] for r in result.runs] == [3, 4]
    assert result.excluded_untrusted == 3


def test_action_required_runs_excluded_from_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never-started action_required runs do not count toward the limit.

    They are reported in a distinct excluded count.
    """
    import collect_ci_data as collector

    pages = {
        1: [
            (0, True, "action_required"),
            (1, True, "action_required"),
            (2, True, "action_required"),
        ],
        2: [(3, True, "success"), (4, True, "success")],
    }
    monkeypatch.setattr(collector, "gh_api", _paged_gh_api(pages))
    result = collector.fetch_runs("owner/repo", 2)
    assert [r["id"] for r in result.runs] == [3, 4]
    assert result.excluded_action_required == 3
    assert result.excluded_untrusted == 0


# --- Issue 514: window span and overlap with the previous window -------------


def test_window_overlap_and_hours(snapshot: dict[str, Any]) -> None:
    result = summarize(snapshot)
    window = result["window"]
    assert window["hours"] == 2
    assert window["previous_end"] is None
    assert window["new_runs"] is None and window["overlap_runs"] is None
    assert "none recorded" in render(result).lower()

    # Runs start at 00:00, 01:00, 02:00; a previous window ending at 02:00 saw
    # all of them, so none are new.
    snapshot["previous_window_end"] = "2026-09-09T02:00:00Z"
    window = summarize(snapshot)["window"]
    assert window["new_runs"] == 0 and window["overlap_runs"] == 3
    assert window["new_runs"] + window["overlap_runs"] == window["runs"]

    snapshot["previous_window_end"] = "2026-09-09T00:30:00Z"
    result = summarize(snapshot)
    assert (result["window"]["new_runs"], result["window"]["overlap_runs"]) == (2, 1)
    assert "2026-09-09T00:30:00Z" in render(result)

    # A window that pages back entirely before the previous end: no new runs.
    snapshot["previous_window_end"] = "2026-09-10T00:00:00Z"
    window = summarize(snapshot)["window"]
    assert window["new_runs"] == 0 and window["overlap_runs"] == 3


def test_latest_window_end_picks_most_recent() -> None:
    from datetime import datetime, timezone

    from collect_ci_data import latest_window_end

    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    assert latest_window_end([], now) is None
    # Mixed Z and +00:00 inputs; the true latest is returned normalized to ...Z.
    history = [
        {"window": {"end": "2026-09-19T13:01:25Z"}},
        {"window": {"end": "2026-09-18T21:13:35+00:00"}},
    ]
    assert latest_window_end(history, now) == "2026-09-19T13:01:25Z"
    # A nonzero UTC offset is converted to UTC before comparison and output: the
    # +02:00 instant (03:00Z) is later than the 02:30Z one and normalizes to ...Z.
    offset_history = [
        {"window": {"end": "2026-10-29T02:30:00Z"}},
        {"window": {"end": "2026-10-29T05:00:00+02:00"}},
    ]
    assert latest_window_end(offset_history, now) == "2026-10-29T03:00:00Z"


def test_latest_window_end_rejects_bad_window_end() -> None:
    from datetime import datetime, timezone

    from collect_ci_data import latest_window_end

    now = datetime(2026, 10, 29, tzinfo=timezone.utc)
    bad_summaries: list[dict[str, Any]] = [
        {"window": {"end": 42}},  # not a str
        {"window": [1, 2]},  # window is not a dict
        {"window": {}},  # missing end
        {"window": {"end": "2026-10-30T00:00:00"}},  # naive datetime
        {"window": {"end": "not-a-date"}},  # non-date text
        {"window": {"end": "2027-01-01T00:00:00Z"}},  # later than now
    ]
    for bad in bad_summaries:
        with pytest.raises(ValueError):
            latest_window_end([bad], now)


# --- Issue 583: jobs cancelled while still queued add no runner time ---------


def test_unstarted_jobs_excluded_from_runner_time() -> None:
    snap = {
        "generated_at": "2026-10-11T00:00:00Z",
        "repo": "UKGovernmentBEIS/inspect_ai",
        "runs": [
            {
                "id": 1,
                "name": "Build",
                "conclusion": "cancelled",
                "run_started_at": "2026-10-11T00:00:00Z",
                "wall_seconds": 10,
                "jobs": [
                    {
                        "name": "test (3.11)",
                        "conclusion": "cancelled",
                        "exec_seconds": 2000,
                        "wait_from_run_start_seconds": 0,
                        "runner_name": None,
                        "steps": [],
                    },
                    {
                        "name": "test (3.10)",
                        "conclusion": "cancelled",
                        "exec_seconds": 100,
                        "wait_from_run_start_seconds": 0,
                        "runner_name": "ubuntu-latest",
                        "steps": [{"name": "pytest", "seconds": 100}],
                    },
                ],
            },
            {
                "id": 2,
                "name": "Build",
                "conclusion": "failure",
                "run_started_at": "2026-10-11T01:00:00Z",
                "wall_seconds": 10,
                "jobs": [
                    {
                        "name": "mypy (3.11)",
                        "conclusion": "failure",
                        "exec_seconds": 500,
                        "wait_from_run_start_seconds": 0,
                        "steps": [],
                    }
                ],
            },
        ],
        "pytest_summaries": {},
        "pytest_durations": {},
    }
    result = summarize(snap)
    assert result["unstarted_jobs"] == 2  # queued-cancelled + legacy empty-steps
    assert result["runner_minutes"] == round(100 / 60, 2)  # only the started job
    assert result["cancelled_runner_minutes"] == round(100 / 60, 2)
    assert result["unavailable_job_timings"] == 0  # unstarted is not unavailable
    assert "unstarted" in render(result).lower()


# The live API shape for a run cancelled while still queued: runner_name "" and
# runner_id 0 (not null), no steps, and a shared started_at across jobs. Run
# 38006279837 in UKGovernmentBEIS/inspect_ai returned exactly this.
_ZERO_RUNNER_JOBS = [
    {
        "id": 114075707983,
        "name": "test (3.11)",
        "status": "completed",
        "conclusion": "cancelled",
        "run_attempt": 1,
        "runner_id": 0,
        "runner_name": "",
        "started_at": "2026-10-09T23:49:25Z",
        "completed_at": "2026-10-10T00:25:26Z",
        "steps": [],
    },
    {
        "id": 114075708048,
        "name": "mypy (3.11)",
        "status": "completed",
        "conclusion": "cancelled",
        "run_attempt": 1,
        "runner_id": 0,
        "runner_name": "",
        "started_at": "2026-10-09T23:49:25Z",
        "completed_at": "2026-10-10T00:21:50Z",
        "steps": [],
    },
]


def test_empty_runner_name_jobs_add_no_runner_time() -> None:
    """A queued-cancel with runner_name "" (not null) adds no runner time.

    The live shape reports an empty runner_name, not null, so these jobs must
    still be counted unstarted rather than charged their queued wall span.
    """
    from collect_ci_data import job_record

    run = {
        "id": 38006279837,
        "name": "Build",
        "conclusion": "cancelled",
        "run_started_at": "2026-10-09T23:49:25Z",
        "wall_seconds": 2435,
    }
    snap = {
        "generated_at": "2026-10-11T00:00:00Z",
        "repo": "UKGovernmentBEIS/inspect_ai",
        "runs": [{**run, "jobs": [job_record(run, j) for j in _ZERO_RUNNER_JOBS]}],
        "pytest_summaries": {},
        "pytest_durations": {},
    }
    result = summarize(snap)
    assert result["unstarted_jobs"] == 2
    assert result["runner_minutes"] == 0
    assert result["cancelled_runner_minutes"] == 0
    assert result["unavailable_job_timings"] == 0


# --- Issue 612: re-run attempts counted; re-run runs out of wall/wait --------


# Attempt 1 failed; attempt 2 re-ran only the two `test` legs and carried the
# rest over. A carried-over job gets a NEW job id in attempt 2's listing but
# keeps the earlier attempt's runner_id and started_at (see the real listing in
# evidence/live-run-40811123765-jobs-filter-all.json: `mypy (3.11)` is id
# 123241411490 in attempt 1 and id 123243125471 in attempt 2, both runner_id
# 1000462481 at 03:15:37Z). Skipped jobs never get a runner, so their runner_id
# is null and each attempt's copy keeps its own id.
_RERUN_JOBS = [
    {
        "id": 1,
        "name": "test (3.14)",
        "conclusion": "failure",
        "run_attempt": 1,
        "runner_id": 501,
        "runner_name": "gh",
        "started_at": "2026-10-29T00:00:00Z",
        "completed_at": "2026-10-29T00:05:00Z",
        "steps": [],
    },
    {
        "id": 2,
        "name": "mypy",
        "conclusion": "success",
        "run_attempt": 1,
        "runner_id": 502,
        "runner_name": "gh",
        "started_at": "2026-10-29T00:00:00Z",
        "completed_at": "2026-10-29T00:01:00Z",
        "steps": [],
    },
    {
        "id": 5,
        "name": "docs",
        "conclusion": "skipped",
        "run_attempt": 1,
        "runner_id": None,
        "runner_name": None,
        "started_at": "2026-10-29T00:00:00Z",
        "completed_at": "2026-10-29T00:00:00Z",
        "steps": [],
    },
    {
        "id": 3,
        "name": "test (3.14)",
        "conclusion": "success",
        "run_attempt": 2,
        "runner_id": 503,
        "runner_name": "gh",
        "started_at": "2026-10-29T00:10:00Z",
        "completed_at": "2026-10-29T00:17:30Z",
        "steps": [],
    },
    {  # carried-over copy of id 2: new id, same runner_id and started_at
        "id": 4,
        "name": "mypy",
        "conclusion": "success",
        "run_attempt": 2,
        "runner_id": 502,
        "runner_name": "gh",
        "started_at": "2026-10-29T00:00:00Z",
        "completed_at": "2026-10-29T00:01:00Z",
        "steps": [],
    },
    {
        "id": 6,
        "name": "docs",
        "conclusion": "skipped",
        "run_attempt": 2,
        "runner_id": None,
        "runner_name": None,
        "started_at": "2026-10-29T00:10:00Z",
        "completed_at": "2026-10-29T00:10:00Z",
        "steps": [],
    },
]


def test_dedupe_jobs_keeps_earliest_copy_regardless_of_order() -> None:
    import collect_ci_data as collector

    def kept_ids(jobs: list[dict[str, Any]]) -> dict[int, int]:
        return {j["id"]: j["run_attempt"] for j in collector.dedupe_jobs(jobs)}

    # id 4 is a carried-over copy of id 2; the attempt-1 copy (id 2) is kept.
    # Skipped jobs (ids 5, 6) have no runner, so each stays by id.
    expected = {1: 1, 2: 1, 3: 2, 5: 1, 6: 2}
    assert kept_ids(_RERUN_JOBS) == expected
    assert kept_ids(list(reversed(_RERUN_JOBS))) == expected


def test_dedupe_jobs_keeps_zero_runner_jobs_sharing_started_at() -> None:
    """Distinct queued-cancelled jobs share runner_id 0 and a started_at.

    They are different jobs, so both must be retained; keying zero runner_id by
    (runner_id, started_at) would collapse them into one.
    """
    import collect_ci_data as collector

    kept = collector.dedupe_jobs(_ZERO_RUNNER_JOBS)
    assert sorted(j["id"] for j in kept) == [114075707983, 114075708048]


def test_zero_runner_jobs_survive_collection_and_count_as_unstarted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both zero-runner jobs reach the snapshot and add no runner time.

    Replaying the live shape through main() keeps both distinct jobs (B2) and
    the summary charges them no runner minutes, counting both as unstarted (B1).
    """
    import collect_ci_data as collector

    run = {
        "id": 38006279837,
        "name": "Build",
        "head_branch": "topic",
        "conclusion": "cancelled",
        "run_attempt": 1,
        "run_started_at": "2026-10-09T23:49:25Z",
        "updated_at": "2026-10-10T00:30:00Z",
    }

    def fake_pages(path: str) -> Any:
        return [{"jobs": _ZERO_RUNNER_JOBS}]

    monkeypatch.setattr(
        collector,
        "fetch_runs",
        lambda repo, limit, days: collector.FetchedRuns([run], 0, 0),
    )
    monkeypatch.setattr(collector, "read_history", lambda: [])
    monkeypatch.setattr(collector, "gh_api_pages", fake_pages)
    out, summary_out = tmp_path / "raw.json", tmp_path / "summary.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collect",
            "--out",
            str(out),
            "--summary-out",
            str(summary_out),
            "--durations-runs",
            "0",
        ],
    )
    collector.main()

    raw = json.loads(out.read_text())
    assert sorted(j["id"] for j in raw["runs"][0]["jobs"]) == [
        114075707983,
        114075708048,
    ]
    summary = json.loads(summary_out.read_text())
    assert summary["unstarted_jobs"] == 2
    assert summary["runner_minutes"] == 0
    assert summary["cancelled_runner_minutes"] == 0


def test_rerun_attempts_counted_and_run_excluded_from_wall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import collect_ci_data as collector

    run = {
        "id": 100,
        "name": "Build",
        "head_branch": "topic",
        "conclusion": "success",
        "run_attempt": 2,
        "run_started_at": "2026-10-29T00:10:00Z",
        "updated_at": "2026-10-29T00:20:00Z",
    }
    jobs_payload = {"jobs": _RERUN_JOBS}
    requested: list[str] = []

    def fake_pages(path: str) -> Any:
        requested.append(path)
        return [jobs_payload]

    monkeypatch.setattr(
        collector,
        "fetch_runs",
        lambda repo, limit, days: collector.FetchedRuns([run], 0, 0),
    )
    monkeypatch.setattr(collector, "read_history", lambda: [])
    monkeypatch.setattr(collector, "gh_api_pages", fake_pages)
    out, summary_out = tmp_path / "raw.json", tmp_path / "summary.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collect",
            "--out",
            str(out),
            "--summary-out",
            str(summary_out),
            "--durations-runs",
            "0",
        ],
    )
    collector.main()

    assert any("filter=all" in p for p in requested)
    raw = json.loads(out.read_text())
    jobs = raw["runs"][0]["jobs"]
    # The carried-over copy (id 4) is dropped in favor of its attempt-1 original
    # (id 2); skipped jobs stay by id, so both copies (ids 5, 6) remain.
    assert sorted(j["id"] for j in jobs) == [1, 2, 3, 5, 6]
    attempts = {j["id"]: j["run_attempt"] for j in jobs}
    assert attempts[2] == 1 and attempts[3] == 2

    summary = json.loads(summary_out.read_text())
    # attempt-1 failed leg (300s) + carried-over mypy (60s, once) + attempt-2
    # re-run leg (450s). The carried-over copy is not double-counted.
    assert summary["runner_minutes"] == round((300 + 60 + 450) / 60, 2)
    assert summary["rerun_runner_minutes"] == round(450 / 60, 2)  # attempt-2 leg only
    assert summary["rerun_runs"] == 1
    assert summary["workflow_wall_seconds"] == {}  # the only run is a re-run
    assert summary["excluded_timings"]["job_wait"] == 0  # carried-over waits dropped
    assert "wait_from_run_start_seconds" not in summary["jobs"]["Build / test (3.14)"]
    assert "re-run" in render(summary).lower()


def test_legacy_partial_rerun_reports_unknown_rerun_minutes() -> None:
    """A legacy snapshot of a partial re-run reports re-run minutes as unknown.

    The old collector kept the run's `run_attempt` but omitted each job's, and
    its latest-attempt listing carried first-attempt successes over. A 60s
    carried-over job and a 450s re-run job cannot be split with no per-job
    attempt, so `rerun_runner_minutes` is None (unknown) rather than a guess
    from the run's attempt that would charge all 510s to the re-run.
    """
    snap = {
        "generated_at": "2026-10-29T00:00:00Z",
        "repo": "UKGovernmentBEIS/inspect_ai",
        "runs": [
            {
                "id": 1,
                "name": "Build",
                "conclusion": "success",
                "run_attempt": 2,
                "run_started_at": "2026-10-29T00:10:00Z",
                "wall_seconds": 600,
                "jobs": [
                    {  # carried over from attempt 1; no per-job attempt recorded
                        "name": "mypy",
                        "conclusion": "success",
                        "exec_seconds": 60,
                        "wait_from_run_start_seconds": 0,
                        "steps": [{"name": "mypy", "seconds": 60}],
                    },
                    {  # re-run in attempt 2; no per-job attempt recorded
                        "name": "test (3.14)",
                        "conclusion": "success",
                        "exec_seconds": 450,
                        "wait_from_run_start_seconds": 0,
                        "steps": [{"name": "pytest", "seconds": 450}],
                    },
                ],
            }
        ],
        "pytest_summaries": {},
        "pytest_durations": {},
    }
    result = summarize(snap)
    assert result["runner_minutes"] == round((60 + 450) / 60, 2)
    assert result["rerun_runner_minutes"] is None
    assert result["rerun_runs"] == 1
    assert result["unavailable_job_timings"] == 0
    assert "None from re-run attempts" in render(result)


def test_legacy_rerun_of_queued_cancelled_jobs_reports_unknown_rerun_minutes() -> None:
    """A legacy re-run whose jobs were all cancelled while queued is unknown.

    The jobs never got a runner (no `runner_name`, no steps), so they add no
    runner time and the re-run's own compute is zero. But a legacy record omits
    the per-job attempt, so the snapshot predates per-job attribution: the old
    collector listed only the latest attempt, and an earlier attempt may have
    consumed runner time the listing discarded. The re-run's share therefore
    cannot be isolated and `rerun_runner_minutes` is None (unknown), not 0.
    """
    snap = {
        "generated_at": "2026-10-29T00:00:00Z",
        "repo": "UKGovernmentBEIS/inspect_ai",
        "runs": [
            {
                "id": 1,
                "name": "Build",
                "conclusion": "cancelled",
                "run_attempt": 3,
                "run_started_at": "2026-10-29T00:10:00Z",
                "wall_seconds": 600,
                "jobs": [
                    {  # cancelled while queued; no runner, no per-job attempt
                        "name": "mypy",
                        "conclusion": "cancelled",
                        "exec_seconds": None,
                        "wait_from_run_start_seconds": None,
                        "steps": [],
                    },
                    {
                        "name": "test (3.14)",
                        "conclusion": "cancelled",
                        "exec_seconds": None,
                        "wait_from_run_start_seconds": None,
                        "steps": [],
                    },
                ],
            }
        ],
        "pytest_summaries": {},
        "pytest_durations": {},
    }
    result = summarize(snap)
    assert result["rerun_runner_minutes"] is None
    assert result["rerun_runs"] == 1
    assert result["unstarted_jobs"] == 2
    assert "None from re-run attempts" in render(result)


def test_new_collector_rerun_of_queued_cancelled_jobs_reports_zero() -> None:
    """A new-collector re-run of only queued-cancelled jobs is a true zero.

    With per-job attempts present, `filter=all` lists every attempt, so absent
    re-run compute is genuinely zero rather than an artifact of latest-attempt
    listing. The re-run jobs got no runner, so `rerun_runner_minutes` is 0.0.
    """
    snap = {
        "generated_at": "2026-10-29T00:00:00Z",
        "repo": "UKGovernmentBEIS/inspect_ai",
        "runs": [
            {
                "id": 1,
                "name": "Build",
                "conclusion": "cancelled",
                "run_attempt": 2,
                "run_started_at": "2026-10-29T00:10:00Z",
                "wall_seconds": 600,
                "jobs": [
                    {
                        "name": "mypy",
                        "conclusion": "cancelled",
                        "run_attempt": 2,
                        "exec_seconds": None,
                        "wait_from_run_start_seconds": None,
                        "steps": [],
                    },
                    {
                        "name": "test (3.14)",
                        "conclusion": "cancelled",
                        "run_attempt": 2,
                        "exec_seconds": None,
                        "wait_from_run_start_seconds": None,
                        "steps": [],
                    },
                ],
            }
        ],
        "pytest_summaries": {},
        "pytest_durations": {},
    }
    result = summarize(snap)
    assert result["rerun_runner_minutes"] == 0.0
    assert result["rerun_runs"] == 1
    assert result["unstarted_jobs"] == 2


# --- Review round 1: paginated job listing, per-job log dedupe, overlap text --


def test_jobs_listing_collects_every_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """A multi-page filter=all job listing contributes all of its jobs.

    With filter=all a run with several attempts can exceed one 100-job page, so
    the collector must page through the listing before dedupe rather than read
    page 1 only.
    """
    import collect_ci_data as collector

    requested: list[str] = []

    def fake_pages(path: str) -> Any:
        requested.append(path)
        return [
            {"jobs": [{"id": 1, "run_attempt": 1}, {"id": 2, "run_attempt": 1}]},
            {"jobs": [{"id": 3, "run_attempt": 1}, {"id": 4, "run_attempt": 1}]},
        ]

    monkeypatch.setattr(collector, "gh_api_pages", fake_pages)
    jobs = collector.fetch_jobs("owner/repo", 100)
    assert sorted(job["id"] for job in jobs) == [1, 2, 3, 4]
    assert "filter=all" in requested[0]


def test_mine_test_logs_keeps_latest_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two successful attempts of one test job keep the latest attempt's log.

    "Re-run all jobs" gives each attempt its own successful copy under the same
    `{run_id}/{job_name}` key, so mining must pick by `run_attempt`, not by the
    order the jobs happen to be listed.
    """
    import collect_ci_data as collector

    def job(job_id: int, attempt: int) -> dict[str, Any]:
        return {
            "id": job_id,
            "name": "test (3.11)",
            "conclusion": "success",
            "run_attempt": attempt,
        }

    logs = {
        11: "1.00s call tests/a.py::test_old\n== 1 passed in 1.00s ==",
        12: "2.00s call tests/a.py::test_new\n== 2 passed in 2.00s ==",
    }

    def fake_log(path: str) -> str:
        return logs[int(path.split("/jobs/")[1].split("/")[0])]

    monkeypatch.setattr(collector, "gh_api_text", fake_log)
    attempts = [job(11, 1), job(12, 2)]
    for order in (attempts, list(reversed(attempts))):
        run = {"id": 1, "name": "Build", "conclusion": "success", "jobs": order}
        data = collector.mine_test_logs("owner/repo", [run], 10)
        assert data.summaries["1/test (3.11)"]["passed"] == 2
        assert data.durations["1/test (3.11)"][0]["test"] == "tests/a.py::test_new"


def test_overlap_line_is_neutral_and_by_start_time(snapshot: dict[str, Any]) -> None:
    """The overlap render states its basis without claiming shared coverage.

    It reports the split by run start time, not as runs the previous snapshot held.
    """
    snapshot["previous_window_end"] = "2026-09-09T00:30:00Z"
    text = render(summarize(snapshot))
    assert "re-measuring shared runs" not in text
    assert "run start time" in text
    assert "started after it" in text and "at or before it" in text
