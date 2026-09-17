"""Tests for parse_cli_args -M flag parsing, covering issue #3348.

Verifies that dotted vLLM arguments like `speculative-config.num_speculative_tokens`
are correctly normalized through the CLI layer without mangling nested key segments.
"""

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


def test_comma_value_split_into_list_by_default() -> None:
    """By default a comma-containing string value is split into a list."""
    result = parse_cli_args(["hosts=a,b,c"])
    assert result == {"hosts": ["a", "b", "c"]}


def test_comma_value_preserved_when_split_lists_false() -> None:
    """With split_lists=False a comma-containing value is preserved verbatim.

    Regression for issue #5368: values such as NO_PROXY=localhost,127.0.0.1 or
    CUDA_VISIBLE_DEVICES=0,1 must not be mangled into Python-list strings.
    """
    result = parse_cli_args(["NO_PROXY=localhost,127.0.0.1"], split_lists=False)
    assert result == {"NO_PROXY": "localhost,127.0.0.1"}

    result = parse_cli_args(["CUDA_VISIBLE_DEVICES=0,1"], split_lists=False)
    assert result == {"CUDA_VISIBLE_DEVICES": "0,1"}


def test_env_option_preserves_comma_values(monkeypatch) -> None:
    """The --env CLI path sets the exact value supplied, commas included.

    End-to-end regression for issue #5368 exercising the common-options wiring.
    """
    import os

    from inspect_ai._cli.common import process_common_options

    monkeypatch.delenv("NO_PROXY", raising=False)
    options = {
        "env": ("NO_PROXY=localhost,127.0.0.1",),
        "display": "full",
        "no_ansi": False,
        "debug": False,
        "debug_port": 5678,
    }
    try:
        process_common_options(options)  # type: ignore[arg-type]
        assert os.environ["NO_PROXY"] == "localhost,127.0.0.1"
    finally:
        os.environ.pop("NO_PROXY", None)
