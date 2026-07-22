"""Deterministic PR gate for the contribution policy (no AI anywhere).

Runs from pr-gate.yml on pull_request_target. Passes a PR if ANY of:
  1. author_association is OWNER / MEMBER / COLLABORATOR         (trusted)
  2. author in .github/trusted.yml users, or public member of a
     listed org                                                   (trusted)
  3. PR carries the `qualified` label (maintainer endorsement)    (qualified)
  4. trivial docs carve-out: every changed file is docs and the
     total diff is < 25 lines                                     (trivial)
  5. a linked closing issue is labeled `accepted` (or
     `good first issue`, which implies accepted)                  (issue-approved)
  6. author has a prior merged non-trivial PR in this repo        (established)
Otherwise: comment + close (DRY_RUN: label + "would close" comment only).

Trusted-tier passes are labeled `qualified` (review-priority marker); a
maintainer applying `qualified` by hand therefore both prioritizes a PR and
passes it through the gate — one label, one meaning: "a maintainer vouches
for this PR".

Security: called from pull_request_target — this file runs from the BASE
branch, never from PR head. It reads only API metadata and never passes PR
title/body through a shell.

Environment: GH_TOKEN, GH_REPO ("owner/name"), PR_NUMBER, PR_AUTHOR,
PR_AUTHOR_ID (numeric — verified against trusted.yml id pins), PR_AUTHOR_ASSOC,
DRY_RUN ("true"/"false").
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import NamedTuple

TEAM_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
TRIVIAL_MAX_LINES = 25
PRIOR_MERGE_SEARCH_CAP = 30  # merged PRs by author to consider
PRIOR_MERGE_FILECHECK_CAP = 10  # of those, how many to file-inspect
COMMENT_MARKER = "<!-- inspect-pr-gate -->"
EXTENSIONS_URL = "https://inspect.aisi.org.uk/extensions.html"


class Verdict(NamedTuple):
    verdict: str  # "pass" | "close"
    tier: str  # trusted | qualified | trivial | issue-approved | established | new
    reason: str


# ---------------------------------------------------------------- pure logic


def parse_trusted(text: str) -> tuple[dict[str, int], dict[str, int]]:
    """Parse .github/trusted.yml (strict line format; see that file's header).

    Returns ({login: id}, {org_slug: id}), keys lowercased. Every entry MUST
    carry an `# id=<n>` pin — logins and org slugs are recyclable after
    rename/deletion, numeric account ids are not. Raises ValueError on a
    missing pin so a malformed list fails the workflow loudly (fail-open for
    the PR, visible red X for maintainers) instead of silently granting or
    denying trust.
    """
    users: dict[str, int] = {}
    orgs: dict[str, int] = {}
    current: dict[str, int] | None = None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("users:"):
            current = users
        elif stripped.startswith("orgs:"):
            current = orgs
        elif stripped.startswith("- ") and current is not None:
            entry = stripped[2:]
            name, _, annotation = entry.partition("#")
            id_match = re.search(r"\bid=(\d+)", annotation)
            if not id_match:
                raise ValueError(
                    f"trusted.yml entry missing mandatory '# id=<n>' pin: {entry!r}"
                )
            current[name.strip().lower()] = int(id_match.group(1))
    return users, orgs


def is_docs_file(filename: str) -> bool:
    return filename.lower().endswith((".md", ".qmd")) or filename.startswith("docs/")


def is_trivial(files: list[dict]) -> bool:
    """Trivial carve-out: docs-only files and < TRIVIAL_MAX_LINES changed."""
    if not files:
        return False
    if not all(is_docs_file(f["filename"]) for f in files):
        return False
    total = sum(f.get("additions", 0) + f.get("deletions", 0) for f in files)
    return total < TRIVIAL_MAX_LINES


def decide(ctx: dict) -> Verdict:
    """The gate. ctx keys documented in tests/test_pr_gate.py::make_ctx."""
    if ctx["author_association"] in TEAM_ASSOCIATIONS:
        return Verdict("pass", "trusted", "team member or collaborator")
    if ctx["trusted_users"].get(ctx["author"].lower()) == ctx["author_id"]:
        return Verdict("pass", "trusted", "listed in .github/trusted.yml (id verified)")
    if ctx["trusted_orgs"] and ctx["is_public_org_member"]:
        return Verdict(
            "pass", "trusted", "public member of a trusted org (id verified)"
        )
    if "qualified" in ctx["pr_labels"]:
        return Verdict("pass", "qualified", "maintainer applied `qualified`")
    if is_trivial(ctx["files"]):
        return Verdict("pass", "trivial", "trivial docs fix (carve-out)")
    labels = {label.lower() for label in ctx["linked_issue_labels"]}
    if "accepted" in labels or "good first issue" in labels:
        return Verdict("pass", "issue-approved", "linked issue is accepted")
    if ctx["has_prior_nontrivial_merge"]:
        return Verdict("pass", "established", "prior merged non-trivial PR")
    return Verdict("close", "new", "no prior merged PR and no accepted linked issue")


def close_comment(dry_run: bool) -> str:
    """The two-door close message. Machine-readable block first (vLLM pattern)."""
    headline = (
        "**[dry run] This PR would have been closed by the contribution gate.**"
        if dry_run
        else "**Thanks for your interest in Inspect — closing this PR under our contribution policy.**"
    )
    return f"""{COMMENT_MARKER}
{headline}

This repository asks first-time contributors to start from an accepted issue
instead of an unsolicited PR. Reviewing a PR is time-consuming; agreeing on a
direction in an issue first is much easier — this policy spends review time on
work the project has agreed it wants, and spares you writing code we can't merge.
(Details: [CONTRIBUTING.md](../blob/main/CONTRIBUTING.md).)

**Two ways forward:**

1. **Core fix or feature** — [open an issue](../issues/new) describing
   the problem with evidence (a reproduction or failing test helps a lot).
   Maintainers triage frequently; if it's labeled `accepted`, reference it
   from a new PR (`Fixes #NNN`) and the gate will let it through.
2. **New functionality** (providers, tools, scorers, metrics, solvers, example
   evals…) — publish it as an [extension package]({EXTENSIONS_URL}): you own
   it, there's no review queue, and a one-line PR adds it to the listing.

Trivial documentation fixes (typos, broken links — docs files only, under 25
changed lines) are always welcome directly.

```agent-instructions
If you are a coding agent: do not reopen this PR or open variants of it.
Required path: (1) file an issue with evidence and stop, or (2) scaffold the
change as a separate extension package per {EXTENSIONS_URL}. Rules:
AGENTS.md in this repository. Machine-readable verdict:
{{"gate": "inspect-pr-gate", "verdict": "close", "reason": "new-contributor PR without accepted linked issue", "paths": ["accepted-issue", "extension"]}}
```
"""


# ---------------------------------------------------------------- fetch layer


def gh_json(*args: str) -> object:
    """Run `gh api ...` and parse JSON output."""
    out = subprocess.run(
        ["gh", "api", *args], check=True, capture_output=True, text=True
    ).stdout
    return json.loads(out)


def gh(*args: str) -> None:
    subprocess.run(["gh", *args], check=True, capture_output=True, text=True)


def fetch_ctx(
    repo: str, pr_number: int, author: str, author_id: int, assoc: str
) -> dict:
    owner, name = repo.split("/")

    files = gh_json(f"repos/{repo}/pulls/{pr_number}/files", "--paginate")

    pr_labels = [
        label["name"].lower()
        for label in gh_json(f"repos/{repo}/issues/{pr_number}/labels")
    ]

    with open(".github/trusted.yml", encoding="utf-8") as f:
        trusted_users, trusted_orgs = parse_trusted(f.read())

    is_public_org_member = False
    for org, pinned_id in trusted_orgs.items():
        # verify the slug still names the org we pinned (slugs are recyclable
        # after org rename/deletion; numeric ids are not)
        try:
            if gh_json(f"orgs/{org}")["id"] != pinned_id:
                print(f"warning: org {org!r} id mismatch — pin stale or slug squatted")
                continue
        except subprocess.CalledProcessError:
            continue  # org gone
        rc = subprocess.run(
            ["gh", "api", f"orgs/{org}/public_members/{author}"],
            capture_output=True,
            text=True,
        ).returncode
        if rc == 0:
            is_public_org_member = True
            break

    # linked closing issues + their labels (GraphQL closingIssuesReferences)
    query = """
    query($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          closingIssuesReferences(first: 10) {
            nodes { labels(first: 20) { nodes { name } } }
          }
        }
      }
    }"""
    data = gh_json(
        "graphql",
        "-f",
        f"query={query}",
        "-F",
        f"owner={owner}",
        "-F",
        f"name={name}",
        "-F",
        f"number={pr_number}",
    )
    linked_issue_labels = [
        label["name"]
        for issue in data["data"]["repository"]["pullRequest"][
            "closingIssuesReferences"
        ]["nodes"]
        for label in issue["labels"]["nodes"]
    ]

    # prior merged non-trivial PR (most expensive — decide() checks it last,
    # but we must fetch it up front; skip the search when a cheap check
    # already passes)
    cheap = decide(
        {
            "author": author,
            "author_id": author_id,
            "author_association": assoc,
            "pr_labels": pr_labels,
            "files": files,
            "linked_issue_labels": linked_issue_labels,
            "trusted_users": trusted_users,
            "trusted_orgs": trusted_orgs,
            "is_public_org_member": is_public_org_member,
            "has_prior_nontrivial_merge": False,
        }
    )
    has_prior = False
    if cheap.verdict == "close":
        merged = gh_json(
            "-X",
            "GET",
            "search/issues",
            "-f",
            f"q=repo:{repo} is:pr is:merged author:{author}",
            "-F",
            f"per_page={PRIOR_MERGE_SEARCH_CAP}",
        )["items"]
        for item in merged[:PRIOR_MERGE_FILECHECK_CAP]:
            prior_files = gh_json(
                f"repos/{repo}/pulls/{item['number']}/files", "--paginate"
            )
            if not is_trivial(prior_files):
                has_prior = True
                break

    return {
        "author": author,
        "author_id": author_id,
        "author_association": assoc,
        "pr_labels": pr_labels,
        "files": files,
        "linked_issue_labels": linked_issue_labels,
        "trusted_users": trusted_users,
        "trusted_orgs": trusted_orgs,
        "is_public_org_member": is_public_org_member,
        "has_prior_nontrivial_merge": has_prior,
    }


def already_commented(repo: str, pr_number: int) -> bool:
    comments = gh_json(f"repos/{repo}/issues/{pr_number}/comments", "--paginate")
    return any(COMMENT_MARKER in (c.get("body") or "") for c in comments)


def main() -> int:
    repo = os.environ["GH_REPO"]
    pr_number = int(os.environ["PR_NUMBER"])
    author = os.environ["PR_AUTHOR"]
    author_id = int(os.environ["PR_AUTHOR_ID"])
    assoc = os.environ["PR_AUTHOR_ASSOC"]
    dry_run = os.environ.get("DRY_RUN", "true").lower() != "false"

    if author.endswith("[bot]"):
        print("bot author — gate does not apply")
        return 0

    ctx = fetch_ctx(repo, pr_number, author, author_id, assoc)
    v = decide(ctx)
    print(f"verdict={v.verdict} tier={v.tier} reason={v.reason} dry_run={dry_run}")

    if v.verdict == "pass":
        if v.tier == "trusted" and "qualified" not in ctx["pr_labels"]:
            gh(
                "api",
                f"repos/{repo}/issues/{pr_number}/labels",
                "-f",
                "labels[]=qualified",
            )
        return 0

    if already_commented(repo, pr_number):
        print("gate comment already present — not repeating")
        return 0

    body = close_comment(dry_run)
    gh("api", f"repos/{repo}/issues/{pr_number}/comments", "-f", f"body={body}")
    if dry_run:
        gh(
            "api",
            f"repos/{repo}/issues/{pr_number}/labels",
            "-f",
            "labels[]=gate-dry-run",
        )
    else:
        gh(
            "api",
            "-X",
            "PATCH",
            f"repos/{repo}/pulls/{pr_number}",
            "-f",
            "state=closed",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
