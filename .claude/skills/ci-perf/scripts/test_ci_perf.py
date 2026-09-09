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


def test_publication_retry_does_not_repeat_trigger(
    snapshot: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    stored: list[dict[str, Any]] = []
    posted: dict[int, list[dict[str, Any]]] = {}

    def fake_issues() -> list[dict[str, Any]]:
        return stored

    def fake_comments(number: int) -> list[dict[str, Any]]:
        return posted.get(number, [])

    def fake_api(path: str, fields: dict[str, str]) -> dict[str, Any]:
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
    assert posted[1] == [{"body": "@auto"}]
    assert len(posted[2]) == 1
    publish(
        findings,
        summarize(snapshot),
        "Report",
        "https://github.com/meridianlabs-ai/actions/actions/runs/123",
        run_attempt=2,
    )
    assert posted[1].count({"body": "@auto"}) == 1
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


@pytest.mark.parametrize("title", ["Slow job", "Unrelated issue"])
def test_existing_issue_identity_and_empty_body(
    title: str, snapshot: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    writes: list[dict[str, str]] = []
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
        assert len(writes) == 2
        assert writes[-1] == {"body": "@auto"}
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
            {"body": "A quoted <!-- ci-perf-summary:1 -->"},
            {
                "body": '<!-- ci-perf-summary:2 -->\n```json\n{"example":true}\n```\n```json\n{"schema_version":1}\n```'
            },
        ],
    )
    assert publisher.read_history() == [{"schema_version": 1}]


@pytest.mark.parametrize("report", ["@auto", "@review", "x" * 12001])
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
    monkeypatch.setattr(publisher, "comments", lambda number: [{"body": body}])
    assert publisher.read_history() == [{"schema_version": 1}]


def test_failed_finding_still_records_measurements(
    snapshot: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    writes: list[dict[str, str]] = []
    monkeypatch.setattr(publisher, "issues", lambda: [])
    monkeypatch.setattr(publisher, "tracking_issue", lambda known=None: {"number": 2})
    monkeypatch.setattr(publisher, "comments", lambda number: [])
    monkeypatch.setattr(
        publisher, "gh", lambda *args: {"number": 1, "title": "Wrong issue"}
    )

    def fake_api(path: str, fields: dict[str, str]) -> None:
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
        {"name": "skipped job", "conclusion": "skipped", "exec_seconds": -15113}
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
                {"id": 1, "created_at": created, "run_started_at": created}
            ]
        }

    monkeypatch.setattr(collector, "gh_api", fake_api)
    assert collector.fetch_runs("owner/repo", 1)[0]["id"] == 1
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
