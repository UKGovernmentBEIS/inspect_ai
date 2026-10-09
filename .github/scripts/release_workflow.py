"""Retry-safe steps of the Release workflow (.github/workflows/release.yml).

  resolve-release  Prints the release tag this run should finish, or nothing.
                   An explicitly requested tag (workflow_dispatch input `tag`,
                   the recovery path) wins; otherwise the release Release
                   Please created in this run; otherwise a tag on this run's
                   own commit. A requested or found tag must be a published,
                   non-pre-release GitHub Release whose manifest names it and
                   whose commit is on main, so a re-run finishes the release it
                   started and never picks up a newer one. A failed GitHub
                   lookup fails the command rather than counting as "no
                   release", so the job can be retried.
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
    """The tag is not a release this workflow may publish."""


class LookupFailed(Exception):
    """GitHub could not be asked (network, rate limit, auth, server error)."""


def run(args: Sequence[str]) -> str:
    return subprocess.run(list(args), check=True, capture_output=True, text=True).stdout


def _notice(message: str) -> None:
    print(f"::notice::{message}", file=sys.stderr)


def _api(run_: Run, *args: str) -> str | None:
    """Return `gh api` output, or None when GitHub answers 404."""
    try:
        return run_(["gh", "api", *args])
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        if "(HTTP 404)" in stderr:
            return None
        raise LookupFailed(f"gh api {args[0]} failed: {stderr or e}") from e


def _tags_at(run_: Run, repo: str, sha: str) -> list[str]:
    try:
        output = run_(["git", "ls-remote", "--tags", f"https://github.com/{repo}.git"])
    except subprocess.CalledProcessError as e:
        raise LookupFailed(f"Could not list tags: {(e.stderr or e)}") from e
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
    """Raise unless `tag` is a published Release Please release on main.

    Raises:
        ReleaseError: If GitHub shows `tag` is not such a release.
        LookupFailed: If GitHub could not be queried.
    """
    if not VERSION_RE.match(tag):
        raise ReleaseError(f"'{tag}' is not a release version (X.Y.Z)")
    release = _api(run_, f"repos/{repo}/releases/tags/{tag}")
    if release is None:
        raise ReleaseError(f"No GitHub Release for tag {tag}")
    try:
        flags = json.loads(release)
        draft, prerelease = flags["draft"], flags["prerelease"]
    except (ValueError, KeyError) as e:
        raise LookupFailed(f"Unexpected release response for {tag}: {e}") from e
    if draft or prerelease:
        raise ReleaseError(f"Release {tag} is a draft or pre-release")

    manifest_text = _api(
        run_,
        f"repos/{repo}/contents/.release-please-manifest.json?ref={tag}",
        "-H",
        "Accept: application/vnd.github.raw",
    )
    if manifest_text is None:
        raise ReleaseError(f"{tag} has no .release-please-manifest.json")
    try:
        version = json.loads(manifest_text).get(".")
    except (ValueError, AttributeError) as e:
        raise ReleaseError(f"{tag} has an unreadable manifest: {e}") from e
    if version != tag:
        raise ReleaseError(
            f"The manifest at {tag} says {version!r}, so Release Please did not "
            f"release {tag}"
        )

    status = _api(run_, f"repos/{repo}/compare/main...{tag}", "--jq", ".status")
    if status is None or status.strip() not in ("identical", "behind"):
        raise ReleaseError(
            f"Tag {tag} is not on main (compare status {status and status.strip()!r})"
        )


def resolve_release(
    run_: Run,
    repo: str,
    sha: str,
    created_tag: str = "",
    requested_tag: str = "",
) -> str:
    """Return the tag whose release this run should finish, or ""."""
    if requested_tag:
        if created_tag and created_tag != requested_tag:
            print(
                f"::warning::This run created {created_tag} but finishes the "
                f"requested {requested_tag}; run the Release workflow again "
                f"for {created_tag}",
                file=sys.stderr,
            )
        check_release(run_, repo, requested_tag)
        _notice(f"Resuming requested release {requested_tag}")
        return requested_tag
    if created_tag:
        if not VERSION_RE.match(created_tag):
            raise ReleaseError(f"Release Please created '{created_tag}', not X.Y.Z")
        return created_tag
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
    except (ReleaseError, LookupFailed) as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
