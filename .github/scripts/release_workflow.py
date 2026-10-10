"""Retry-safe steps of the Release workflow (.github/workflows/release.yml).

  resolve-release  Prints the release tag this run should finish, or nothing.
                   An explicitly requested tag (workflow_dispatch input `tag`,
                   the recovery path) wins; otherwise the release Release
                   Please created in this run; otherwise a tag on this run's
                   own commit. A requested or found tag must be a published,
                   non-pre-release GitHub Release whose manifest names it and
                   whose commit is on main. A re-run therefore finishes a
                   release tagged on its own commit and never picks another.
                   A failed GitHub lookup fails the command rather than
                   counting as "no release", so the job can be retried.
  check-latest-published
                   Run when resolve-release found nothing. Fails if the latest
                   Release Please release on main is not fully published (no
                   PyPI wheel and sdist, or no npm version) and no other
                   Release run is still active. A re-run cannot find a
                   release created on an earlier commit, so this tells the
                   maintainer to dispatch Release with that tag instead of
                   finishing green. It never resumes or picks a release
                   itself.
  dispatch-checks  Dispatches each workflow that has no run yet for the
                   branch's current head commit. Safe to repeat: workflows
                   that already ran (or are running) on that commit are
                   skipped, and every workflow is attempted even if an
                   earlier dispatch fails.

Runs `gh` and `git` and reads PyPI and npm; stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any, Callable, Sequence

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

PYPI_URL = "https://pypi.org/pypi/inspect-ai/{version}/json"
NPM_URL = "https://registry.npmjs.org/@meridianlabs%2flog-viewer/{version}"
ACTIVE_RUN_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}

Run = Callable[[Sequence[str]], str]
Fetch = Callable[[str], "dict[str, Any] | None"]


class ReleaseError(Exception):
    """The tag is not a release this workflow may publish."""


class LookupFailed(Exception):
    """GitHub could not be asked (network, rate limit, auth, server error)."""


class IncompleteRelease(Exception):
    """The latest release is not fully published and needs a tag dispatch."""


def run(args: Sequence[str]) -> str:
    return subprocess.run(list(args), check=True, capture_output=True, text=True).stdout


def fetch_json(url: str) -> dict[str, Any] | None:
    """Return the JSON at `url`, or None when it answers 404."""
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise LookupFailed(f"{url} answered HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LookupFailed(f"Could not read {url}: {e}") from e
    if not isinstance(data, dict):
        raise LookupFailed(f"Unexpected response from {url}")
    return data


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


def _active_release_runs(run_: Run, repo: str, run_id: str) -> list[str]:
    """Return IDs of Release runs other than `run_id` that are still active.

    Filters by status on the server, one query per active status, so older
    active runs are not hidden behind newer completed ones. The current run
    is the only one excluded, so a full page (the limit is at least 2) always
    holds another active run, and a partial page is complete.
    """
    active: list[str] = []
    for status in sorted(ACTIVE_RUN_STATUSES):
        try:
            runs = json.loads(
                run_(
                    ["gh", "run", "list", "--repo", repo, "--workflow", "release.yml"]
                    + ["--status", status, "--limit", "20", "--json", "databaseId"]
                )
            )
        except (subprocess.CalledProcessError, ValueError) as e:
            raise LookupFailed(
                f"Could not list {status} Release runs: "
                f"{getattr(e, 'stderr', None) or e}"
            ) from e
        active += [str(r["databaseId"]) for r in runs if str(r["databaseId"]) != run_id]
    return active


def check_latest_published(run_: Run, fetch: Fetch, repo: str, run_id: str) -> str:
    """Raise IncompleteRelease if the latest release was never finished.

    Returns:
        The latest release's tag when it is complete, or "" when there is no
        Release Please release to check.

    Raises:
        IncompleteRelease: If PyPI or npm lacks the version and no other
            Release run is active (one may still be waiting for publish
            approval).
        LookupFailed: If GitHub, PyPI or npm could not be queried.
    """
    latest = _api(run_, f"repos/{repo}/releases/latest")
    if latest is None:
        return ""
    try:
        release = json.loads(latest)
        tag = release["tag_name"]
    except (ValueError, KeyError) as e:
        raise LookupFailed(f"Unexpected latest-release response: {e}") from e
    try:
        check_release(run_, repo, tag)
    except ReleaseError as e:
        _notice(f"Not checking latest release {tag}: {e}")
        return ""

    missing: list[str] = []
    pypi = fetch(PYPI_URL.format(version=tag))
    types = {f.get("packagetype") for f in (pypi or {}).get("urls", [])}
    if not {"bdist_wheel", "sdist"} <= types:
        missing.append("its PyPI wheel and sdist")
    if fetch(NPM_URL.format(version=tag)) is None:
        missing.append("its npm package")
    if not missing:
        return tag

    active = _active_release_runs(run_, repo, run_id)
    if active:
        _notice(
            f"Release {tag} is not fully published yet; Release runs {active} "
            f"may still be publishing it"
        )
        return tag
    raise IncompleteRelease(
        f"Release {tag} exists but is not fully published (missing "
        f"{', '.join(missing)}); re-run the Release workflow with tag={tag}"
    )


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
    latest = commands.add_parser("check-latest-published")
    latest.add_argument("--run-id", required=True)
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
        elif args.command == "check-latest-published":
            tag = check_latest_published(run, fetch_json, args.repo, args.run_id)
            print(f"Nothing to finish (latest release: {tag or 'none'})")
        else:
            dispatch_checks(run, args.repo, args.branch, args.workflows)
    except (ReleaseError, LookupFailed, IncompleteRelease) as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
