"""Tests for parse_cli_args -M flag parsing, covering issue #3348.

Verifies that dotted vLLM arguments like `speculative-config.num_speculative_tokens`
are correctly normalized through the CLI layer without mangling nested key segments.
"""

import os

import pytest
import yaml

from inspect_ai._cli.common import CommonOptions, process_common_options
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


def test_shared_parser_task_model_args_preserve_existing_comma_splitting() -> None:
    """The shared parser preserves existing comma-splitting behavior for task/model args."""
    # Unquoted comma splits to list
    res1 = parse_cli_args(["target=alpha,beta"])
    assert res1 == {"target": ["alpha", "beta"]}

    # Quoted comma also splits to list (existing shared parser behavior)
    res2 = parse_cli_args(['target="alpha,beta"'])
    assert res2 == {"target": ["alpha", "beta"]}

    # Single-quoted comma splits to list
    res3 = parse_cli_args(["target='alpha,beta'"])
    assert res3 == {"target": ["alpha", "beta"]}

    # Numbers in quotes split to list
    res4 = parse_cli_args(['gpu_ids="0,1"'])
    assert res4 == {"gpu_ids": ["0", "1"]}

    # Explicit preserve_quoted_commas=False matches default
    res5 = parse_cli_args(['target="alpha,beta"'], preserve_quoted_commas=False)
    assert res5 == {"target": ["alpha", "beta"]}


def test_quoted_commas_preserved_in_parse_cli_args_with_flag() -> None:
    """Issue #5368: Explicitly quoted YAML/JSON strings must preserve commas when enabled."""
    # Double quoted
    res1 = parse_cli_args(
        ['NO_PROXY="localhost,127.0.0.1"'], preserve_quoted_commas=True
    )
    assert res1 == {"NO_PROXY": "localhost,127.0.0.1"}

    # Single quoted
    res2 = parse_cli_args(["CUDA_VISIBLE_DEVICES='0,1'"], preserve_quoted_commas=True)
    assert res2 == {"CUDA_VISIBLE_DEVICES": "0,1"}

    # Unquoted comma continues to split into a list (preserving backward compatibility)
    res3 = parse_cli_args(["NO_PROXY=localhost,127.0.0.1"], preserve_quoted_commas=True)
    assert res3 == {"NO_PROXY": ["localhost", "127.0.0.1"]}

    # Force string with quoted commas
    res4 = parse_cli_args(
        ['NO_PROXY="localhost,127.0.0.1"'], force_str=True, preserve_quoted_commas=True
    )
    assert res4 == {"NO_PROXY": "localhost,127.0.0.1"}

    # Empty quoted strings
    res5 = parse_cli_args(['EMPTY=""'], preserve_quoted_commas=True)
    assert res5 == {"EMPTY": ""}

    # Multiple equal signs in value
    res6 = parse_cli_args(['KEY="foo=bar,baz"'], preserve_quoted_commas=True)
    assert res6 == {"KEY": "foo=bar,baz"}


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
def test_env_comma_lists_and_yaml_values(
    raw: str, expected: object, force_str: bool
) -> None:
    """When preserve_quoted_commas=True, only plain strings use the comma-separated list shorthand."""
    assert parse_cli_args(
        [f"label={raw}"], force_str=force_str, preserve_quoted_commas=True
    ) == {"label": str(expected) if force_str else expected}


def test_process_common_options_env_quoted_commas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The --env CLI option preserves quoted comma-containing values in os.environ."""
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

    options: CommonOptions = {
        "log_level": "info",
        "log_dir": "./logs",
        "env": (
            'NO_PROXY="localhost,127.0.0.1"',
            "CUDA_VISIBLE_DEVICES='0,1'",
        ),
        "display": "none",
        "no_ansi": True,
        "debug": False,
        "debug_port": 5678,
        "debug_errors": False,
        "traceback_locals": False,
    }
    process_common_options(options)

    assert os.environ["NO_PROXY"] == "localhost,127.0.0.1"
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "0,1"


@pytest.mark.parametrize(
    "malformed_arg",
    [
        'NO_PROXY="localhost,127.0.0.1',
        "NO_PROXY=[1,2",
        'NO_PROXY="a""b,c"',
    ],
)
def test_malformed_yaml_raises(malformed_arg: str) -> None:
    """Malformed YAML expressions propagate yaml.YAMLError rather than silently coercing."""
    with pytest.raises(yaml.YAMLError):
        parse_cli_args([malformed_arg])
