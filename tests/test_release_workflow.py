"""Tests for the Release workflow and the Release Please changelog.

Covers .github/scripts/release_workflow.py with a fake `gh`/`git`, the parts
of release.yml and the publish steps that make re-runs safe, Changelog Lint
(run against real git diffs) and the Release Please configuration. The PyPI
skip-already-published step is tested with the other pypi-release.py tests in
tests/tools/sandbox_tools_utils/test_sandbox_tools_digests.py.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
from email.message import Message
from pathlib import Path
from typing import Any, Callable, Sequence

import pytest
import yaml

REPO = Path(__file__).parents[1]

spec = importlib.util.spec_from_file_location(
    "release_workflow", REPO / ".github" / "scripts" / "release_workflow.py"
)
assert spec is not None and spec.loader is not None
release_workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_workflow)
ReleaseError = release_workflow.ReleaseError

GH_REPO = "UKGovernmentBEIS/inspect_ai"
RELEASE_SHA = "a" * 40
LATER_SHA = "b" * 40
BRANCH = "release-please--branches--main"


class FakeGitHub:
    """Answers the gh/git calls release_workflow.py makes."""

    def __init__(self) -> None:
        self.tags: dict[str, str] = {}  # tag -> commit
        self.annotated: set[str] = set()
        self.releases: dict[str, dict[str, bool]] = {}
        self.manifests: dict[str, str] = {}  # tag -> manifest version
        self.on_main: set[str] = set()
        self.branch_head = "c" * 40
        self.runs: dict[str, list[int]] = {}  # workflow -> run ids on branch_head
        self.fail: Callable[[Sequence[str]], bool] = lambda args: False
        self.fail_stderr = "gh: Server Error (HTTP 502)"
        self.calls: list[list[str]] = []
        self.dispatched: list[str] = []
        self.latest: str | None = None  # tag of releases/latest
        self.release_runs: list[dict[str, Any]] = []  # release.yml runs, newest first

    def add_release(self, tag: str, commit: str, **flags: bool) -> None:
        self.tags[tag] = commit
        self.releases[tag] = {"draft": False, "prerelease": False, **flags}
        self.manifests[tag] = tag
        self.on_main.add(tag)

    def __call__(self, args: Sequence[str]) -> str:
        args = list(args)
        self.calls.append(args)
        if self.fail(args):
            raise subprocess.CalledProcessError(1, args, stderr=self.fail_stderr)
        if args[:2] == ["git", "ls-remote"]:
            lines = []
            for tag, commit in self.tags.items():
                if tag in self.annotated:
                    lines.append(f"{'f' * 40}\trefs/tags/{tag}")
                    lines.append(f"{commit}\trefs/tags/{tag}^{{}}")
                else:
                    lines.append(f"{commit}\trefs/tags/{tag}")
            return "\n".join(lines) + "\n"
        if args[:2] == ["gh", "api"]:
            path = args[2]
            not_found = subprocess.CalledProcessError(
                1, args, stderr="gh: Not Found (HTTP 404)"
            )
            if "/releases/tags/" in path:
                tag = path.rsplit("/", 1)[1]
                if tag not in self.releases:
                    raise not_found
                return json.dumps(self.releases[tag])
            if ".release-please-manifest.json?ref=" in path:
                tag = path.rsplit("=", 1)[1]
                if tag not in self.manifests:
                    raise not_found
                return json.dumps({".": self.manifests[tag]})
            if "/compare/main..." in path:
                return (
                    "behind\n"
                    if path.rsplit("...", 1)[1] in self.on_main
                    else ("ahead\n")
                )
            if path.endswith("/releases/latest"):
                if self.latest is None:
                    raise not_found
                return json.dumps({"tag_name": self.latest})
            if path.endswith(f"/branches/{BRANCH}"):
                return self.branch_head + "\n"
        if args[:3] == ["gh", "run", "list"]:
            workflow = args[args.index("--workflow") + 1]
            if workflow == "release.yml":
                # Like GitHub: filter by --status on the server, then apply --limit.
                status = (
                    args[args.index("--status") + 1] if "--status" in args else None
                )
                limit = int(args[args.index("--limit") + 1])
                matching = [
                    r for r in self.release_runs if status in (None, r["status"])
                ]
                return json.dumps(matching[:limit])
            assert args[args.index("--commit") + 1] == self.branch_head
            return json.dumps(
                [{"databaseId": i} for i in self.runs.get(workflow, [])][:1]
            )
        if args[:3] == ["gh", "workflow", "run"]:
            assert args[args.index("--ref") + 1] == BRANCH
            self.runs.setdefault(args[3], []).append(len(self.calls))
            self.dispatched.append(args[3])
            return ""
        raise AssertionError(f"unexpected call {args}")

    def dispatches(self) -> list[str]:
        """Successful dispatches since the last clear()."""
        return self.dispatched


def _resolve(gh: FakeGitHub, sha: str = RELEASE_SHA, **kwargs: str) -> str:
    return release_workflow.resolve_release(gh, GH_REPO, sha, **kwargs)


# ---------------------------------------------------------------------------
# resolve-release: the release a run (or a re-run) must finish
# ---------------------------------------------------------------------------


def test_release_created_in_this_run_is_used_without_lookups() -> None:
    gh = FakeGitHub()
    assert _resolve(gh, created_tag="0.3.278") == "0.3.278"
    assert gh.calls == []


def test_rerun_after_downstream_failure_resumes_the_same_release() -> None:
    # Run 1 created 0.3.278 on RELEASE_SHA, then build/publish failed. On
    # re-run, Release Please no longer reports the (already labelled) release.
    gh = FakeGitHub()
    gh.add_release("0.3.277", "e" * 40)
    gh.add_release("0.3.278", RELEASE_SHA)
    assert _resolve(gh, created_tag="0.3.278") == "0.3.278"
    assert _resolve(gh) == "0.3.278"


def test_rerun_never_picks_a_newer_release() -> None:
    gh = FakeGitHub()
    gh.add_release("0.3.278", RELEASE_SHA)
    gh.add_release("0.3.279", LATER_SHA)
    assert _resolve(gh, sha=RELEASE_SHA) == "0.3.278"
    assert _resolve(gh, sha="d" * 40) == ""


def test_rerun_resolves_annotated_tags_to_their_commit() -> None:
    gh = FakeGitHub()
    gh.add_release("0.3.278", RELEASE_SHA)
    gh.annotated.add("0.3.278")
    assert _resolve(gh) == "0.3.278"


def test_normal_push_without_a_release_resolves_nothing() -> None:
    gh = FakeGitHub()
    gh.add_release("0.3.277", "e" * 40)
    assert _resolve(gh, sha=LATER_SHA) == ""


@pytest.mark.parametrize(
    "setup",
    [
        pytest.param(lambda gh: gh.releases.pop("0.3.278"), id="tag-without-release"),
        pytest.param(
            lambda gh: gh.releases["0.3.278"].update(prerelease=True),
            id="pre-release",
        ),
        pytest.param(
            lambda gh: gh.manifests.update({"0.3.278": "0.3.277"}),
            id="not-a-release-please-commit",
        ),
        pytest.param(lambda gh: gh.manifests.pop("0.3.278"), id="no-manifest"),
        pytest.param(lambda gh: gh.on_main.discard("0.3.278"), id="off-main"),
    ],
)
def test_tag_on_commit_is_not_resumed_unless_it_is_a_release_please_release(
    setup: Callable[[FakeGitHub], Any],
) -> None:
    gh = FakeGitHub()
    gh.add_release("0.3.278", RELEASE_SHA)
    setup(gh)
    assert _resolve(gh) == ""


def test_requested_tag_resumes_from_a_later_commit() -> None:
    gh = FakeGitHub()
    gh.add_release("0.3.278", RELEASE_SHA)
    gh.add_release("0.3.279", LATER_SHA)
    assert _resolve(gh, sha="d" * 40, requested_tag="0.3.278") == "0.3.278"


@pytest.mark.parametrize(
    "tag,setup,error",
    [
        ("v0.3.278", lambda gh: None, "not a release version"),
        ("0.3.278", lambda gh: gh.releases.pop("0.3.278"), "No GitHub Release"),
        (
            "0.3.278",
            lambda gh: gh.releases["0.3.278"].update(draft=True),
            "draft or pre-release",
        ),
        (
            "0.3.278",
            lambda gh: gh.manifests.update({"0.3.278": "0.3.277"}),
            "did not release",
        ),
        ("0.3.278", lambda gh: gh.on_main.discard("0.3.278"), "not on main"),
    ],
)
def test_requested_tag_must_be_a_release_please_release(
    tag: str, setup: Callable[[FakeGitHub], Any], error: str
) -> None:
    gh = FakeGitHub()
    gh.add_release("0.3.278", RELEASE_SHA)
    setup(gh)
    with pytest.raises(ReleaseError, match=error):
        _resolve(gh, sha="d" * 40, requested_tag=tag)


READS = {
    "release": "/releases/tags/",
    "manifest": ".release-please-manifest.json",
    "main-ancestry": "/compare/main...",
}


@pytest.mark.parametrize("read", READS)
@pytest.mark.parametrize(
    "stderr",
    [
        "gh: Server Error (HTTP 502)",
        "gh: API rate limit exceeded for installation ID 1. (HTTP 403)",
        "gh: Bad credentials (HTTP 401)",
        "error connecting to api.github.com",
    ],
    ids=["5xx", "rate-limit", "auth", "network"],
)
def test_failed_lookup_fails_automatic_resolution(read: str, stderr: str) -> None:
    """A lookup error is not evidence that the release is absent."""
    gh = FakeGitHub()
    gh.add_release("0.3.278", RELEASE_SHA)
    gh.fail = lambda args: args[:2] == ["gh", "api"] and READS[read] in args[2]
    gh.fail_stderr = stderr
    with pytest.raises(release_workflow.LookupFailed, match=re.escape(stderr)):
        _resolve(gh)


def test_failed_tag_listing_fails_automatic_resolution() -> None:
    gh = FakeGitHub()
    gh.add_release("0.3.278", RELEASE_SHA)
    gh.fail = lambda args: args[:2] == ["git", "ls-remote"]
    with pytest.raises(release_workflow.LookupFailed):
        _resolve(gh)


def test_cli_fails_on_lookup_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    gh = FakeGitHub()
    gh.add_release("0.3.278", RELEASE_SHA)
    gh.fail = lambda args: args[:2] == ["gh", "api"]
    monkeypatch.setattr(release_workflow, "run", gh)
    assert (
        release_workflow.main(
            ["--repo", GH_REPO, "resolve-release", "--sha", RELEASE_SHA]
        )
        == 1
    )


def test_requested_tag_wins_over_a_release_created_in_the_same_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    gh = FakeGitHub()
    gh.add_release("0.3.278", RELEASE_SHA)
    gh.add_release("0.3.279", LATER_SHA)
    assert (
        _resolve(gh, sha=LATER_SHA, created_tag="0.3.279", requested_tag="0.3.278")
        == "0.3.278"
    )
    assert ["gh", "api", f"repos/{GH_REPO}/releases/tags/0.3.278"] in gh.calls
    assert "created 0.3.279 but finishes the requested 0.3.278" in (
        capsys.readouterr().err
    )


def test_invalid_requested_tag_never_falls_back_to_a_created_release() -> None:
    gh = FakeGitHub()
    gh.add_release("0.3.279", LATER_SHA)
    with pytest.raises(ReleaseError, match="No GitHub Release for tag 0.3.278"):
        _resolve(gh, sha=LATER_SHA, created_tag="0.3.279", requested_tag="0.3.278")


# ---------------------------------------------------------------------------
# check-latest-published: fail closed when a re-run cannot find its release
# ---------------------------------------------------------------------------

PYPI_FILES = {
    "urls": [{"packagetype": "bdist_wheel"}, {"packagetype": "sdist"}],
}
THIS_RUN = "1000"


class FakeRegistries:
    """PyPI and npm JSON for check_latest_published; None means 404."""

    def __init__(self) -> None:
        self.pypi: dict[str, Any] | None = PYPI_FILES
        self.npm: dict[str, Any] | None = {"version": "0.3.278"}
        self.fail: str | None = None  # "pypi" or "npm"

    def __call__(self, url: str) -> dict[str, Any] | None:
        registry = "pypi" if url.startswith("https://pypi.org/") else "npm"
        assert url.endswith(("/0.3.278/json", "/0.3.278"))
        if self.fail == registry:
            raise release_workflow.LookupFailed(f"{url} answered HTTP 503")
        return self.pypi if registry == "pypi" else self.npm


def _published_release() -> tuple[FakeGitHub, FakeRegistries]:
    """0.3.278, tagged on RELEASE_SHA and fully published."""
    gh = FakeGitHub()
    gh.add_release("0.3.278", RELEASE_SHA)
    gh.latest = "0.3.278"
    gh.release_runs = [{"databaseId": int(THIS_RUN), "status": "in_progress"}]
    return gh, FakeRegistries()


def _check(gh: FakeGitHub, registries: FakeRegistries) -> str:
    return release_workflow.check_latest_published(gh, registries, GH_REPO, THIS_RUN)


def test_all_jobs_retry_of_a_release_created_on_an_earlier_commit_fails() -> None:
    """The pass-3 sequence: created on an earlier merge SHA, retried on a later one."""
    gh, registries = _published_release()
    # Attempt 1 ran on LATER_SHA and created 0.3.278 on the release PR's merge
    # commit (RELEASE_SHA); its build failed, so nothing was published.
    assert _resolve(gh, sha=LATER_SHA, created_tag="0.3.278") == "0.3.278"
    registries.pypi = None
    registries.npm = None

    # Attempt 2 (Re-run all jobs): Release Please reports nothing.
    assert _resolve(gh, sha=LATER_SHA) == ""
    with pytest.raises(release_workflow.IncompleteRelease) as error:
        _check(gh, registries)
    assert str(error.value) == (
        "Release 0.3.278 exists but is not fully published (missing its PyPI "
        "wheel and sdist, its npm package); "
        "re-run the Release workflow with tag=0.3.278"
    )

    # The named recovery path resolves exactly that release.
    assert _resolve(gh, sha=LATER_SHA, requested_tag="0.3.278") == "0.3.278"


@pytest.mark.parametrize(
    "break_it,missing",
    [
        (lambda gh, r: setattr(r, "pypi", None), "its PyPI wheel and sdist"),
        (
            lambda gh, r: setattr(
                r, "pypi", {"urls": [{"packagetype": "bdist_wheel"}]}
            ),
            "its PyPI wheel and sdist",
        ),
        (lambda gh, r: setattr(r, "npm", None), "its npm package"),
    ],
    ids=["pypi-missing", "sdist-missing", "npm-missing"],
)
def test_each_missing_part_makes_the_latest_release_incomplete(
    break_it: Callable[[FakeGitHub, FakeRegistries], Any], missing: str
) -> None:
    gh, registries = _published_release()
    break_it(gh, registries)
    with pytest.raises(
        release_workflow.IncompleteRelease, match=f"missing {missing}\\)"
    ):
        _check(gh, registries)


def test_complete_latest_release_is_a_no_op() -> None:
    gh, registries = _published_release()
    assert _resolve(gh, sha=LATER_SHA) == ""
    assert _check(gh, registries) == "0.3.278"


def test_no_release_or_a_non_release_please_release_is_not_checked() -> None:
    gh, registries = _published_release()
    gh.latest = None
    assert _check(gh, registries) == ""
    gh, registries = _published_release()
    gh.manifests["0.3.278"] = "0.3.277"  # e.g. a break-glass release
    registries.pypi = None
    assert _check(gh, registries) == ""


def test_incomplete_release_is_not_reported_while_another_release_run_is_active() -> (
    None
):
    """The creating run may still be waiting for publish approval."""
    gh, registries = _published_release()
    registries.pypi = None
    gh.release_runs.append({"databaseId": 999, "status": "waiting"})
    assert _check(gh, registries) == "0.3.278"
    # Completed runs and this run itself do not count.
    gh.release_runs[-1]["status"] = "completed"
    with pytest.raises(release_workflow.IncompleteRelease):
        _check(gh, registries)


def test_waiting_run_older_than_50_completed_runs_still_suppresses_the_failure() -> (
    None
):
    """V-A: run 950 waits for approval behind 49 completed runs and this run."""
    gh, registries = _published_release()
    registries.npm = None
    gh.release_runs = (
        [{"databaseId": int(THIS_RUN), "status": "in_progress"}]
        + [{"databaseId": i, "status": "completed"} for i in range(999, 950, -1)]
        + [{"databaseId": 950, "status": "waiting"}]
    )
    assert len(gh.release_runs) == 51
    assert _check(gh, registries) == "0.3.278"
    # Without the waiting run, the same history fails.
    gh.release_runs[-1]["status"] = "completed"
    with pytest.raises(release_workflow.IncompleteRelease):
        _check(gh, registries)


@pytest.mark.parametrize("status", sorted(release_workflow.ACTIVE_RUN_STATUSES))
def test_every_active_status_suppresses_the_failure(status: str) -> None:
    gh, registries = _published_release()
    registries.pypi = None
    gh.release_runs.append({"databaseId": 999, "status": status})
    assert _check(gh, registries) == "0.3.278"


def test_active_runs_are_queried_by_status_on_the_server() -> None:
    gh, registries = _published_release()
    registries.pypi = None
    with pytest.raises(release_workflow.IncompleteRelease):
        _check(gh, registries)
    queries = [c for c in gh.calls if c[:3] == ["gh", "run", "list"]]
    assert sorted(q[q.index("--status") + 1] for q in queries) == sorted(
        release_workflow.ACTIVE_RUN_STATUSES
    )
    assert all(int(q[q.index("--limit") + 1]) >= 2 for q in queries)


@pytest.mark.parametrize(
    "fail",
    [
        "latest-release",
        "release-manifest",
        "pypi",
        "npm",
        "release-runs",
    ],
)
def test_lookup_failure_while_checking_completeness_fails(fail: str) -> None:
    gh, registries = _published_release()
    registries.pypi = None  # incomplete, so the run list is read too
    paths = {
        "latest-release": "/releases/latest",
        "release-manifest": ".release-please-manifest.json",
    }
    if fail in paths:
        gh.fail = lambda args: args[:2] == ["gh", "api"] and paths[fail] in args[2]
    elif fail == "release-runs":
        gh.fail = lambda args: args[:3] == ["gh", "run", "list"]
    else:
        registries.fail = fail
    with pytest.raises(release_workflow.LookupFailed):
        _check(gh, registries)


def test_fetch_json_separates_404_from_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen(url: str, timeout: int) -> Any:
        code = int(url.rsplit("/", 1)[1])
        raise release_workflow.urllib.error.HTTPError(url, code, "x", Message(), None)

    monkeypatch.setattr(release_workflow.urllib.request, "urlopen", urlopen)
    assert release_workflow.fetch_json("https://pypi.org/x/404") is None
    for code in (403, 429, 500, 503):
        with pytest.raises(release_workflow.LookupFailed, match=f"HTTP {code}"):
            release_workflow.fetch_json(f"https://pypi.org/x/{code}")


def test_cli_fails_with_the_recovery_instruction(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gh, registries = _published_release()
    registries.npm = None
    monkeypatch.setattr(release_workflow, "run", gh)
    monkeypatch.setattr(release_workflow, "fetch_json", registries)
    assert (
        release_workflow.main(
            ["--repo", GH_REPO, "check-latest-published", "--run-id", THIS_RUN]
        )
        == 1
    )
    assert "re-run the Release workflow with tag=0.3.278" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# dispatch-checks: retrying the release PR's checks
# ---------------------------------------------------------------------------

WORKFLOWS = ["build.yml", "changelog-lint.yml", "release-pr-checks.yml"]


def _dispatch(gh: FakeGitHub) -> list[str]:
    return release_workflow.dispatch_checks(gh, GH_REPO, BRANCH, WORKFLOWS)


def test_rerun_after_failure_before_dispatching_dispatches_all() -> None:
    # Run 1 updated the release PR, then failed before dispatching. On re-run
    # nothing changes on the branch, but its head has no check runs.
    gh = FakeGitHub()
    assert _dispatch(gh) == WORKFLOWS
    assert gh.dispatches() == WORKFLOWS


def test_rerun_after_only_the_first_dispatches_succeeded_dispatches_the_last() -> None:
    gh = FakeGitHub()
    gh.fail = lambda args: args[:4] == [
        "gh",
        "workflow",
        "run",
        "release-pr-checks.yml",
    ]
    with pytest.raises(ReleaseError, match="release-pr-checks.yml"):
        _dispatch(gh)
    assert gh.dispatches() == ["build.yml", "changelog-lint.yml"]

    gh.fail = lambda args: False
    gh.dispatched.clear()
    assert _dispatch(gh) == ["release-pr-checks.yml"]
    assert gh.dispatches() == ["release-pr-checks.yml"]


def test_a_failed_dispatch_does_not_stop_the_next_one() -> None:
    gh = FakeGitHub()
    gh.fail = lambda args: args[:4] == ["gh", "workflow", "run", "build.yml"]
    with pytest.raises(ReleaseError, match=r"\['build.yml'\]"):
        _dispatch(gh)
    assert "release-pr-checks.yml" in gh.runs


def test_checks_that_already_ran_on_the_head_are_not_dispatched_again() -> None:
    gh = FakeGitHub()
    gh.runs = {
        "build.yml": [1],
        "changelog-lint.yml": [2],
        "release-pr-checks.yml": [3],
    }
    assert _dispatch(gh) == []
    assert gh.dispatches() == []


def test_a_new_head_gets_new_checks() -> None:
    gh = FakeGitHub()
    _dispatch(gh)
    gh.branch_head = "9" * 40
    gh.runs = {}
    assert _dispatch(gh) == WORKFLOWS


def test_cli_reports_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    gh = FakeGitHub()
    monkeypatch.setattr(release_workflow, "run", gh)
    assert (
        release_workflow.main(
            ["--repo", GH_REPO, "resolve-release", "--sha", RELEASE_SHA]
            + ["--requested-tag", "0.3.278"]
        )
        == 1
    )


# ---------------------------------------------------------------------------
# breaking-changes-heading: Release Please's heading, renamed on each update
# ---------------------------------------------------------------------------

GENERATED = "### \u26a0 BREAKING CHANGES"
RENAMED = "### Breaking Changes"
PR_NUMBER = 5900


def _section(version: str, heading: str, previous: str = "0.3.280") -> str:
    return (
        f"## [{version}](https://github.com/{GH_REPO}/compare/{previous}...{version})"
        " (2026-10-15)\n\n\n"
        f"{heading}\n\n"
        "* require Python 3.11 \u2014 see the \u26a0 note ([#5862](x))\n\n"
        "### Features\n\n"
        "* add swarm types ([#5860](x)) ([a11afc9](y))\n"
    )


def _changelog(new_heading: str, old_heading: str = GENERATED) -> str:
    return (
        "# Changelog\n\n"
        + _section("0.3.282", new_heading, "0.3.281")
        + "\n"
        + _section("0.3.281", old_heading)
        + "\n## 0.3.150 (2025-11-02)\n\n- Older hand-written notes.\n"
    )


def _body(heading: str) -> str:
    return (
        "Merging this PR tags the release.\n---\n\n\n"
        + _section("0.3.282", heading, "0.3.281")
        + "\n---\nThis PR was generated with [Release Please](https://github.com/"
        "googleapis/release-please). See [documentation](https://github.com/"
        "googleapis/release-please#release-please)."
    )


class ReleasePRGitHub(FakeGitHub):
    """Adds the release PR, its CHANGELOG.md blob and the writes to FakeGitHub."""

    def __init__(self, changelog: str | None, body: str) -> None:
        super().__init__()
        self.changelog = None if changelog is None else changelog.encode("utf-8")
        self.body = body
        self.open_prs = [(PR_NUMBER, False)]  # (number, from a fork)
        self.commits: list[dict[str, Any]] = []
        self.patches: list[dict[str, Any]] = []

    def _blob_sha(self) -> str:
        assert self.changelog is not None
        return hashlib.sha1(
            b"blob %d\0" % len(self.changelog) + self.changelog
        ).hexdigest()

    def __call__(self, args: Sequence[str]) -> str:
        args = list(args)
        if args[:3] == ["gh", "pr", "list"]:
            self.calls.append(args)
            assert args[args.index("--head") + 1] == BRANCH
            assert args[args.index("--state") + 1] == "open"
            return json.dumps(
                [
                    {"number": n, "body": self.body, "isCrossRepository": fork}
                    for n, fork in self.open_prs
                ]
            )
        if args[:2] == ["gh", "api"] and "--input" in args:
            self.calls.append(args)
            if self.fail(args):
                raise subprocess.CalledProcessError(1, args, stderr=self.fail_stderr)
            payload = json.loads(Path(args[args.index("--input") + 1]).read_text())
            if args[2] == "graphql":
                commit = payload["variables"]["input"]
                assert commit["expectedHeadOid"] == self.branch_head
                (change,) = commit["fileChanges"]["additions"]
                assert change["path"] == "CHANGELOG.md"
                self.changelog = base64.b64decode(change["contents"])
                self.commits.append(commit)
                self.branch_head = f"{len(self.commits):040x}"
                return json.dumps(
                    {"data": {"createCommitOnBranch": {"commit": {"oid": "x"}}}}
                )
            assert args[2:5] == ["-X", "PATCH", f"repos/{GH_REPO}/pulls/{PR_NUMBER}"]
            self.body = payload["body"]
            self.patches.append(payload)
            return "{}"
        if args[:2] == ["gh", "api"] and "/contents/CHANGELOG.md?ref=" in args[2]:
            self.calls.append(args)
            assert args[2].endswith(f"?ref={self.branch_head}")
            if self.changelog is None:
                raise subprocess.CalledProcessError(
                    1, args, stderr="gh: Not Found (HTTP 404)"
                )
            return self._blob_sha() + "\n"
        if args[:2] == ["gh", "api"] and "/git/blobs/" in args[2]:
            self.calls.append(args)
            assert self.changelog is not None
            assert args[2].endswith(self._blob_sha())
            # GitHub wraps the base64 content at 60 characters.
            encoded = base64.b64encode(self.changelog).decode("ascii")
            return "\n".join(encoded[i : i + 60] for i in range(0, len(encoded), 60))
        return super().__call__(args)

    def writes(self) -> int:
        return len(self.commits) + len(self.patches)


def _rename(gh: ReleasePRGitHub) -> list[str]:
    return release_workflow.breaking_changes_heading(gh, GH_REPO, BRANCH)


def test_heading_is_renamed_in_the_body_and_the_newest_changelog_section() -> None:
    gh = ReleasePRGitHub(_changelog(GENERATED), _body(GENERATED))
    assert _rename(gh) == ["CHANGELOG.md", "body"]
    # Everything else is byte-identical, including the older section's
    # heading (hand-fixed releases keep whatever they shipped with).
    assert gh.changelog == _changelog(RENAMED).encode("utf-8")
    assert gh.body == _body(RENAMED)
    (commit,) = gh.commits
    assert commit["branch"] == {
        "repositoryNameWithOwner": GH_REPO,
        "branchName": BRANCH,
    }
    assert re.match(r"chore: ", commit["message"]["headline"])


def test_renaming_again_changes_nothing() -> None:
    gh = ReleasePRGitHub(_changelog(GENERATED), _body(GENERATED))
    _rename(gh)
    head = gh.branch_head
    assert _rename(gh) == []
    assert gh.writes() == 2
    assert gh.branch_head == head


def test_release_without_breaking_changes_is_left_alone() -> None:
    changelog = _changelog("### Bug Fixes", old_heading="### Bug Fixes")
    gh = ReleasePRGitHub(changelog, _body("### Bug Fixes"))
    assert _rename(gh) == []
    assert gh.writes() == 0
    assert gh.changelog == changelog.encode("utf-8")


@pytest.mark.parametrize(
    "line",
    [
        f"{GENERATED} (extra)",
        f"#{GENERATED}",
        f" {GENERATED}",
        "### \u26a0\ufe0f BREAKING CHANGES",
        "### BREAKING CHANGES",
        f"* mentions {GENERATED} inline",
    ],
)
def test_only_the_exact_heading_line_is_renamed(line: str) -> None:
    gh = ReleasePRGitHub(_changelog(line), _body(line))
    assert _rename(gh) == []
    assert gh.writes() == 0


def test_crlf_body_keeps_its_line_endings() -> None:
    body = _body(GENERATED).replace("\n", "\r\n")
    gh = ReleasePRGitHub(_changelog(RENAMED), body)
    assert _rename(gh) == ["body"]
    assert gh.body == _body(RENAMED).replace("\n", "\r\n")
    assert gh.commits == []


def test_already_renamed_changelog_with_generated_body_updates_the_body_only() -> None:
    # A previous run committed the CHANGELOG.md rename but failed on the body.
    gh = ReleasePRGitHub(_changelog(RENAMED), _body(GENERATED))
    assert _rename(gh) == ["body"]
    assert gh.commits == []


def test_no_open_release_pr_changes_nothing() -> None:
    gh = ReleasePRGitHub(_changelog(GENERATED), _body(GENERATED))
    gh.open_prs = []
    assert _rename(gh) == []
    assert [c[:3] for c in gh.calls] == [["gh", "pr", "list"]]


def test_fork_pr_with_the_release_branch_name_is_ignored() -> None:
    gh = ReleasePRGitHub(_changelog(GENERATED), _body(GENERATED))
    gh.open_prs = [(PR_NUMBER - 1, True)]
    assert _rename(gh) == []
    assert gh.writes() == 0


def test_branch_without_a_changelog_still_gets_its_body_renamed() -> None:
    gh = ReleasePRGitHub(None, _body(GENERATED))
    assert _rename(gh) == ["body"]
    assert gh.commits == []


def test_failed_commit_fails_the_command(monkeypatch: pytest.MonkeyPatch) -> None:
    # e.g. Release Please pushed again after the branch head was read.
    gh = ReleasePRGitHub(_changelog(GENERATED), _body(GENERATED))
    gh.fail = lambda args: args[:3] == ["gh", "api", "graphql"]
    gh.fail_stderr = "gh: Expected branch to point to x"
    monkeypatch.setattr(release_workflow, "run", gh)
    assert (
        release_workflow.main(
            ["--repo", GH_REPO, "breaking-changes-heading", "--branch", BRANCH]
        )
        == 1
    )
    assert gh.writes() == 0


# ---------------------------------------------------------------------------
# Workflow wiring
# ---------------------------------------------------------------------------


def _load(path: str) -> dict[Any, Any]:
    loaded = yaml.safe_load((REPO / path).read_text())
    assert isinstance(loaded, dict)
    return loaded


def test_release_jobs_follow_the_resolved_tag() -> None:
    workflow = _load(".github/workflows/release.yml")
    jobs = workflow["jobs"]
    assert jobs["release-please"]["outputs"] == {
        "tag": "${{ steps.resolve.outputs.tag }}"
    }
    assert jobs["build"]["if"] == "needs.release-please.outputs.tag != ''"
    for name in ("publish-pypi", "publish-npm"):
        assert "build" in jobs[name]["needs"]
    assert "release_created" not in json.dumps(
        {k: v for k, v in jobs.items() if k != "release-please"}
    )
    # workflow_dispatch can name a release to finish
    assert "tag" in workflow[True]["workflow_dispatch"]["inputs"]


def test_completeness_check_runs_last_when_nothing_was_resolved() -> None:
    steps = _load(".github/workflows/release.yml")["jobs"]["release-please"]["steps"]
    last = steps[-1]
    assert last["name"] == "Check the latest release is fully published"
    assert last["if"] == "steps.resolve.outputs.tag == ''"
    assert 'check-latest-published --run-id "$GITHUB_RUN_ID"' in last["run"]


def test_tag_dispatch_is_recovery_only() -> None:
    """With a `tag` input, no release is created and the release PR is untouched."""
    job = _load(".github/workflows/release.yml")["jobs"]["release-please"]
    steps = {s.get("id") or s.get("name"): s for s in job["steps"]}
    assert steps["release"]["if"] == "${{ !inputs.tag }}"
    assert steps["pr"]["if"] == "${{ !inputs.tag }}"
    # The release PR step runs only when the (skipped) lookup found an open PR.
    assert steps["Run checks on the release PR"]["if"] == (
        "steps.pr.outputs.open == 'true'"
    )
    resolve = steps["resolve"]
    assert resolve["env"]["REQUESTED_TAG"] == "${{ inputs.tag }}"
    assert "--requested-tag" in resolve["run"]


def test_release_pr_check_dispatch_does_not_depend_on_this_run_changing_the_branch() -> (
    None
):
    steps = _load(".github/workflows/release.yml")["jobs"]["release-please"]["steps"]
    dispatch = next(s for s in steps if s.get("name") == "Run checks on the release PR")
    assert dispatch["if"] == "steps.pr.outputs.open == 'true'"
    assert "dispatch-checks" in dispatch["run"]


PYPI_PUBLISH = "pypa/gh-action-pypi-publish@"


def test_publish_steps_skip_what_the_registries_already_have() -> None:
    action = _load(".github/actions/publish-dist/action.yml")
    names = [s.get("name") for s in action["runs"]["steps"]]
    assert names.index("Verify distributions") < names.index(
        "Skip files already on PyPI"
    )
    assert action["outputs"]["count"]["value"] == "${{ steps.pending.outputs.count }}"

    for workflow, job in [("release.yml", "publish-pypi"), ("publish.yml", "publish")]:
        steps = _load(f".github/workflows/{workflow}")["jobs"][job]["steps"]
        dist = next(i for i, s in enumerate(steps) if s.get("id") == "dist")
        assert steps[dist]["uses"].endswith(".github/actions/publish-dist")
        upload = next(
            i for i, s in enumerate(steps) if s.get("uses", "").startswith(PYPI_PUBLISH)
        )
        assert dist < upload
        assert steps[upload]["if"] == "steps.dist.outputs.count != '0'"


def test_build_dist_builds_with_the_hashed_toolchain() -> None:
    # Without isolation, the build backend is the one installed from the
    # hashed requirements rather than whatever PyPI serves at build time.
    action_dir = REPO / ".github" / "actions" / "build-dist"
    steps = _load(".github/actions/build-dist/action.yml")["runs"]["steps"]
    runs = [s.get("run", "").strip() for s in steps]
    installs = [r for r in runs if "pip install" in r]
    assert installs == [
        'python -m pip install --require-hashes --only-binary :all: --no-deps -r "$REQUIREMENTS"'
    ]
    assert "python -m build --no-isolation" in runs

    # The documented refresh must not keep existing pins as preferences.
    action = (action_dir / "action.yml").read_text()
    refresh = re.search(r"#\s+(uv pip compile .*?-o requirements\.txt)", action, re.S)
    assert refresh
    assert "--upgrade " in refresh.group(1)
    assert '--exclude-newer "7 days"' in refresh.group(1)

    requirements = (action_dir / "requirements.txt").read_text()
    pins = re.findall(r"^([A-Za-z0-9_.-]+)==\S+ \\$", requirements, re.MULTILINE)
    assert {"build", "setuptools", "setuptools-scm"} <= set(pins)
    requirement_lines = [
        line
        for line in requirements.splitlines()
        if line and not line.startswith(("#", " "))
    ]
    assert len(requirement_lines) == len(pins)


def test_dependabot_updates_the_build_toolchain_with_a_cooldown() -> None:
    updates = _load(".github/dependabot.yml")["updates"]
    (update,) = [u for u in updates if u["directory"] == "/.github/actions/build-dist"]
    assert update["package-ecosystem"] == "uv"
    assert update["cooldown"]["default-days"] == 7
    assert update["schedule"]["interval"] == "weekly"
    assert [group["patterns"] for group in update["groups"].values()] == [["*"]]


def test_no_composite_action_runs_the_pypi_publish_docker_action() -> None:
    # pypa/gh-action-pypi-publish is a Docker action, unsupported inside a
    # composite: its image resolves against the calling repo and fails.
    for path in (REPO / ".github" / "actions").glob("*/action.yml"):
        steps = _load(str(path.relative_to(REPO)))["runs"].get("steps", [])
        assert not any(s.get("uses", "").startswith(PYPI_PUBLISH) for s in steps), path


def test_release_publishes_with_this_runs_publish_steps() -> None:
    # A recovery dispatch on main publishes an older tag; the tag's own
    # publish-dist may predate a fix, so the action comes from the run's commit.
    steps = _load(".github/workflows/release.yml")["jobs"]["publish-pypi"]["steps"]
    ci = next(s for s in steps if s.get("with", {}).get("path") == ".ci")
    assert "ref" not in ci["with"]
    assert ci["with"]["sparse-checkout"] == ".github/actions"
    dist = next(s for s in steps if s.get("id") == "dist")
    assert dist["uses"] == "./.ci/.github/actions/publish-dist"

    npm_steps = _load(".github/workflows/npm-publish.yml")["jobs"]["publish"]["steps"]
    publish = next(s for s in npm_steps if s.get("name") == "Publish to NPM")
    assert "steps.npm-version.outputs.published != 'true'" in publish["if"]


def test_release_pr_gets_every_required_check() -> None:
    # Release Please pushes the release PR with GITHUB_TOKEN, so it gets no
    # pull_request runs; each workflow providing a required status check on
    # main must be dispatched on it.
    steps = _load(".github/workflows/release.yml")["jobs"]["release-please"]["steps"]
    dispatch = next(s for s in steps if s.get("name") == "Run checks on the release PR")
    for workflow in ["build.yml", "changelog-lint.yml"]:
        assert workflow in dispatch["run"].split()


def test_release_notes_are_release_pleases() -> None:
    """release.yml changes Release Please's notes only by renaming one heading."""
    workflow = (REPO / ".github" / "workflows" / "release.yml").read_text()
    assert "gh release edit" not in workflow
    assert "release_changelog" not in workflow
    assert not (REPO / ".github" / "scripts" / "release_changelog.py").exists()


def test_heading_is_renamed_before_the_release_pr_checks_are_dispatched() -> None:
    steps = _load(".github/workflows/release.yml")["jobs"]["release-please"]["steps"]
    names = [s.get("id") or s.get("name") for s in steps]
    rename = steps[names.index("Rename the breaking changes heading")]
    assert names.index("pr") < names.index("Rename the breaking changes heading")
    assert names.index("Rename the breaking changes heading") < names.index(
        "Run checks on the release PR"
    )
    assert rename["if"] == "steps.pr.outputs.open == 'true'"
    # A failed rename must not fail the job and skip the publish jobs.
    assert rename["continue-on-error"] is True
    assert rename["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert 'breaking-changes-heading --branch "$RELEASE_BRANCH"' in rename["run"]


# ---------------------------------------------------------------------------
# Changelog Lint: PRs other than the release PR must not edit CHANGELOG.md
# ---------------------------------------------------------------------------

CHANGELOG_LINT = ".github/workflows/changelog-lint.yml"
LINT_STEP = "Check CHANGELOG.md is not edited"


def test_changelog_lint_runs_on_every_pr_and_on_dispatch() -> None:
    # A required check filtered by path would leave PRs that don't touch
    # CHANGELOG.md waiting for a check that never runs.
    workflow = _load(CHANGELOG_LINT)
    triggers = workflow[True]
    assert triggers["pull_request"] is None
    assert "workflow_dispatch" in triggers
    # A dispatched run needs main's history for the merge base. 0 is falsy in
    # expressions, so the depths must be quoted.
    checkout = workflow["jobs"]["lint"]["steps"][0]
    assert checkout["with"]["fetch-depth"] == (
        "${{ github.event_name == 'workflow_dispatch' && '0' || '2' }}"
    )
    # The required check's name: a fixed string, with no matrix or job `if`.
    job = workflow["jobs"]["lint"]
    assert job["name"] == "no-changelog-edits"
    assert "if" not in job and "strategy" not in job


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _lint(
    tmp_path: Path,
    *,
    edit: bool,
    event: str = "pull_request",
    branch: str = "feature",
    head_repo: str = GH_REPO,
) -> subprocess.CompletedProcess[str]:
    """Run the lint step on a PR branch that does or doesn't edit CHANGELOG.md.

    A pull_request run checks out the PR's merge commit; a dispatched run
    checks out the branch with origin/main available.
    """
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## 0.3.278\n\n- x\n")
    (tmp_path / "code.py").write_text("x = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(tmp_path, "checkout", "-qb", branch)
    (tmp_path / "code.py").write_text("x = 2\n")
    if edit:
        (tmp_path / "CHANGELOG.md").write_text(
            "# Changelog\n\n## Unreleased\n\n- y\n\n## 0.3.278\n\n- x\n"
        )
    _git(tmp_path, "commit", "-qam", "change")
    if event == "pull_request":
        # Move main on, so the PR's merge commit has a distinct base parent.
        _git(tmp_path, "checkout", "-q", "main")
        (tmp_path / "other.py").write_text("y = 1\n")
        _git(tmp_path, "add", "other.py")
        _git(tmp_path, "commit", "-qm", "main moves on")
        _git(tmp_path, "merge", "-q", "--no-ff", "-m", "merge", branch)

    steps = _load(CHANGELOG_LINT)["jobs"]["lint"]["steps"]
    step = next(s for s in steps if s.get("name") == LINT_STEP)
    env = {
        **os.environ,
        "EVENT_NAME": event,
        "BRANCH": branch,
        "HEAD_REPO": head_repo if event == "pull_request" else "",
        "RELEASE_BRANCH": step["env"]["RELEASE_BRANCH"],
        "GITHUB_REPOSITORY": GH_REPO,
    }
    return subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )


needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


@needs_bash
@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch"])
def test_changelog_lint_passes_when_changelog_md_is_untouched(
    tmp_path: Path, event: str
) -> None:
    result = _lint(tmp_path, edit=False, event=event)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CHANGELOG.md is unchanged." in result.stdout


@needs_bash
@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch"])
def test_changelog_lint_fails_a_pr_that_edits_changelog_md(
    tmp_path: Path, event: str
) -> None:
    result = _lint(tmp_path, edit=True, event=event)
    assert result.returncode == 1
    assert "::error file=CHANGELOG.md::" in result.stdout
    assert "your PR title is the changelog line" in result.stdout


@needs_bash
@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch"])
def test_changelog_lint_exempts_the_release_pr(tmp_path: Path, event: str) -> None:
    result = _lint(tmp_path, edit=True, event=event, branch=BRANCH)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Release PR" in result.stdout


@needs_bash
def test_changelog_lint_does_not_exempt_a_fork_branch_named_like_the_release_pr(
    tmp_path: Path,
) -> None:
    result = _lint(tmp_path, edit=True, branch=BRANCH, head_repo="someone/inspect_ai")
    assert result.returncode == 1


# ---------------------------------------------------------------------------
# Release Please configuration
# ---------------------------------------------------------------------------

# meridianlabs-ai/inspect_scout's changelog-sections.
CHANGELOG_SECTIONS = [
    {"type": "feat", "section": "Features"},
    {"type": "fix", "section": "Bug Fixes"},
    {"type": "perf", "section": "Performance Improvements"},
    {"type": "revert", "section": "Reverts"},
    {"type": "refactor", "section": "Code Refactoring", "hidden": True},
    {"type": "docs", "section": "Documentation", "hidden": True},
    {"type": "chore", "section": "Miscellaneous", "hidden": True},
    {"type": "build", "section": "Build System", "hidden": True},
    {"type": "ci", "section": "Continuous Integration", "hidden": True},
    {"type": "test", "section": "Tests", "hidden": True},
    {"type": "style", "section": "Styles", "hidden": True},
]


def test_release_please_config_invariants() -> None:
    config = json.loads((REPO / ".release-please-config.json").read_text())
    manifest = json.loads((REPO / ".release-please-manifest.json").read_text())
    package = config["packages"]["."]

    assert config["release-type"] == "python"
    # Bare tags; release-please ignores these two at the top level.
    assert package["include-v-in-tag"] is False
    assert package["include-component-in-tag"] is False
    # Every release is a patch, breaking changes included; a minor or major
    # release is set with a temporary release-as.
    assert package["versioning"] == "always-bump-patch"
    # Inert under always-bump-patch; kept so switching back to default
    # versioning restores the 0.x behavior.
    assert package["bump-minor-pre-major"] is True
    assert package["bump-patch-for-minor-pre-major"] is True
    # Release Please writes CHANGELOG.md.
    assert "skip-changelog" not in package and "skip-changelog" not in config
    assert package["changelog-sections"] == CHANGELOG_SECTIONS
    # package-name or component would change the release branch name from
    # release-please--branches--main, which the workflows refer to.
    assert "package-name" not in package and "component" not in package

    assert list(manifest) == ["."]
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["."])


def test_changelog_md_starts_with_the_title_and_a_release_section() -> None:
    """Release Please inserts each release's section after the `# Changelog` line."""
    lines = (REPO / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# Changelog"
    first_section = next(line for line in lines[1:] if line.strip())
    # Not necessarily the manifest version: a break-glass release adds none.
    assert re.match(r"## \[?\d+\.\d+\.\d+\b", first_section)


def test_release_workflow_passes_no_release_type() -> None:
    """A release-type input puts the action in simple mode, ignoring the config."""
    workflow = (REPO / ".github" / "workflows" / "release.yml").read_text()
    assert "release-type:" not in workflow
    assert "config-file: .release-please-config.json" in workflow
