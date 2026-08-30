"""Tests for the suppression ledger gate (.github/scripts/check_suppressions.py).

Mostly pure-logic tests over the scanner and ledger diffing, plus a few CLI
tests that run the script against a throwaway git repo. Directive examples
live inside string literals, which the tokenize-based scanner never counts,
so this file adds nothing to the ledger.
"""

import importlib.util
import pathlib
import subprocess
import sys

SCRIPTS_DIR = pathlib.Path(__file__).parents[1] / ".github" / "scripts"

spec = importlib.util.spec_from_file_location(
    "check_suppressions", SCRIPTS_DIR / "check_suppressions.py"
)
assert spec is not None and spec.loader is not None
cs = importlib.util.module_from_spec(spec)
# Register before exec so suppressions_pr_delta.py's `import
# check_suppressions` resolves to this instance when loaded below.
sys.modules["check_suppressions"] = cs
spec.loader.exec_module(cs)


def scan(source: str) -> list[tuple[str, bool]]:
    return [(s.rule, s.described) for s in cs.scan_source(source)]


# --- scanner: ruff noqa ---


def test_noqa_with_code_and_reason_segment() -> None:
    assert scan("x = 1  # noqa: E501  # long URL\n") == [("noqa:E501", True)]


def test_noqa_with_code_no_reason() -> None:
    assert scan("x = 1  # noqa: E501\n") == [("noqa:E501", False)]


def test_noqa_multiple_codes_count_separately() -> None:
    assert scan("import a, b  # noqa: E402, F401\n") == [
        ("noqa:E402", False),
        ("noqa:F401", False),
    ]


def test_noqa_em_dash_reason() -> None:
    assert scan("f()  # noqa: BLE001 — never crash the loop\n") == [
        ("noqa:BLE001", True)
    ]


def test_noqa_double_dash_reason() -> None:
    assert scan("f()  # noqa: BLE001 -- best effort\n") == [("noqa:BLE001", True)]


def test_bare_noqa_keys_separately() -> None:
    assert scan("x = 1  # noqa\n") == [("noqa", False)]


def test_noqa_case_insensitive() -> None:
    assert scan("x = 1  # NOQA: E501\n") == [("noqa:E501", False)]


def test_noqa_prefix_of_word_ignored() -> None:
    assert scan("x = 1  # noqable\n") == []


def test_file_wide_ruff_noqa() -> None:
    assert scan("# ruff: noqa\n") == [("noqa (file-wide)", False)]


def test_file_wide_ruff_noqa_with_space_separated_codes() -> None:
    assert scan("# ruff: noqa: F401 F403\n") == [
        ("noqa:F401 (file-wide)", False),
        ("noqa:F403 (file-wide)", False),
    ]


def test_file_wide_flake8_noqa() -> None:
    assert scan("# flake8: noqa\n") == [("noqa (file-wide)", False)]


def test_file_wide_noqa_loose_spellings_honored_by_ruff() -> None:
    # ruff honors the noqa token in any case and whitespace around the
    # colons (all verified against the pinned ruff); miss these and a
    # whole-file suppression lands with no ledger entry.
    for text in (
        "# ruff: NOQA\n",
        "# ruff: Noqa\n",
        "# ruff : noqa\n",
        "#ruff : noqa\n",
        "# flake8 : noqa\n",
    ):
        assert scan(text) == [("noqa (file-wide)", False)], text
    assert scan("# ruff: NOQA: F401\n") == [("noqa:F401 (file-wide)", False)]


def test_file_wide_noqa_uppercase_prefix_is_inert() -> None:
    # ruff ignores an uppercase prefix ("RUFF: NOQA" suppresses nothing,
    # verified), and the scanner matches nothing either: the file-level
    # prefix is case-sensitive on purpose, and the line-level noqa branch
    # requires the token to open a comment segment.
    assert scan("# RUFF: NOQA\n") == []


def test_trailing_file_wide_noqa_is_inert() -> None:
    # ruff warns ("File-level suppression comments must appear on their own
    # line") and suppresses nothing (verified), for either spelling.
    assert scan("x = 1  # ruff: noqa\n") == []
    assert scan("x = 1  # flake8: noqa\n") == []


def test_file_wide_noqa_mid_comment_is_inert() -> None:
    # Own line, but the directive doesn't open the comment: ruff silently
    # ignores it (verified).
    assert scan("# prose  # ruff: noqa\nimport os\n") == []


# --- scanner: mypy ---


def test_type_ignore_bare() -> None:
    assert scan("x = f()  # type: ignore\n") == [("type: ignore", False)]


def test_type_ignore_with_code_and_reason_segment() -> None:
    assert scan("x = f()  # type: ignore[assignment]  # stub is wrong\n") == [
        ("type: ignore[assignment]", True)
    ]


def test_type_ignore_multiple_codes() -> None:
    assert scan("x = f()  # type: ignore[method-assign, assignment]\n") == [
        ("type: ignore[method-assign]", False),
        ("type: ignore[assignment]", False),
    ]


def test_type_ignore_no_space_variant() -> None:
    assert scan("x = f()  #type:ignore[arg-type]\n") == [
        ("type: ignore[arg-type]", False)
    ]


def test_type_ignore_word_prefix_ignored() -> None:
    assert scan("x = 1  # type: ignored by design\n") == []


def test_type_ignore_mid_comment_is_inert() -> None:
    # mypy only honors type: ignore when it opens the comment.
    assert scan("x = f()  # prose  # type: ignore\n") == []


def test_double_hash_type_ignore_is_inert() -> None:
    assert scan("## type: ignore\nimport x\n") == []


def test_type_ignore_after_legacy_type_comment_counts() -> None:
    # mypy honors the trailing ignore of a legacy type comment (verified),
    # so it must be counted or it would evade the ledger.
    assert scan("x = f()  # type: List[int]  # type: ignore\n") == [
        ("type: ignore", False)
    ]
    assert scan("x = f()  # type: List[int]  # type: ignore[assignment]\n") == [
        ("type: ignore[assignment]", False)
    ]


def test_type_ignore_after_legacy_type_comment_with_reason_segment() -> None:
    assert scan("x = f()  # type: List[int]  # type: ignore  # stub is wrong\n") == [
        ("type: ignore", True)
    ]


def test_type_ignore_after_legacy_type_comment_with_prose_between_is_inert() -> None:
    # mypy honors the ignore only as the type comment's first embedded
    # segment (verified: a prose segment in between defeats it).
    assert scan("x = f()  # type: List[int]  # prose  # type: ignore\n") == []


def test_legacy_type_comment_in_preamble_is_not_file_wide() -> None:
    # An own-line legacy type comment before any code is a mypy syntax
    # error (verified), so its trailing ignore must not upgrade to the
    # module-wide form the way a bare preamble type: ignore does.
    assert scan("# type: List[int]  # type: ignore\nimport x\n") == [
        ("type: ignore", False)
    ]


def test_duplicate_type_ignore_counts_once_and_is_not_a_reason() -> None:
    assert scan("x = f()  # type: ignore  # type: ignore\n") == [
        ("type: ignore", False)
    ]


def test_type_ignore_trailing_prose_is_not_a_reason() -> None:
    # mypy rejects the directive outright when bare prose follows it, so
    # prose there is a broken comment, not a reason.
    assert scan("x = f()  # type: ignore stub is wrong\n") == [("type: ignore", False)]


def test_type_ignore_space_before_bracket() -> None:
    # mypy honors and scopes the code despite the space (verified).
    assert scan("x = f()  # type: ignore [assignment]\n") == [
        ("type: ignore[assignment]", False)
    ]


def test_bare_type_ignore_at_top_of_file_is_file_wide() -> None:
    # A bare own-line type: ignore before any code or docstring silences
    # the whole module in mypy, even indented (verified).
    assert scan("# type: ignore\nimport x\n") == [("type: ignore (file-wide)", False)]
    assert scan("    # type: ignore\nimport x\n") == [
        ("type: ignore (file-wide)", False)
    ]


def test_type_ignore_after_docstring_is_not_file_wide() -> None:
    assert scan('"""Doc."""\nx = f()  # type: ignore\n') == [("type: ignore", False)]


def test_bracketed_type_ignore_at_top_of_file_stays_line_level() -> None:
    # mypy errors on the bracketed form at module level rather than
    # treating it as file-wide.
    assert scan("# type: ignore[assignment]\nimport x\n") == [
        ("type: ignore[assignment]", False)
    ]


def test_mypy_ignore_errors_file_wide() -> None:
    assert scan("# mypy: ignore-errors\n") == [
        ("mypy: ignore-errors (file-wide)", False)
    ]


def test_trailing_mypy_config_comment_is_inert() -> None:
    # mypy config comments are honored only on a line of their own; a
    # trailing one suppresses nothing (verified).
    assert scan("x = 1  # mypy: ignore-errors\n") == []


def test_mid_file_own_line_mypy_config_comment_counts() -> None:
    # Own-line placement is what matters, not top-of-file (verified: a
    # mid-file `# mypy: ignore-errors` suppresses the module).
    assert scan("x = 1\n# mypy: ignore-errors\ny = 2\n") == [
        ("mypy: ignore-errors (file-wide)", False)
    ]


def test_indented_mypy_config_comment_is_inert() -> None:
    # mypy config comments must start at column 0: an indented own-line
    # one suppresses nothing (verified for both forms).
    assert scan("if x:\n    # mypy: ignore-errors\n    pass\n") == []
    assert scan('if x:\n    # mypy: disable-error-code="assignment"\n    pass\n') == []


def test_indented_file_level_noqa_still_counts() -> None:
    # Unlike mypy config comments, ruff honors an indented own-line
    # file-level noqa comment (verified: it suppresses file-wide).
    assert scan("if x:\n    # ruff: noqa\n    pass\n") == [("noqa (file-wide)", False)]


def test_mypy_disable_error_code_file_wide() -> None:
    assert scan('# mypy: disable-error-code="unused-ignore"\n') == [
        ("mypy: disable-error-code[unused-ignore] (file-wide)", False)
    ]


def test_mypy_prose_comment_not_a_directive() -> None:
    assert scan("# mypy: passing None would require Optional here\n") == []


# --- scanner: pyright ---


def test_pyright_ignore_with_rules() -> None:
    assert scan(
        "x = f()  # pyright: ignore[reportUnknownMemberType,reportPrivateUsage]\n"
    ) == [
        ("pyright: ignore[reportUnknownMemberType]", False),
        ("pyright: ignore[reportPrivateUsage]", False),
    ]


def test_pyright_mode_comment_not_a_directive() -> None:
    assert scan("# pyright: basic\n") == []


# --- scanner: reasons and comment structure ---


def test_directive_following_directive_is_not_a_reason() -> None:
    assert scan("x = f()  # type: ignore  # noqa: E501\n") == [
        ("type: ignore", False),
        ("noqa:E501", False),
    ]


def test_separator_only_tail_is_not_a_reason() -> None:
    assert scan("x = f()  # type: ignore  # --- #\n") == [("type: ignore", False)]


def test_directive_text_in_string_literal_ignored() -> None:
    assert scan('s = "x  # noqa: E501"\n') == []


def test_directive_mid_prose_without_hash_ignored() -> None:
    assert scan("# remove the type: ignore below once fixed\n") == []


def test_directive_after_prose_comment_counts_but_prose_is_not_a_reason() -> None:
    # ruff honors a noqa directive opening a later segment of the comment;
    # a reason must FOLLOW the directive (preceding prose describes the code).
    assert scan("x = 1  # legacy import  # noqa: F401\n") == [("noqa:F401", False)]


# --- ledger building ---


def test_build_ledger_tallies_sorts_and_omits_empty() -> None:
    S = cs.Suppression
    ledger = cs.build_ledger(
        {
            "b.py": [S("r", False), S("r", True)],
            "a.py": [S("r", True)],
            "empty.py": [],
        }
    )
    assert ledger == {
        "a.py": {"r": {"count": 1}},
        "b.py": {"r": {"count": 2, "undescribed": 1}},
    }
    assert list(ledger.keys()) == ["a.py", "b.py"]


# --- diffing ---


def test_diff_ledgers_reports_growth_and_shrink() -> None:
    diffs = cs.diff_ledgers(
        {"a.py": {"r": {"count": 2}}, "gone.py": {"r": {"count": 1}}},
        {"a.py": {"r": {"count": 3}}},
    )
    assert [(d.before.total, d.after.total) for d in diffs] == [(2, 3), (1, 0)]


def test_diff_ledgers_reports_undescribed_only_change() -> None:
    diffs = cs.diff_ledgers(
        {"a.py": {"r": {"count": 2, "undescribed": 2}}},
        {"a.py": {"r": {"count": 2, "undescribed": 1}}},
    )
    assert [(d.before.undescribed, d.after.undescribed) for d in diffs] == [(2, 1)]


def test_diff_ledgers_empty_on_match() -> None:
    ledger = {"a.py": {"r": {"count": 1}}}
    assert cs.diff_ledgers(ledger, ledger) == []


# --- ratchet ---


def test_ratchet_flags_undescribed_growth_allows_shrink_and_described_growth() -> None:
    ledger = {"a.py": {"r": {"count": 2, "undescribed": 2}}}
    grow = {"a.py": {"r": {"count": 3, "undescribed": 3}}}
    described_grow = {"a.py": {"r": {"count": 3, "undescribed": 2}}}
    shrink = {"a.py": {"r": {"count": 1, "undescribed": 1}}}
    assert len(cs.ratchet_violations(ledger, grow)) == 1
    assert cs.ratchet_violations(ledger, described_grow) == []
    assert cs.ratchet_violations(ledger, shrink) == []


def test_ratchet_flags_new_file_with_undescribed_suppression() -> None:
    assert (
        len(
            cs.ratchet_violations({}, {"new.py": {"r": {"count": 1, "undescribed": 1}}})
        )
        == 1
    )


def test_ratchet_is_per_rule_across_files_so_a_move_does_not_trip_it() -> None:
    assert (
        cs.ratchet_violations(
            {"old.py": {"r": {"count": 2, "undescribed": 2}}},
            {"new.py": {"r": {"count": 2, "undescribed": 2}}},
        )
        == []
    )


def test_line_to_file_wide_swap_is_a_ledger_diff_but_not_a_ratchet_trip() -> None:
    ledger = {"a.py": {"noqa:F401": {"count": 1, "undescribed": 1}}}
    actual = {"a.py": {"noqa:F401 (file-wide)": {"count": 1, "undescribed": 1}}}
    assert [d.key[1] for d in cs.diff_ledgers(ledger, actual)] == [
        "noqa:F401",
        "noqa:F401 (file-wide)",
    ]
    assert cs.ratchet_violations(ledger, actual) == []


def test_ratchet_still_fires_when_a_move_also_adds_a_reasonless_suppression() -> None:
    assert cs.ratchet_violations(
        {"old.py": {"r": {"count": 2, "undescribed": 2}}},
        {"new.py": {"r": {"count": 3, "undescribed": 3}}},
    ) == [cs.RatchetViolation("r", 2, 3)]


# --- totals ---


def test_totals_sums_counts_and_undescribed() -> None:
    assert cs.totals(
        {
            "a.py": {"r": {"count": 2, "undescribed": 1}, "s": {"count": 1}},
            "b.py": {"r": {"count": 3, "undescribed": 3}},
        }
    ) == cs.Counts(6, 4)


# --- PR delta comment (suppressions_pr_delta.py) ---

delta_spec = importlib.util.spec_from_file_location(
    "suppressions_pr_delta", SCRIPTS_DIR / "suppressions_pr_delta.py"
)
assert delta_spec is not None and delta_spec.loader is not None
delta = importlib.util.module_from_spec(delta_spec)
delta_spec.loader.exec_module(delta)


def render(base: dict, head: dict) -> str | None:
    body = delta.render(base, head)
    assert body is None or isinstance(body, str)
    return body


def test_delta_renders_nothing_when_unchanged() -> None:
    ledger = {"a.py": {"r": {"count": 1, "undescribed": 1}}}
    assert render(ledger, ledger) is None


def test_delta_growth_renders_marker_warning_row_and_footer() -> None:
    body = render({}, {"a.py": {"r": {"count": 1}}})
    assert body is not None
    assert body.startswith(delta.MARKER)
    assert "⚠️ Suppression ledger grew: 0 → 1 (+1)" in body
    assert "| `a.py` | `r` | +1 |" in body
    assert "maintainer sign-off" in body


def test_delta_shrink_renders_plain_heading_without_footer() -> None:
    body = render(
        {"a.py": {"r": {"count": 2}}},
        {"a.py": {"r": {"count": 1}}},
    )
    assert body is not None
    assert "Suppression ledger changed: 2 → 1 (-1)" in body
    assert "maintainer sign-off" not in body


def test_delta_undescribed_only_change_still_renders() -> None:
    body = render(
        {"a.py": {"r": {"count": 1, "undescribed": 1}}},
        {"a.py": {"r": {"count": 1}}},
    )
    assert body is not None
    assert "| `a.py` | `r` | ±0 (reason-less 1 → 0) |" in body
    assert "Reason-less (baselined) suppressions: 1 → 0" in body


# --- CLI: bootstrap, ratchet refusal, and --allow-growth (throwaway git repo) ---


def _init_repo(tmp_path: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    # ls-files only sees tracked files; staging suffices (no commit needed).
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def _run_gate(repo: pathlib.Path, *args: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "check_suppressions.py"), *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def test_update_bootstrap_ratchet_refusal_and_allow_growth(
    tmp_path: pathlib.Path,
) -> None:
    repo = _init_repo(tmp_path, {"a.py": "x = 1  # noqa: E501\n"})

    # Bootstrap --update captures the baseline and says the ratchet was skipped.
    boot = _run_gate(repo, "--update")
    assert boot.returncode == 0
    assert "ratchet not applied" in boot.stdout

    # A second reason-less suppression: --update refuses via the ratchet
    # and points at the sanctioned override.
    (repo / "a.py").write_text("x = 1  # noqa: E501\ny = 2  # noqa: E501\n")
    refused = _run_gate(repo, "--update")
    assert refused.returncode == 1
    assert "UNDESCRIBED: noqa:E501" in refused.stderr
    assert "--allow-growth" in refused.stderr

    # --allow-growth records the growth, loudly.
    allowed = _run_gate(repo, "--update", "--allow-growth")
    assert allowed.returncode == 0
    assert "ALLOWED GROWTH: noqa:E501" in allowed.stderr
    assert _run_gate(repo).returncode == 0


def test_allow_growth_without_update_is_an_error(tmp_path: pathlib.Path) -> None:
    repo = _init_repo(tmp_path, {})
    result = _run_gate(repo, "--allow-growth")
    assert result.returncode == 2
    assert "--update" in result.stderr


def test_unknown_argument_is_an_error(tmp_path: pathlib.Path) -> None:
    # A typo'd flag must not silently fall through to check mode.
    repo = _init_repo(tmp_path, {})
    result = _run_gate(repo, "--updat")
    assert result.returncode == 2
    assert "--updat" in result.stderr


def test_pyi_stubs_are_scanned(tmp_path: pathlib.Path) -> None:
    repo = _init_repo(tmp_path, {"a.pyi": "x: int  # type: ignore[assignment]\n"})
    result = _run_gate(repo, "--update")
    assert result.returncode == 0
    assert '"a.pyi"' in (repo / "suppressions.json").read_text()
