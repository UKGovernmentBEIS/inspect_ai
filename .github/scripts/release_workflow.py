"""Retry-safe steps of the Release workflow (.github/workflows/release.yml).

  resolve-release  Prints the release tag this run should finish, or nothing.
                   A release Release Please created in this run comes first.
                   Otherwise an explicitly requested tag (workflow_dispatch
                   input `tag`) or a tag on this run's own commit is resumed
                   when it is a published, non-pre-release GitHub Release whose
                   manifest names it and whose commit is on main. Re-running a
                   Release run therefore finishes the release it started and
                   never picks up a newer one.
  dispatch-checks  Dispatches each workflow that has no run yet for the
                   branch's current head commit. Safe to repeat: workflows
                   that already ran (or are running) on that commit are
                   skipped, and every workflow is attempted even if an
                   earlier dispatch fails.

Runs `gh` and `git`; stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Callable, Sequence

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

Run = Callable[[Sequence[str]], str]


class ReleaseError(Exception):
    pass


def run(args: Sequence[str]) -> str:
    return subprocess.run(list(args), check=True, capture_output=True, text=True).stdout


def _notice(message: str) -> None:
    print(f"::notice::{message}", file=sys.stderr)


def _tags_at(run_: Run, repo: str, sha: str) -> list[str]:
    output = run_(["git", "ls-remote", "--tags", f"https://github.com/{repo}.git"])
    commits: dict[str, str] = {}
    for line in output.splitlines():
        commit, _, ref = line.partition("\t")
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            commits[name[:-3]] = commit  # annotated tag, peeled to its commit
        else:
            commits.setdefault(name, commit)
    return sorted(tag for tag, commit in commits.items() if commit == sha)


def check_release(run_: Run, repo: str, tag: str) -> None:
    """Raise unless `tag` is a published Release Please release on main."""
    if not VERSION_RE.match(tag):
        raise ReleaseError(f"'{tag}' is not a release version (X.Y.Z)")
    try:
        release = json.loads(
            run_(
                ["gh", "release", "view", tag, "--repo", repo]
                + ["--json", "isDraft,isPrerelease"]
            )
        )
    except subprocess.CalledProcessError as e:
        raise ReleaseError(f"No GitHub Release for tag {tag}") from e
    if release["isDraft"] or release["isPrerelease"]:
        raise ReleaseError(f"Release {tag} is a draft or pre-release")
    try:
        manifest = json.loads(
            run_(
                ["gh", "api"]
                + [f"repos/{repo}/contents/.release-please-manifest.json?ref={tag}"]
                + ["-H", "Accept: application/vnd.github.raw"]
            )
        )
        status = run_(
            ["gh", "api", f"repos/{repo}/compare/main...{tag}", "--jq", ".status"]
        ).strip()
    except subprocess.CalledProcessError as e:
        raise ReleaseError(f"Could not read {tag}'s manifest or history: {e}") from e
    if manifest.get(".") != tag:
        raise ReleaseError(
            f"The manifest at {tag} says {manifest.get('.')!r}, so Release Please "
            f"did not release {tag}"
        )
    if status not in ("identical", "behind"):
        raise ReleaseError(f"Tag {tag} is not on main (compare status '{status}')")


def resolve_release(
    run_: Run,
    repo: str,
    sha: str,
    created_tag: str = "",
    requested_tag: str = "",
) -> str:
    """Return the tag whose release this run should finish, or ""."""
    if created_tag:
        if not VERSION_RE.match(created_tag):
            raise ReleaseError(f"Release Please created '{created_tag}', not X.Y.Z")
        return created_tag
    if requested_tag:
        check_release(run_, repo, requested_tag)
        _notice(f"Resuming requested release {requested_tag}")
        return requested_tag
    for tag in _tags_at(run_, repo, sha):
        try:
            check_release(run_, repo, tag)
        except ReleaseError as e:
            _notice(f"Not resuming tag {tag} on {sha}: {e}")
            continue
        _notice(f"Resuming release {tag}, which is on this run's commit {sha}")
        return tag
    return ""


def dispatch_checks(
    run_: Run, repo: str, branch: str, workflows: Sequence[str]
) -> list[str]:
    """Dispatch workflows with no run on the branch head; return those dispatched.

    Raises:
        ReleaseError: If any lookup or dispatch failed (after trying all).
    """
    sha = run_(
        ["gh", "api", f"repos/{repo}/branches/{branch}", "--jq", ".commit.sha"]
    ).strip()
    dispatched: list[str] = []
    failed: list[str] = []
    for workflow in workflows:
        try:
            runs = json.loads(
                run_(
                    [
                        "gh",
                        "run",
                        "list",
                        "--repo",
                        repo,
                        "--workflow",
                        workflow,
                        "--commit",
                        sha,
                        "--limit",
                        "1",
                        "--json",
                        "databaseId",
                    ]
                )
            )
            if runs:
                print(f"{workflow} already has run {runs[0]['databaseId']} on {sha}")
                continue
            run_(["gh", "workflow", "run", workflow, "--repo", repo, "--ref", branch])
            dispatched.append(workflow)
            print(f"Dispatched {workflow} on {branch} ({sha})")
        except subprocess.CalledProcessError as e:
            print(f"::error::Could not dispatch {workflow}: {e.stderr or e}")
            failed.append(workflow)
    if failed:
        raise ReleaseError(
            f"Dispatch failed for {failed}; re-run this job to retry them"
        )
    return dispatched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release workflow steps")
    parser.add_argument("--repo", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve-release")
    resolve.add_argument("--sha", required=True)
    resolve.add_argument("--created-tag", default="")
    resolve.add_argument("--requested-tag", default="")
    dispatch = commands.add_parser("dispatch-checks")
    dispatch.add_argument("--branch", required=True)
    dispatch.add_argument("workflows", nargs="+")
    args = parser.parse_args(argv)

    try:
        if args.command == "resolve-release":
            print(
                resolve_release(
                    run, args.repo, args.sha, args.created_tag, args.requested_tag
                )
            )
        else:
            dispatch_checks(run, args.repo, args.branch, args.workflows)
    except ReleaseError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
