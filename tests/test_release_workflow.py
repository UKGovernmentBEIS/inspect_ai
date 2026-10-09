"""Tests for the retry paths of the Release workflow.

Covers .github/scripts/release_workflow.py with a fake `gh`/`git`, and the
parts of release.yml and the publish steps that make re-runs safe. The PyPI
skip-already-published step is tested with the other pypi-release.py tests in
tests/tools/sandbox_tools_utils/test_sandbox_tools_digests.py.
"""

from __future__ import annotations

import importlib.util
import json
import re
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
        self.bodies: dict[str, str] = {}  # tag -> GitHub Release body
        self.changelogs: dict[str, str] = {}  # tag -> CHANGELOG.md at the tag
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
                return json.dumps(
                    {"tag_name": self.latest, "body": self.bodies.get(self.latest)}
                )
            if "/contents/CHANGELOG.md?ref=" in path:
                tag = path.rsplit("=", 1)[1]
                if tag not in self.changelogs:
                    raise not_found
                return self.changelogs[tag]
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

NOTES = "- Fixed a thing.\n"
CHANGELOG_0_3_278 = f"## Unreleased\n\n## 0.3.278 (12 October 2026)\n\n{NOTES}"
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
    gh.changelogs["0.3.278"] = CHANGELOG_0_3_278
    gh.bodies["0.3.278"] = NOTES
    gh.release_runs = [{"databaseId": int(THIS_RUN), "status": "in_progress"}]
    return gh, FakeRegistries()


def _check(gh: FakeGitHub, registries: FakeRegistries) -> str:
    return release_workflow.check_latest_published(gh, registries, GH_REPO, THIS_RUN)


def test_all_jobs_retry_of_a_release_created_on_an_earlier_commit_fails() -> None:
    """The pass-3 sequence: created on an earlier merge SHA, retried on a later one."""
    gh, registries = _published_release()
    # Attempt 1 ran on LATER_SHA and created 0.3.278 on the release PR's merge
    # commit (RELEASE_SHA); its build failed, so nothing was published and the
    # release keeps Release Please's generated notes.
    assert _resolve(gh, sha=LATER_SHA, created_tag="0.3.278") == "0.3.278"
    registries.pypi = None
    registries.npm = None
    gh.bodies["0.3.278"] = "## 0.3.278\n\n### Bug Fixes\n\n* generated"

    # Attempt 2 (Re-run all jobs): Release Please reports nothing.
    assert _resolve(gh, sha=LATER_SHA) == ""
    with pytest.raises(release_workflow.IncompleteRelease) as error:
        _check(gh, registries)
    assert str(error.value) == (
        "Release 0.3.278 exists but is not fully published (missing its PyPI "
        "wheel and sdist, its npm package, its CHANGELOG.md release notes); "
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
        (
            lambda gh, r: gh.bodies.update({"0.3.278": "generated notes"}),
            "its CHANGELOG.md release notes",
        ),
    ],
    ids=["pypi-missing", "sdist-missing", "npm-missing", "notes-missing"],
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


def test_release_notes_with_crlf_line_endings_count_as_curated() -> None:
    gh, registries = _published_release()
    gh.bodies["0.3.278"] = NOTES.replace("\n", "\r\n")
    assert _check(gh, registries) == "0.3.278"


def test_no_release_or_a_non_release_please_release_is_not_checked() -> None:
    gh, registries = _published_release()
    gh.latest = None
    assert _check(gh, registries) == ""
    gh, registries = _published_release()
    gh.manifests["0.3.278"] = "0.3.277"  # e.g. a break-glass release
    registries.pypi = None
    assert _check(gh, registries) == ""


def test_unreadable_changelog_section_does_not_block_every_run() -> None:
    """An empty section fails the release-notes job, which no retry can fix."""
    gh, registries = _published_release()
    gh.changelogs["0.3.278"] = "## Unreleased\n\n## 0.3.278 (12 October 2026)\n"
    gh.bodies["0.3.278"] = "generated"
    assert _check(gh, registries) == "0.3.278"


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
        "changelog",
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
        "changelog": "/contents/CHANGELOG.md",
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

WORKFLOWS = ["build.yml", "release-pr-checks.yml"]


def _dispatch(gh: FakeGitHub) -> list[str]:
    return release_workflow.dispatch_checks(gh, GH_REPO, BRANCH, WORKFLOWS)


def test_rerun_after_failure_following_the_changelog_push_dispatches_both() -> None:
    # Run 1 pushed the changelog commit, then failed before dispatching. On
    # re-run nothing changes on the branch, but its head has no check runs.
    gh = FakeGitHub()
    assert _dispatch(gh) == WORKFLOWS
    assert gh.dispatches() == WORKFLOWS


def test_rerun_after_only_the_first_dispatch_succeeded_dispatches_the_second() -> None:
    gh = FakeGitHub()
    gh.fail = lambda args: args[:4] == [
        "gh",
        "workflow",
        "run",
        "release-pr-checks.yml",
    ]
    with pytest.raises(ReleaseError, match="release-pr-checks.yml"):
        _dispatch(gh)
    assert gh.dispatches() == ["build.yml"]

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
    gh.runs = {"build.yml": [1], "release-pr-checks.yml": [2]}
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
    for name in ("release-notes", "build"):
        assert jobs[name]["if"] == "needs.release-please.outputs.tag != ''"
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
    # The release PR steps run only when the (skipped) lookup found an open PR.
    for name in (
        "Release CHANGELOG.md entries on the release PR",
        "Run checks on the release PR",
    ):
        assert steps[name]["if"] == "steps.pr.outputs.open == 'true'"
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


def test_publish_steps_skip_what_the_registries_already_have() -> None:
    action = _load(".github/actions/publish-dist/action.yml")
    steps = action["runs"]["steps"]
    names = [s.get("name") for s in steps]
    assert (
        names.index("Verify distributions")
        < names.index("Skip files already on PyPI")
        < names.index("Publish to PyPI")
    )
    assert steps[names.index("Publish to PyPI")]["if"] == (
        "steps.pending.outputs.count != '0'"
    )

    npm_steps = _load(".github/workflows/npm-publish.yml")["jobs"]["publish"]["steps"]
    publish = next(s for s in npm_steps if s.get("name") == "Publish to NPM")
    assert "steps.npm-version.outputs.published != 'true'" in publish["if"]
