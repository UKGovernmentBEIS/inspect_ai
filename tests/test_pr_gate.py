"""Tests for the PR gate (.github/scripts/pr_gate.py).

No network: decision-core tests are pure logic, and the fetch and
enforcement layers run against a fake `gh` that records the calls.
"""

import importlib.util
import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "pr_gate", REPO / ".github" / "scripts" / "pr_gate.py"
)
assert spec is not None and spec.loader is not None
pr_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr_gate)


LOCAL_REPO = "UKGovernmentBEIS/inspect_ai"
FOREIGN_REPO = "someone-else/their-fork"


def issue(labels=None, author="issue-author", repo=LOCAL_REPO):
    """A linked closing issue as fetch_ctx shapes it (not the PR author unless a test says so)."""
    return {"author": author, "repo": repo, "labels": labels or []}


def make_ctx(**overrides):
    ctx = {
        "repo": LOCAL_REPO,  # GH_REPO: the PR's base repository
        "author": "somebody",
        "author_id": 999999,
        "author_association": "NONE",
        "pr_labels": [],
        "files": [{"filename": "src/inspect_ai/x.py", "additions": 40, "deletions": 3}],
        # closing issues: [{"author": login, "repo": nameWithOwner, "labels": [...]}]
        "linked_issues": [],
        "qualified_users": {111222},  # account ids from .github/qualified.yml
    }
    ctx.update(overrides)
    return ctx


# --- qualified.yml parsing (strict line format, numeric account ids) ---


def test_parse_qualified():
    text = "# comment\n\nusers:\n  - 111222\n  - 333444\n"
    users = pr_gate.parse_qualified(text)
    assert users == {111222, 333444}


def test_parse_qualified_non_numeric_entry_raises():
    with pytest.raises(ValueError, match="numeric"):
        pr_gate.parse_qualified("users:\n  - somelogin\n")


# --- trivial carve-out ---


def test_docs_include_fix_is_trivial():
    files = [{"filename": "docs/_tools-basics.md", "additions": 1, "deletions": 1}]
    assert pr_gate.is_trivial(files)


def test_readme_typo_fix_is_trivial():
    assert pr_gate.is_trivial(
        [{"filename": "README.md", "additions": 1, "deletions": 1}]
    )


def test_trivial_docs_only_small_diff():
    files = [
        {"filename": "README.md", "additions": 2, "deletions": 1},
        {"filename": "docs/eval.qmd", "additions": 5, "deletions": 0},
    ]
    assert pr_gate.is_trivial(files)


def test_not_trivial_when_code_touched():
    files = [{"filename": "src/inspect_ai/x.py", "additions": 1, "deletions": 0}]
    assert not pr_gate.is_trivial(files)


def test_not_trivial_when_diff_large():
    files = [{"filename": "README.md", "additions": 30, "deletions": 0}]
    assert not pr_gate.is_trivial(files)


def test_trivial_empty_file_list_is_not_trivial():
    assert not pr_gate.is_trivial([])


@pytest.mark.parametrize(
    "filename",
    [
        "docs/_quarto.yml",
        "docs/filters/callout.lua",
        "docs/scripts/build.py",
        "docs/js/site.js",
        "AGENTS.md",
        "CLAUDE.md",
        "src/inspect_sandbox_tools/AGENTS.md",
        "AGENTS.override.md",
        "GEMINI.md",
        "examples/skills/skills/disk-usage/SKILL.md",
        "CONTRIBUTING.md",
        "design/sandbox-trust-model.md",
        "src/inspect_ai/README.md",
        "docs/AGENTS.md",
        "docs/guides/AGENTS.override.md",
        "docs/CHANGELOG.md",
        ".agents/skills/slow-tests/SKILL.md",
        ".github/pull_request_template.md",
    ],
)
def test_small_edit_outside_docs_prose_is_not_trivial(filename):
    files = [{"filename": filename, "additions": 1, "deletions": 1}]
    assert not pr_gate.is_trivial(files)
    v = pr_gate.decide(make_ctx(files=files))
    assert v.verdict == "close" and v.tier == "needs-issue"


def test_one_line_extensions_listing_is_trivial():
    files = [
        {"filename": "docs/extensions/extensions.yml", "additions": 6, "deletions": 0}
    ]
    assert pr_gate.is_trivial(files)


def test_rename_from_code_into_docs_is_not_trivial():
    files = [
        {
            "filename": "docs/notes.qmd",
            "previous_filename": "src/inspect_ai/x.py",
            "status": "renamed",
            "additions": 1,
            "deletions": 0,
        }
    ]
    assert not pr_gate.is_trivial(files)


def test_rename_within_docs_with_a_small_edit_is_trivial():
    files = [
        {
            "filename": "docs/new-name.qmd",
            "previous_filename": "docs/old-name.qmd",
            "status": "renamed",
            "additions": 1,
            "deletions": 1,
        }
    ]
    assert pr_gate.is_trivial(files)


@pytest.mark.parametrize(
    "change",
    [
        # mode change: GitHub reports no changed lines, as for a binary file
        {"filename": "docs/eval.qmd", "status": "changed"},
        # pure rename
        {
            "filename": "docs/b.qmd",
            "previous_filename": "docs/a.qmd",
            "status": "renamed",
        },
    ],
)
def test_change_without_changed_lines_is_not_trivial(change):
    files = [{"additions": 0, "deletions": 0, **change}]
    assert not pr_gate.is_trivial(files)


def test_gate_rechecks_when_files_or_body_change():
    workflow = yaml.safe_load(
        (REPO / ".github" / "workflows" / "pr-gate.yml").read_text()
    )
    # PyYAML reads the bare `on` key as True.
    types = workflow[True]["pull_request_target"]["types"]
    assert {"synchronize", "edited"} <= set(types)
    env = workflow["jobs"]["gate"]["steps"][-1]["env"]
    assert env["PR_EVENT_ACTION"] == "${{ github.event.action }}"


# --- decision core: pass if ANY check holds ---


def test_team_passes_as_qualified():
    v = pr_gate.decide(make_ctx(author_association="MEMBER"))
    assert v.verdict == "pass" and v.tier == "qualified"


def test_collaborator_passes_as_qualified():
    v = pr_gate.decide(make_ctx(author_association="COLLABORATOR"))
    assert v.verdict == "pass" and v.tier == "qualified"


def test_listed_account_id_passes():
    v = pr_gate.decide(make_ctx(author_id=111222))
    assert v.verdict == "pass" and v.tier == "qualified"


def test_unlisted_account_id_fails():
    v = pr_gate.decide(make_ctx(author_id=31337))
    assert v.verdict == "close"


def test_qualified_label_passes():
    v = pr_gate.decide(make_ctx(pr_labels=["qualified"]))
    assert v.verdict == "pass" and v.tier == "qualified"


def test_prior_merge_history_grants_nothing():
    # There is deliberately no "established" tier: merged-PR history does not
    # exempt anyone from the accepted-issue requirement. (An obsolete ctx key
    # is ignored rather than honored.)
    v = pr_gate.decide(make_ctx(has_prior_nontrivial_merge=True))
    assert v.verdict == "close" and v.tier == "needs-issue"


def test_trivial_docs_pr_passes():
    v = pr_gate.decide(
        make_ctx(files=[{"filename": "README.md", "additions": 2, "deletions": 0}])
    )
    assert v.verdict == "pass" and v.tier == "trivial"


def test_accepted_linked_issue_passes():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["accepted"])]))
    assert v.verdict == "pass" and v.tier == "issue-approved"


def test_good_first_issue_implies_accepted():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["good first issue"])]))
    assert v.verdict == "pass" and v.tier == "issue-approved"


def test_unknown_author_no_issue_fails():
    v = pr_gate.decide(make_ctx())
    assert v.verdict == "close"
    assert v.tier == "needs-issue"


def test_linked_issue_without_accepted_fails():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["enhancement"])]))
    assert v.verdict == "close" and v.tier == "needs-issue"


def test_self_filed_accepted_issue_passes():
    # Who filed the issue is irrelevant — only the `accepted` label matters.
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["accepted"], author="somebody")]))
    assert v.verdict == "pass" and v.tier == "issue-approved"


def test_self_filed_unaccepted_issue_fails():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(author="somebody")]))
    assert v.verdict == "close" and v.tier == "needs-issue"


# --- deferred veto: a deferred linked issue closes the PR for every
# automatic pass; only the human-vouched qualified tier goes through ---


def test_deferred_linked_issue_closes():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["deferred"])]))
    assert v.verdict == "close" and v.tier == "deferred"


def test_deferred_overrides_accepted_on_same_issue():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["accepted", "deferred"])]))
    assert v.verdict == "close" and v.tier == "deferred"


def test_deferred_overrides_trivial_carveout():
    v = pr_gate.decide(
        make_ctx(
            files=[{"filename": "README.md", "additions": 2, "deletions": 0}],
            linked_issues=[issue(["deferred"])],
        )
    )
    assert v.verdict == "close" and v.tier == "deferred"


def test_deferred_label_is_case_insensitive():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["Deferred"])]))
    assert v.verdict == "close" and v.tier == "deferred"


def test_team_passes_despite_deferred():
    v = pr_gate.decide(
        make_ctx(author_association="MEMBER", linked_issues=[issue(["deferred"])])
    )
    assert v.verdict == "pass" and v.tier == "qualified"


def test_listed_account_passes_despite_deferred():
    v = pr_gate.decide(make_ctx(author_id=111222, linked_issues=[issue(["deferred"])]))
    assert v.verdict == "pass" and v.tier == "qualified"


def test_qualified_label_passes_despite_deferred():
    v = pr_gate.decide(
        make_ctx(pr_labels=["qualified"], linked_issues=[issue(["deferred"])])
    )
    assert v.verdict == "pass" and v.tier == "qualified"


# --- mixed linked issues: any accepted issue passes, whoever filed what ---


def test_unaccepted_plus_other_accepted_issue_passes():
    v = pr_gate.decide(
        make_ctx(
            linked_issues=[
                issue(author="somebody"),
                issue(["accepted"], author="someone-else"),
            ]
        )
    )
    assert v.verdict == "pass" and v.tier == "issue-approved"


def test_trivial_passes_despite_unaccepted_issue():
    v = pr_gate.decide(
        make_ctx(
            files=[{"filename": "README.md", "additions": 2, "deletions": 0}],
            linked_issues=[issue(author="somebody")],
        )
    )
    assert v.verdict == "pass" and v.tier == "trivial"


# --- repository provenance: only labels on issues in the PR's base repo
# grant acceptance or force deferral; a closing reference can point anywhere ---


def test_local_accepted_issue_passes():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["accepted"], repo=LOCAL_REPO)]))
    assert v.verdict == "pass" and v.tier == "issue-approved"


def test_local_deferred_issue_closes():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["deferred"], repo=LOCAL_REPO)]))
    assert v.verdict == "close" and v.tier == "deferred"


def test_foreign_accepted_issue_grants_nothing():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["accepted"], repo=FOREIGN_REPO)]))
    assert v.verdict == "close" and v.tier == "needs-issue"


def test_foreign_good_first_issue_grants_nothing():
    v = pr_gate.decide(
        make_ctx(linked_issues=[issue(["good first issue"], repo=FOREIGN_REPO)])
    )
    assert v.verdict == "close" and v.tier == "needs-issue"


def test_foreign_deferred_issue_does_not_veto():
    # A foreign `deferred` neither vetoes nor grants: the PR is judged as if
    # the issue were not linked (here: trivial carve-out still passes).
    v = pr_gate.decide(
        make_ctx(
            files=[{"filename": "README.md", "additions": 2, "deletions": 0}],
            linked_issues=[issue(["deferred"], repo=FOREIGN_REPO)],
        )
    )
    assert v.verdict == "pass" and v.tier == "trivial"


def test_foreign_deferred_alone_is_needs_issue_not_deferred():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["deferred"], repo=FOREIGN_REPO)]))
    assert v.verdict == "close" and v.tier == "needs-issue"


def test_local_accepted_with_foreign_deferred_passes():
    v = pr_gate.decide(
        make_ctx(
            linked_issues=[
                issue(["deferred"], repo=FOREIGN_REPO),
                issue(["accepted"], repo=LOCAL_REPO),
            ]
        )
    )
    assert v.verdict == "pass" and v.tier == "issue-approved"


def test_local_deferred_with_foreign_accepted_closes_as_deferred():
    v = pr_gate.decide(
        make_ctx(
            linked_issues=[
                issue(["accepted"], repo=FOREIGN_REPO),
                issue(["deferred"], repo=LOCAL_REPO),
            ]
        )
    )
    assert v.verdict == "close" and v.tier == "deferred"


def test_local_unaccepted_with_foreign_accepted_needs_issue():
    v = pr_gate.decide(
        make_ctx(
            linked_issues=[
                issue(["enhancement"], repo=LOCAL_REPO),
                issue(["accepted"], repo=FOREIGN_REPO),
            ]
        )
    )
    assert v.verdict == "close" and v.tier == "needs-issue"


def test_repo_comparison_is_case_insensitive():
    v = pr_gate.decide(
        make_ctx(
            repo="ukgovernmentbeis/inspect_ai",
            linked_issues=[issue(["accepted"], repo="UKGovernmentBEIS/Inspect_AI")],
        )
    )
    assert v.verdict == "pass" and v.tier == "issue-approved"


def test_issue_without_repo_provenance_grants_nothing():
    accepted = {"author": "issue-author", "labels": ["accepted"]}
    v = pr_gate.decide(make_ctx(linked_issues=[accepted]))
    assert v.verdict == "close" and v.tier == "needs-issue"


def test_issue_without_repo_provenance_does_not_veto():
    deferred = {"author": "issue-author", "repo": None, "labels": ["deferred"]}
    v = pr_gate.decide(make_ctx(linked_issues=[deferred]))
    assert v.verdict == "close" and v.tier == "needs-issue"


def test_team_passes_despite_foreign_issues():
    v = pr_gate.decide(
        make_ctx(
            author_association="MEMBER",
            linked_issues=[issue(["deferred"], repo=FOREIGN_REPO)],
        )
    )
    assert v.verdict == "pass" and v.tier == "qualified"


# --- close comment ---


def test_close_comment_has_marker_and_both_doors():
    body = pr_gate.close_comment()
    assert pr_gate.COMMENT_MARKER in body
    assert "issue" in body and "extension" in body


def test_deferred_close_comment_is_distinct_and_marked():
    body = pr_gate.deferred_close_comment()
    assert pr_gate.COMMENT_MARKER in body
    assert "deferred" in body
    assert body != pr_gate.close_comment()


# --- grandfathering ---


def test_pr_created_before_policy_is_grandfathered():
    # POLICY_START is the qualified-or-accepted policy's adoption date;
    # everything open before it (including the original 7/29 dry-run cohort)
    # stays ungated even across stale-close/reopen cycles.
    assert pr_gate.is_grandfathered("2026-08-31T06:43:25Z")


def test_pr_created_after_policy_is_not_grandfathered():
    assert not pr_gate.is_grandfathered("2026-09-01T00:00:01Z")


def test_pr_created_at_policy_start_is_not_grandfathered():
    assert not pr_gate.is_grandfathered(pr_gate.POLICY_START)


# --- fetch layer: linked issues carry their repository ---


def graphql_response(nodes):
    return {
        "data": {
            "repository": {"pullRequest": {"closingIssuesReferences": {"nodes": nodes}}}
        }
    }


def test_fetch_ctx_records_linked_issue_repository(monkeypatch, tmp_path):
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "qualified.yml").write_text("users:\n  - 111222\n")
    monkeypatch.chdir(tmp_path)

    def fake_gh_json(*args):
        if args[0].endswith("/files"):
            return [{"filename": "src/inspect_ai/x.py", "additions": 1, "deletions": 0}]
        if args[0].endswith("/labels"):
            return [{"name": "Bug"}]
        assert args[0] == "graphql"
        return graphql_response(
            [
                {
                    "author": {"login": "issue-author"},
                    "repository": {"nameWithOwner": LOCAL_REPO},
                    "labels": {"nodes": [{"name": "accepted"}]},
                },
                {
                    "author": None,
                    "repository": {"nameWithOwner": FOREIGN_REPO},
                    "labels": {"nodes": [{"name": "deferred"}]},
                },
            ]
        )

    monkeypatch.setattr(pr_gate, "gh_json", fake_gh_json)
    ctx = pr_gate.fetch_ctx(LOCAL_REPO, 42, "somebody", 999999, "NONE")

    assert ctx["repo"] == LOCAL_REPO
    assert ctx["pr_labels"] == ["bug"]
    assert ctx["qualified_users"] == {111222}
    assert ctx["linked_issues"] == [
        {"author": "issue-author", "repo": LOCAL_REPO, "labels": ["accepted"]},
        {"author": None, "repo": FOREIGN_REPO, "labels": ["deferred"]},
    ]
    assert pr_gate.decide(ctx).tier == "issue-approved"


# --- enforcement: a close verdict closes the PR unless it changed during the
# run; the explanatory comment is skipped only when a reopened PR already has
# one, and only the gate's own comment counts as posted ---


def gate_comment(body=None):
    return {
        "user": {"login": pr_gate.COMMENT_AUTHOR, "type": "Bot"},
        "body": body if body is not None else pr_gate.close_comment(),
    }


def user_comment(login, body):
    return {"user": {"login": login, "type": "User"}, "body": body}


def test_is_gate_comment_requires_gate_author_and_marker():
    assert pr_gate.is_gate_comment(gate_comment())
    assert not pr_gate.is_gate_comment(gate_comment(body="unrelated bot output"))
    assert not pr_gate.is_gate_comment(
        user_comment("somebody", pr_gate.close_comment())
    )
    assert not pr_gate.is_gate_comment(
        user_comment("somebody", f"{pr_gate.COMMENT_MARKER} pasted marker")
    )
    assert not pr_gate.is_gate_comment({"body": pr_gate.close_comment()})
    assert not pr_gate.is_gate_comment({"user": None, "body": None})


HEAD_SHA = "a" * 40


def live(
    sha,
    state="open",
    draft=False,
    body="Fixes #1",
    base="main",
    fork_pushed_at="2026-11-23T10:00:00Z",
    labels=(),
):
    """The PR as GET /pulls/N returns it, with some of the fork metadata."""
    return {
        "head": {"sha": sha, "repo": {"pushed_at": fork_pushed_at}},
        "base": {"ref": base},
        "state": state,
        "draft": draft,
        "body": body,
        "labels": [{"name": name} for name in labels],
    }


class FakeGitHub:
    """Stands in for the gate's `gh`/`gh_json` calls and records what it is told."""

    def __init__(self, ctx, comments, prs=(None,)):
        self.ctx = ctx
        self.comments = comments
        # successive answers for the live PR; the last one repeats
        self.prs = [pr or live(HEAD_SHA) for pr in prs]
        self.calls: list[tuple[str, ...]] = []

    def fetch_ctx(self, repo, pr_number, author, author_id, assoc):
        assert repo == self.ctx["repo"]
        return self.ctx

    def gh_json(self, *args):
        if args[0].endswith("/pulls/42"):
            return self.prs.pop(0) if len(self.prs) > 1 else self.prs[0]
        assert args[0].endswith("/comments"), args
        return self.comments

    def gh(self, *args):
        self.calls.append(args)

    @property
    def posted_comments(self):
        return [c for c in self.calls if c[1].endswith("/comments")]

    @property
    def closed(self):
        return any("state=closed" in c for c in self.calls)

    @property
    def labels_added(self):
        return [c[-1] for c in self.calls if c[1].endswith("/labels")]


def run_gate(
    monkeypatch,
    ctx,
    comments=(),
    dry_run="false",
    prs=(None,),
    action="opened",
):
    fake = FakeGitHub(ctx, list(comments), prs)
    monkeypatch.setattr(pr_gate, "fetch_ctx", fake.fetch_ctx)
    monkeypatch.setattr(pr_gate, "gh_json", fake.gh_json)
    monkeypatch.setattr(pr_gate, "gh", fake.gh)
    monkeypatch.setenv("GH_REPO", ctx["repo"])
    monkeypatch.setenv("PR_NUMBER", "42")
    monkeypatch.setenv("PR_AUTHOR", ctx["author"])
    monkeypatch.setenv("PR_AUTHOR_ID", str(ctx["author_id"]))
    monkeypatch.setenv("PR_AUTHOR_ASSOC", ctx["author_association"])
    monkeypatch.setenv("PR_CREATED_AT", "2026-09-15T12:00:00Z")
    monkeypatch.setenv("PR_EVENT_ACTION", action)
    monkeypatch.setenv("DRY_RUN", dry_run)
    assert pr_gate.main() == 0
    return fake


def test_close_verdict_comments_and_closes(monkeypatch):
    fake = run_gate(monkeypatch, make_ctx())
    assert len(fake.posted_comments) == 1
    assert pr_gate.COMMENT_MARKER in fake.posted_comments[0][-1]
    assert fake.closed


def test_deferred_close_uses_deferred_comment(monkeypatch):
    fake = run_gate(monkeypatch, make_ctx(linked_issues=[issue(["deferred"])]))
    assert len(fake.posted_comments) == 1
    assert fake.posted_comments[0][-1] == f"body={pr_gate.deferred_close_comment()}"
    assert fake.closed


def test_reopened_pr_with_gate_comment_is_closed_without_new_comment(monkeypatch):
    # The PR was closed by the gate once and reopened unchanged: close it
    # again, but do not repeat the explanation.
    fake = run_gate(
        monkeypatch, make_ctx(), comments=[gate_comment()], action="reopened"
    )
    assert fake.posted_comments == []
    assert fake.closed


@pytest.mark.parametrize("action", ["synchronize", "edited"])
def test_recheck_close_explains_itself_despite_an_earlier_gate_comment(
    monkeypatch, action
):
    # The PR was closed once, reopened with an accepted issue and passed; a
    # later push or edit made it fail again.
    fake = run_gate(
        monkeypatch,
        make_ctx(linked_issues=[issue(["deferred"])]),
        comments=[gate_comment()],
        action=action,
    )
    assert fake.posted_comments[0][-1] == f"body={pr_gate.deferred_close_comment()}"
    assert fake.closed


def test_failing_pr_is_left_for_the_newer_run_when_its_body_changed(monkeypatch):
    # An edit during the run may have linked an accepted issue.
    fake = run_gate(
        monkeypatch,
        make_ctx(),
        prs=(live(HEAD_SHA), live(HEAD_SHA, body="Fixes #2")),
    )
    assert not fake.closed
    assert fake.posted_comments == []


def test_failing_pr_is_left_for_the_newer_run_when_retargeted(monkeypatch):
    fake = run_gate(
        monkeypatch,
        make_ctx(),
        prs=(live(HEAD_SHA), live(HEAD_SHA, base="release/1.0")),
    )
    assert not fake.closed
    assert fake.posted_comments == []


def test_push_to_another_branch_of_the_fork_does_not_skip_the_close(monkeypatch):
    fake = run_gate(
        monkeypatch,
        make_ctx(),
        prs=(live(HEAD_SHA), live(HEAD_SHA, fork_pushed_at="2026-11-23T10:05:00Z")),
    )
    assert fake.closed
    assert len(fake.posted_comments) == 1


def test_failing_pr_endorsed_during_the_run_is_not_closed(monkeypatch):
    fake = run_gate(
        monkeypatch,
        make_ctx(),
        prs=(live(HEAD_SHA), live(HEAD_SHA, labels=["Qualified"])),
    )
    assert not fake.closed
    assert fake.posted_comments == []


def test_reopened_pr_without_gate_comment_explains_itself(monkeypatch):
    fake = run_gate(monkeypatch, make_ctx(), action="reopened")
    assert len(fake.posted_comments) == 1
    assert fake.closed


def test_unrelated_marker_comment_does_not_count_as_gate_comment(monkeypatch):
    # Someone else's comment carrying the marker is not the gate's output: the
    # gate still explains itself, and still closes.
    fake = run_gate(
        monkeypatch,
        make_ctx(),
        comments=[user_comment("somebody", pr_gate.close_comment())],
        action="reopened",
    )
    assert len(fake.posted_comments) == 1
    assert fake.closed


def test_gate_author_comment_without_marker_does_not_count(monkeypatch):
    fake = run_gate(
        monkeypatch,
        make_ctx(),
        comments=[gate_comment(body="some other bot output")],
        action="reopened",
    )
    assert len(fake.posted_comments) == 1
    assert fake.closed


def test_foreign_accepted_issue_is_enforced(monkeypatch):
    fake = run_gate(
        monkeypatch,
        make_ctx(linked_issues=[issue(["accepted"], repo=FOREIGN_REPO)]),
    )
    assert len(fake.posted_comments) == 1
    assert fake.posted_comments[0][-1] == f"body={pr_gate.close_comment()}"
    assert fake.closed


def test_pass_verdict_does_not_close(monkeypatch):
    fake = run_gate(monkeypatch, make_ctx(linked_issues=[issue(["accepted"])]))
    assert fake.posted_comments == []
    assert not fake.closed
    assert fake.labels_added == []


def test_qualified_pass_labels_without_closing(monkeypatch):
    fake = run_gate(monkeypatch, make_ctx(author_association="MEMBER"))
    assert fake.labels_added == ["labels[]=qualified"]
    assert not fake.closed


def test_dry_run_labels_instead_of_closing(monkeypatch):
    fake = run_gate(monkeypatch, make_ctx(), dry_run="true")
    assert fake.labels_added == ["labels[]=gate-dry-run"]
    assert fake.posted_comments == []
    assert not fake.closed


def test_failing_pr_is_left_for_the_newer_run_when_its_head_moved(monkeypatch):
    fake = run_gate(monkeypatch, make_ctx(), prs=(live(HEAD_SHA), live("b" * 40)))
    assert not fake.closed
    assert fake.posted_comments == []


def test_gate_runs_only_on_open_ready_prs():
    workflow = yaml.safe_load(
        (REPO / ".github" / "workflows" / "pr-gate.yml").read_text()
    )
    condition = workflow["jobs"]["gate"]["if"]
    assert "github.event.pull_request.draft == false" in condition
    assert "github.event.pull_request.state == 'open'" in condition
    assert " && " in condition and "||" not in condition


@pytest.mark.parametrize(
    "now",
    [live(HEAD_SHA, state="closed"), live(HEAD_SHA, draft=True)],
    ids=["closed", "draft"],
)
def test_queued_run_leaves_a_pr_that_is_no_longer_open_and_ready(monkeypatch, now):
    # The run was queued while the PR was open and ready; an earlier run
    # closed it, a maintainer closed it, or the author made it a draft.
    fake = run_gate(monkeypatch, make_ctx(), prs=(now,), action="edited")
    assert not fake.closed
    assert fake.posted_comments == []
