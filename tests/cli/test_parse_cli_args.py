"""Tests for parse_cli_args -M flag parsing, covering issue #3348.

Verifies that dotted vLLM arguments like `speculative-config.num_speculative_tokens`
are correctly normalized through the CLI layer without mangling nested key segments.
"""

import pytest

from inspect_ai._util.config import parse_cli_args


def test_simple_hyphenated_key() -> None:
    """Top-level hyphenated keys normalize to underscores."""
    result = parse_cli_args(["tool-call-parser=glm47"])
    assert result == {"tool_call_parser": "glm47"}


def test_dotted_key_top_level_hyphen_normalized() -> None:
    """Top-level portion of dotted key: hyphens -> underscores."""
    result = parse_cli_args(["speculative-config.method=mtp"])
    assert result == {"speculative_config.method": "mtp"}


def test_dotted_key_nested_underscores_preserved() -> None:
    """Nested portion of dotted key: underscores must NOT be converted.

    Regression for issue #3348: without the fix, `num_speculative_tokens`
    was converted to `num-speculative-tokens`, breaking pydantic validation
    in vLLM's SpeculativeConfig.
    """
    result = parse_cli_args(["speculative-config.num_speculative_tokens=1"])
    assert result == {"speculative_config.num_speculative_tokens": 1}


def test_dotted_key_integer_value_parsed() -> None:
    """Integer values in dotted args are parsed as int, not str."""
    result = parse_cli_args(["speculative-config.num_speculative_tokens=1"])
    val = result["speculative_config.num_speculative_tokens"]
    assert val == 1
    assert isinstance(val, int)


def test_multiple_m_flags_together() -> None:
    """Multiple -M flags parse correctly as a combined dict."""
    result = parse_cli_args(
        [
            "speculative-config.method=mtp",
            "speculative-config.num_speculative_tokens=1",
            "tool-call-parser=glm47",
        ]
    )
    assert result == {
        "speculative_config.method": "mtp",
        "speculative_config.num_speculative_tokens": 1,
        "tool_call_parser": "glm47",
    }


def test_boolean_flag_without_value_skipped() -> None:
    """Args without '=' (bare flags like enable-auto-tool-choice) are skipped."""
    result = parse_cli_args(["enable-auto-tool-choice"])
    assert result == {}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("alpha,beta", ["alpha", "beta"]),
        ('"alpha,beta"', "alpha,beta"),
        ("'alpha,beta'", "alpha,beta"),
        ('  "alpha,beta" # comment', "alpha,beta"),
        ('!!str "alpha,beta"', "alpha,beta"),
        ('&label "alpha,beta"', "alpha,beta"),
        ("|-\n  alpha,beta", "alpha,beta"),
        (">-\n  alpha,beta", "alpha,beta"),
        ('"alpha=one,beta=two"', "alpha=one,beta=two"),
        ('"alpha,\\nbeta"', "alpha,\nbeta"),
        ('["alpha,beta", "gamma"]', ["alpha,beta", "gamma"]),
        ('{"label": "alpha,beta"}', {"label": "alpha,beta"}),
        ('"true"', "true"),
        ("true", True),
        ("12", 12),
        ("null", None),
        ('""', ""),
    ],
)
@pytest.mark.parametrize("force_str", [False, True])
def test_comma_lists_and_yaml_values(
    raw: str, expected: object, force_str: bool
) -> None:
    """Only plain strings use the comma-separated list shorthand."""
    assert parse_cli_args([f"label={raw}"], force_str=force_str) == {
        "label": str(expected) if force_str else expected
    }
