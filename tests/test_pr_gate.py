"""Tests for the PR gate decision core (.github/scripts/pr_gate.py).

Pure-logic tests only — no network. The fetch layer is exercised in the
gate's two-week dry run, not here.
"""

import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "pr_gate", pathlib.Path(__file__).parents[1] / ".github" / "scripts" / "pr_gate.py"
)
assert spec is not None and spec.loader is not None
pr_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr_gate)


def issue(labels=None, author="issue-author"):
    """A linked closing issue as fetch_ctx shapes it (not the PR author unless a test says so)."""
    return {"author": author, "labels": labels or []}


def make_ctx(**overrides):
    ctx = {
        "author": "somebody",
        "author_id": 999999,
        "author_association": "NONE",
        "pr_labels": [],
        "files": [{"filename": "src/inspect_ai/x.py", "additions": 40, "deletions": 3}],
        "linked_issues": [],  # closing issues: [{"author": login, "labels": [...]}]
        "qualified_users": {111222},  # account ids from .github/qualified.yml
        "has_prior_nontrivial_merge": False,
        "open_prs": 0,  # author's OTHER open PRs in this repo (excludes this one)
    }
    ctx.update(overrides)
    return ctx


# --- qualified.yml parsing (strict line format, numeric account ids) ---


def test_parse_qualified():
    text = "# comment\n\nusers:\n  - 111222\n  - 333444\n"
    users = pr_gate.parse_qualified(text)
    assert users == {111222, 333444}


def test_parse_qualified_non_numeric_entry_raises():
    import pytest

    with pytest.raises(ValueError, match="numeric"):
        pr_gate.parse_qualified("users:\n  - somelogin\n")


# --- trivial carve-out ---


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


def test_prior_nontrivial_merge_passes_as_established():
    v = pr_gate.decide(make_ctx(has_prior_nontrivial_merge=True))
    assert v.verdict == "pass" and v.tier == "established"


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
    assert v.tier == "new"


def test_linked_issue_without_accepted_fails():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["enhancement"])]))
    assert v.verdict == "close"


# --- deferred veto: a deferred linked issue closes the PR for every
# automatic pass; only the human-vouched qualified tier goes through ---


def test_deferred_linked_issue_fails_established_author():
    v = pr_gate.decide(
        make_ctx(has_prior_nontrivial_merge=True, linked_issues=[issue(["deferred"])])
    )
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


# --- self-filed veto: an issue the PR author filed themselves doesn't
# establish demand — the PR needs that issue (or another linked issue)
# labeled `accepted`, whatever the author's tier. Trivial stays welcome,
# qualified outranks, deferred is the more informative close ---


def test_self_filed_unaccepted_issue_closes_established_author():
    v = pr_gate.decide(
        make_ctx(
            has_prior_nontrivial_merge=True,
            linked_issues=[issue(author="somebody")],
        )
    )
    assert v.verdict == "close" and v.tier == "self-filed"


def test_self_filed_unaccepted_issue_closes_new_author_as_self_filed():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(author="somebody")]))
    assert v.verdict == "close" and v.tier == "self-filed"


def test_self_filed_issue_with_accepted_passes():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["accepted"], author="somebody")]))
    assert v.verdict == "pass" and v.tier == "issue-approved"


def test_self_filed_plus_other_accepted_issue_passes():
    v = pr_gate.decide(
        make_ctx(
            linked_issues=[
                issue(author="somebody"),
                issue(["accepted"], author="someone-else"),
            ]
        )
    )
    assert v.verdict == "pass" and v.tier == "issue-approved"


def test_team_passes_despite_self_filed():
    v = pr_gate.decide(
        make_ctx(author_association="MEMBER", linked_issues=[issue(author="somebody")])
    )
    assert v.verdict == "pass" and v.tier == "qualified"


def test_trivial_passes_despite_self_filed():
    v = pr_gate.decide(
        make_ctx(
            files=[{"filename": "README.md", "additions": 2, "deletions": 0}],
            linked_issues=[issue(author="somebody")],
        )
    )
    assert v.verdict == "pass" and v.tier == "trivial"


def test_deferred_reported_over_self_filed():
    v = pr_gate.decide(make_ctx(linked_issues=[issue(["deferred"], author="somebody")]))
    assert v.verdict == "close" and v.tier == "deferred"


def test_self_filed_reported_over_capped():
    v = pr_gate.decide(
        make_ctx(
            has_prior_nontrivial_merge=True,
            open_prs=9,
            linked_issues=[issue(author="somebody")],
        )
    )
    assert v.verdict == "close" and v.tier == "self-filed"


def test_self_filed_close_comment_is_distinct_and_marked():
    body = pr_gate.self_filed_close_comment()
    assert pr_gate.COMMENT_MARKER in body
    assert "accepted" in body
    assert "reopen" in body.lower()
    assert body != pr_gate.close_comment()
    assert body != pr_gate.deferred_close_comment()


# --- open-PR cap: the Established tier's "may open PRs directly" privilege
# is bounded at OPEN_PR_CAP open PRs; the other pass paths are not (trivial
# stays always-welcome, an accepted issue is maintainer-approved demand, and
# qualified is a human vouch) ---


def test_established_at_cap_is_closed():
    v = pr_gate.decide(
        make_ctx(has_prior_nontrivial_merge=True, open_prs=pr_gate.OPEN_PR_CAP)
    )
    assert v.verdict == "close" and v.tier == "capped"


def test_established_just_under_cap_passes():
    v = pr_gate.decide(
        make_ctx(has_prior_nontrivial_merge=True, open_prs=pr_gate.OPEN_PR_CAP - 1)
    )
    assert v.verdict == "pass" and v.tier == "established"


def test_cap_is_five():
    assert pr_gate.OPEN_PR_CAP == 5


def test_team_passes_despite_cap():
    v = pr_gate.decide(make_ctx(author_association="MEMBER", open_prs=20))
    assert v.verdict == "pass" and v.tier == "qualified"


def test_accepted_issue_passes_despite_cap():
    v = pr_gate.decide(
        make_ctx(
            has_prior_nontrivial_merge=True,
            linked_issues=[issue(["accepted"])],
            open_prs=9,
        )
    )
    assert v.verdict == "pass" and v.tier == "issue-approved"


def test_trivial_passes_despite_cap():
    v = pr_gate.decide(
        make_ctx(
            files=[{"filename": "README.md", "additions": 2, "deletions": 0}],
            has_prior_nontrivial_merge=True,
            open_prs=9,
        )
    )
    assert v.verdict == "pass" and v.tier == "trivial"


def test_deferred_reported_over_capped():
    v = pr_gate.decide(
        make_ctx(
            has_prior_nontrivial_merge=True,
            linked_issues=[issue(["deferred"])],
            open_prs=9,
        )
    )
    assert v.verdict == "close" and v.tier == "deferred"


def test_new_author_over_cap_still_reports_new():
    v = pr_gate.decide(make_ctx(open_prs=9))
    assert v.verdict == "close" and v.tier == "new"


def test_capped_close_comment_is_distinct_and_marked():
    body = pr_gate.capped_close_comment(6)
    assert pr_gate.COMMENT_MARKER in body
    assert str(pr_gate.OPEN_PR_CAP) in body
    assert "reopen" in body.lower()
    assert body != pr_gate.close_comment()
    assert body != pr_gate.deferred_close_comment()


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
    assert pr_gate.is_grandfathered("2026-07-28T06:43:25Z")


def test_pr_created_after_policy_is_not_grandfathered():
    assert not pr_gate.is_grandfathered("2026-07-30T00:00:00Z")


def test_pr_created_at_policy_start_is_not_grandfathered():
    assert not pr_gate.is_grandfathered(pr_gate.POLICY_START)
