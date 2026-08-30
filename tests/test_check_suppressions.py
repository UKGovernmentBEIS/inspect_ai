"""Tests for the suppression ledger gate (.github/scripts/check_suppressions.py).

Pure-logic tests over the scanner and ledger diffing — no git, no filesystem.
Directive examples live inside string literals, which the tokenize-based
scanner never counts, so this file adds nothing to the ledger.
"""

import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "check_suppressions",
    pathlib.Path(__file__).parents[1] / ".github" / "scripts" / "check_suppressions.py",
)
assert spec is not None and spec.loader is not None
cs = importlib.util.module_from_spec(spec)
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


def test_mypy_ignore_errors_file_wide() -> None:
    assert scan("# mypy: ignore-errors\n") == [
        ("mypy: ignore-errors (file-wide)", False)
    ]


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
