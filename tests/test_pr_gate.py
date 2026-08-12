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


def make_ctx(**overrides):
    ctx = {
        "author": "somebody",
        "author_id": 999999,
        "author_association": "NONE",
        "pr_labels": [],
        "files": [{"filename": "src/inspect_ai/x.py", "additions": 40, "deletions": 3}],
        "linked_issue_labels": [],  # flattened labels across all closing issues
        "qualified_users": {111222},  # account ids from .github/qualified.yml
        "has_prior_nontrivial_merge": False,
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
    v = pr_gate.decide(make_ctx(linked_issue_labels=["accepted"]))
    assert v.verdict == "pass" and v.tier == "issue-approved"


def test_good_first_issue_implies_accepted():
    v = pr_gate.decide(make_ctx(linked_issue_labels=["good first issue"]))
    assert v.verdict == "pass" and v.tier == "issue-approved"


def test_unknown_author_no_issue_fails():
    v = pr_gate.decide(make_ctx())
    assert v.verdict == "close"
    assert v.tier == "new"


def test_linked_issue_without_accepted_fails():
    v = pr_gate.decide(make_ctx(linked_issue_labels=["enhancement"]))
    assert v.verdict == "close"


# --- deferred veto: a deferred linked issue closes the PR for every
# automatic pass; only the human-vouched qualified tier goes through ---


def test_deferred_linked_issue_fails_established_author():
    v = pr_gate.decide(
        make_ctx(has_prior_nontrivial_merge=True, linked_issue_labels=["deferred"])
    )
    assert v.verdict == "close" and v.tier == "deferred"


def test_deferred_overrides_accepted_on_same_issue():
    v = pr_gate.decide(make_ctx(linked_issue_labels=["accepted", "deferred"]))
    assert v.verdict == "close" and v.tier == "deferred"


def test_deferred_overrides_trivial_carveout():
    v = pr_gate.decide(
        make_ctx(
            files=[{"filename": "README.md", "additions": 2, "deletions": 0}],
            linked_issue_labels=["deferred"],
        )
    )
    assert v.verdict == "close" and v.tier == "deferred"


def test_deferred_label_is_case_insensitive():
    v = pr_gate.decide(make_ctx(linked_issue_labels=["Deferred"]))
    assert v.verdict == "close" and v.tier == "deferred"


def test_team_passes_despite_deferred():
    v = pr_gate.decide(
        make_ctx(author_association="MEMBER", linked_issue_labels=["deferred"])
    )
    assert v.verdict == "pass" and v.tier == "qualified"


def test_listed_account_passes_despite_deferred():
    v = pr_gate.decide(make_ctx(author_id=111222, linked_issue_labels=["deferred"]))
    assert v.verdict == "pass" and v.tier == "qualified"


def test_qualified_label_passes_despite_deferred():
    v = pr_gate.decide(
        make_ctx(pr_labels=["qualified"], linked_issue_labels=["deferred"])
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
    assert pr_gate.is_grandfathered("2026-07-28T06:43:25Z")


def test_pr_created_after_policy_is_not_grandfathered():
    assert not pr_gate.is_grandfathered("2026-07-30T00:00:00Z")


def test_pr_created_at_policy_start_is_not_grandfathered():
    assert not pr_gate.is_grandfathered(pr_gate.POLICY_START)
