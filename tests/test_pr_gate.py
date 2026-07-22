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
        "trusted_users": {"rasmusfaber": 2798829},  # login (lower) -> pinned id
        "trusted_orgs": {},  # slug (lower) -> pinned id
        "is_public_org_member": False,  # fetch layer verifies org id before setting
        "has_prior_nontrivial_merge": False,
    }
    ctx.update(overrides)
    return ctx


# --- trusted.yml parsing (strict line format, mandatory id pins) ---


def test_parse_trusted():
    text = (
        "# comment\n\nusers:\n  - RasmusFaber  # id=2798829\n"
        "  - anthonyduong9  # id=42191920\n\norgs: []\n"
    )
    users, orgs = pr_gate.parse_trusted(text)
    assert users == {"rasmusfaber": 2798829, "anthonyduong9": 42191920}
    assert orgs == {}


def test_parse_trusted_with_orgs():
    text = "users:\n  - a  # id=1\norgs:\n  - METR  # id=115503932\n"
    users, orgs = pr_gate.parse_trusted(text)
    assert orgs == {"metr": 115503932}


def test_parse_trusted_missing_id_raises():
    import pytest

    with pytest.raises(ValueError, match="id"):
        pr_gate.parse_trusted("users:\n  - noidhere\n")


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


def test_team_passes_as_trusted():
    v = pr_gate.decide(make_ctx(author_association="MEMBER"))
    assert v.verdict == "pass" and v.tier == "trusted"


def test_collaborator_passes_as_trusted():
    v = pr_gate.decide(make_ctx(author_association="COLLABORATOR"))
    assert v.verdict == "pass" and v.tier == "trusted"


def test_trusted_list_user_passes_case_insensitive():
    v = pr_gate.decide(make_ctx(author="RasmusFaber", author_id=2798829))
    assert v.verdict == "pass" and v.tier == "trusted"


def test_trusted_login_with_wrong_id_fails():
    # username-squatting defense: right login, wrong immutable account id
    v = pr_gate.decide(make_ctx(author="rasmusfaber", author_id=31337))
    assert v.verdict == "close"


def test_public_org_member_passes_as_trusted():
    v = pr_gate.decide(
        make_ctx(trusted_orgs={"metr": 115503932}, is_public_org_member=True)
    )
    assert v.verdict == "pass" and v.tier == "trusted"


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


# --- close comment ---


def test_close_comment_has_marker_and_both_doors():
    body = pr_gate.close_comment(dry_run=False)
    assert pr_gate.COMMENT_MARKER in body
    assert "issue" in body and "extension" in body


def test_dry_run_comment_says_would_close():
    body = pr_gate.close_comment(dry_run=True)
    assert "would have been closed" in body
