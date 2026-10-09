"""Tests for the retry paths of the Release workflow.

Covers .github/scripts/release_workflow.py with a fake `gh`/`git`, and the
parts of release.yml and the publish steps that make re-runs safe. The PyPI
skip-already-published step is tested with the other pypi-release.py tests in
tests/tools/sandbox_tools_utils/test_sandbox_tools_digests.py.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
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
        self.calls: list[list[str]] = []
        self.dispatched: list[str] = []

    def add_release(self, tag: str, commit: str, **flags: bool) -> None:
        self.tags[tag] = commit
        self.releases[tag] = {"isDraft": False, "isPrerelease": False, **flags}
        self.manifests[tag] = tag
        self.on_main.add(tag)

    def __call__(self, args: Sequence[str]) -> str:
        args = list(args)
        self.calls.append(args)
        if self.fail(args):
            raise subprocess.CalledProcessError(1, args, stderr="simulated failure")
        if args[:2] == ["git", "ls-remote"]:
            lines = []
            for tag, commit in self.tags.items():
                if tag in self.annotated:
                    lines.append(f"{'f' * 40}\trefs/tags/{tag}")
                    lines.append(f"{commit}\trefs/tags/{tag}^{{}}")
                else:
                    lines.append(f"{commit}\trefs/tags/{tag}")
            return "\n".join(lines) + "\n"
        if args[:3] == ["gh", "release", "view"]:
            if args[3] not in self.releases:
                raise subprocess.CalledProcessError(1, args, stderr="release not found")
            return json.dumps(self.releases[args[3]])
        if args[:2] == ["gh", "api"]:
            path = args[2]
            if ".release-please-manifest.json?ref=" in path:
                tag = path.rsplit("=", 1)[1]
                if tag not in self.manifests:
                    raise subprocess.CalledProcessError(1, args, stderr="Not Found")
                return json.dumps({".": self.manifests[tag]})
            if "/compare/main..." in path:
                return (
                    "behind\n"
                    if path.rsplit("...", 1)[1] in self.on_main
                    else ("ahead\n")
                )
            if path.endswith(f"/branches/{BRANCH}"):
                return self.branch_head + "\n"
        if args[:3] == ["gh", "run", "list"]:
            workflow = args[args.index("--workflow") + 1]
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
            lambda gh: gh.releases["0.3.278"].update(isPrerelease=True),
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
            lambda gh: gh.releases["0.3.278"].update(isDraft=True),
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
