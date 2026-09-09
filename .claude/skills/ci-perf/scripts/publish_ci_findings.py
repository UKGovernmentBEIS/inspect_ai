#!/usr/bin/env python3
"""Publish CI findings to fork issues, or validate them without any writes."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = "meridianlabs-ai/inspect_ai"
TRACKING_TITLE = "CI performance trend summaries"
TRACKING_MARKER = "<!-- ci-perf-trends-v1 -->"


def gh(*args: str) -> Any:
    """Run a fixed gh command and decode its JSON response."""
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def api(path: str, fields: dict[str, str]) -> Any:
    """Write issue data through the fork's REST endpoint."""
    result = subprocess.run(
        ["gh", "api", f"repos/{REPO}/{path}", "--method", "POST", "--input", "-"],
        input=json.dumps(fields),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def issues() -> list[dict[str, Any]]:
    """List issues through REST so retries do not depend on the search index."""
    pages = gh(
        "api", "--paginate", "--slurp", f"repos/{REPO}/issues?state=all&per_page=100"
    )
    return [issue for page in pages for issue in page if "pull_request" not in issue]


def comments(number: int) -> list[dict[str, Any]]:
    pages = gh(
        "api",
        "--paginate",
        "--slurp",
        f"repos/{REPO}/issues/{number}/comments?per_page=100",
    )
    return [comment for page in pages for comment in page]


def canonical_issue(matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Reuse the earliest marker owner, even if a later copy remains open.

    Closing a finding must not retrigger implementation on a duplicate copy.
    Warn on copied markers so maintainers can remove them without losing history.
    """
    if len(matches) > 1:
        print(
            f"WARNING: duplicate CI issue markers on {[item['number'] for item in matches]}; using the earliest issue",
            file=sys.stderr,
        )
    return min(matches, key=lambda item: item["number"]) if matches else None


def tracking_issue(known: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    matches = [
        issue
        for issue in (issues() if known is None else known)
        if TRACKING_MARKER in (issue.get("body") or "")
    ]
    return canonical_issue(matches)


def read_history() -> list[dict[str, Any]]:
    """Read compact summaries from the tracking issue, without creating it."""
    issue = tracking_issue()
    if issue is None:
        return []
    summaries = []
    for comment in comments(issue["number"]):
        body = comment["body"]
        if not body.startswith("<!-- ci-perf-summary:"):
            continue
        blocks = re.findall(r"```json\n(.*?)\n```", body, re.DOTALL)
        if not blocks:
            raise ValueError(f"Malformed trend summary: {comment['html_url']}")
        summary = json.loads(blocks[-1])
        if summary.get("schema_version") != 1:
            raise ValueError(f"Unsupported trend schema: {comment['html_url']}")
        summaries.append(summary)
    return summaries[-10:]


def validate_findings(value: Any) -> list[dict[str, Any]]:
    """Reject malformed output before any issue is created."""
    if not isinstance(value, list) or len(value) > 5:
        raise ValueError("findings.json must be a list of at most five findings")
    keys = set()
    for finding in value:
        if not isinstance(finding, dict) or set(finding) - {
            "key",
            "title",
            "body",
            "existing_issue",
        }:
            raise ValueError("Unexpected finding fields")
        for field, maximum in (("key", 80), ("title", 200), ("body", 20000)):
            text = finding.get(field)
            if not isinstance(text, str) or not text.strip() or len(text) > maximum:
                raise ValueError(f"Invalid finding {field}")
            if "@auto" in text or "@review" in text:
                raise ValueError(
                    "Automation mentions belong only in the publisher's trigger comment"
                )
        if (
            not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", finding["key"])
            or finding["key"] in keys
        ):
            raise ValueError("Finding keys must be unique lowercase slugs")
        keys.add(finding["key"])
        number = finding.get("existing_issue")
        if number is not None and (type(number) is not int or number <= 0):
            raise ValueError("existing_issue must be a positive issue number")
    return list(value)


def validate_report(summary: dict[str, Any], report: str) -> None:
    """Apply publication limits in both dry-run and live mode."""
    if summary.get("schema_version") != 1 or not report.strip():
        raise ValueError("Missing report or unsupported summary schema")
    payload = json.dumps(summary, separators=(",", ":")) + report
    if "@auto" in payload or "@review" in payload:
        raise ValueError("Trend comments must not trigger automation")
    if len(report.encode()) > 12000 or len(payload.encode()) > 58000:
        raise ValueError("Report exceeds 12 KB or report plus summary exceeds 58 KB")


def publish(
    findings: list[dict[str, Any]], summary: dict[str, Any], report: str, run_url: str
) -> list[str]:
    """Publish each finding once per run and trigger an issue at most once.

    The workflow serializes runs. Markers make retries skip completed writes.
    Closed findings are left closed, and deferred findings are left untouched.
    """
    match = re.fullmatch(
        r"https://github.com/meridianlabs-ai/actions/actions/runs/(\d+)", run_url
    )
    if match is None:
        raise ValueError("Expected an actions-repo workflow run URL")
    validate_report(summary, report)
    run_id = match.group(1)
    summary_body = f"<!-- ci-perf-summary:{run_id} -->\n{run_url}\n\n{report}\n\n```json\n{json.dumps(summary, separators=(',', ':'))}\n```"
    if len(summary_body.encode()) > 60000:
        raise ValueError(
            "Report and compact summary exceed the 60 KB issue-comment budget"
        )
    known = issues()
    tracking = tracking_issue(known)
    urls = []
    for finding in findings:
        marker = f"<!-- ci-perf-finding:{finding['key']} -->"
        number = finding.get("existing_issue")
        if number is None:
            matches = [issue for issue in known if marker in (issue.get("body") or "")]
            matched = canonical_issue(matches)
            if matched:
                number = matched["number"]
        evidence_marker = f"<!-- ci-perf-evidence:{run_id}:{finding['key']} -->"
        body = f"{marker}\n{evidence_marker}\n{finding['body']}\n\nEvidence: {run_url}"
        if number is None:
            issue = api("issues", {"title": finding["title"], "body": body})
            number = issue["number"]
        else:
            issue = gh("api", f"repos/{REPO}/issues/{number}")
            if "pull_request" in issue:
                raise ValueError(f"#{number} is a PR, not an issue")
            if finding.get("existing_issue") and issue["title"] != finding["title"]:
                raise ValueError(
                    f"#{number} title does not match the observed existing issue"
                )
        urls.append(issue["html_url"])
        if issue["state"] != "open" or any(
            label["name"] == "deferred" for label in issue.get("labels", [])
        ):
            continue
        existing = comments(number)
        if evidence_marker not in (issue.get("body") or "") and not any(
            evidence_marker in comment["body"] for comment in existing
        ):
            api(f"issues/{number}/comments", {"body": body})
        if not any("@auto" in comment["body"] for comment in existing):
            api(f"issues/{number}/comments", {"body": "@auto"})

    if tracking is None:
        tracking = api(
            "issues",
            {
                "title": TRACKING_TITLE,
                "body": f"{TRACKING_MARKER}\nCompact CI trend summaries. Raw snapshots expire after 90 days in Actions artifacts. Findings have separate implementation issues.",
            },
        )
    number = tracking["number"]
    if not any(
        f"<!-- ci-perf-summary:{run_id} -->" in comment["body"]
        for comment in comments(number)
    ):
        links = (
            "\n\nFinding issues:\n" + "\n".join(urls)
            if urls
            else "\n\nNo new actionable findings."
        )
        api(f"issues/{number}/comments", {"body": summary_body + links})
    return urls


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--read-history", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--run-url")
    args = parser.parse_args()
    if args.read_history:
        if args.publish:
            parser.error("--read-history and --publish cannot be combined")
        args.directory.mkdir(parents=True, exist_ok=True)
        (args.directory / "previous-summaries.json").write_text(
            json.dumps(read_history())
        )
        return
    findings = validate_findings(
        json.loads((args.directory / "findings.json").read_text())
    )
    summary = json.loads((args.directory / "summary.json").read_text())
    report = (args.directory / "report.md").read_text()
    validate_report(summary, report)
    if args.publish:
        if not args.run_url:
            parser.error("--publish requires --run-url")
        urls = publish(findings, summary, report, args.run_url)
        (args.directory / "published.json").write_text(json.dumps(urls))
    else:
        print(f"Dry-run: validated {len(findings)} findings; no GitHub writes")


if __name__ == "__main__":
    main()
