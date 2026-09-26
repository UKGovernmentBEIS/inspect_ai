"""Tests for the `--extra-headers` and `--extra-body` CLI options.

Both take a YAML or JSON mapping, inline or as the path to a file, and reach
`GenerateConfigArgs` as a dict. Header values must be strings, since that is
what is sent on the wire; a YAML scalar like `3` is refused rather than
coerced.
"""

import json
from pathlib import Path
from typing import Any

import click
import pytest
import yaml
from click.testing import CliRunner, Result

from inspect_ai._cli import eval as cli_eval
from inspect_ai._util.generate_config_args import (
    config_from_locals,
    parse_config_mapping,
    parse_extra_headers,
)
from inspect_ai.model import GenerateConfig


def _option(command: click.Command, name: str) -> click.Option:
    for param in command.params:
        if isinstance(param, click.Option) and name in param.opts:
            return param
    raise AssertionError(f"{name} not declared on {command.name}")


@pytest.mark.parametrize(
    ("name", "envvar"),
    [
        ("--extra-headers", "INSPECT_EVAL_EXTRA_HEADERS"),
        ("--extra-body", "INSPECT_EVAL_EXTRA_BODY"),
    ],
)
def test_eval_and_eval_set_declare_the_option(name: str, envvar: str) -> None:
    for command in (cli_eval.eval_command, cli_eval.eval_set_command):
        option = _option(command, name)
        assert option.envvar == envvar


def test_inline_yaml() -> None:
    assert parse_extra_headers("{X-Trace-Id: abc}") == {"X-Trace-Id": "abc"}


def test_inline_json() -> None:
    assert parse_extra_headers('{"X-Trace-Id": "abc"}') == {"X-Trace-Id": "abc"}


def test_nested_body() -> None:
    assert parse_config_mapping(
        "{chat_template_kwargs: {enable_thinking: true}, top_n: 3}", "--extra-body"
    ) == {"chat_template_kwargs": {"enable_thinking": True}, "top_n": 3}


def test_yaml_file(tmp_path: Path) -> None:
    body = {"chat_template_kwargs": {"enable_thinking": True}}
    path = tmp_path / "body.yaml"
    path.write_text(yaml.safe_dump(body))
    assert parse_config_mapping(str(path), "--extra-body") == body


def test_json_file(tmp_path: Path) -> None:
    headers = {"X-Trace-Id": "abc"}
    path = tmp_path / "headers.json"
    path.write_text(json.dumps(headers))
    assert parse_extra_headers(str(path)) == headers


@pytest.mark.parametrize(
    "value", ["[1, 2]", "not-a-file", "missing.yaml", "{unterminated", "42"]
)
def test_not_a_mapping_is_refused(value: str) -> None:
    with pytest.raises(click.BadParameter, match="YAML or JSON mapping"):
        parse_config_mapping(value, "--extra-body")


def test_file_without_a_mapping_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "body.yaml"
    path.write_text("- secret-token\n")
    with pytest.raises(click.BadParameter, match="does not contain") as ex:
        parse_config_mapping(str(path), "--extra-body")
    assert "secret-token" not in ex.value.format_message()


def test_non_string_key_is_refused() -> None:
    with pytest.raises(click.BadParameter, match="key must be a string"):
        parse_config_mapping("{1: a}", "--extra-body")


def test_non_string_header_value_is_refused_without_quoting_it() -> None:
    with pytest.raises(click.BadParameter, match="X-Retry") as ex:
        parse_extra_headers("{X-Retry: 31337}")
    assert "31337" not in ex.value.format_message()


def test_config_from_locals_parses_both() -> None:
    config = config_from_locals(
        {"extra_headers": "{X-Trace-Id: abc}", "extra_body": '{"top_n": 3}'}
    )
    assert config["extra_headers"] == {"X-Trace-Id": "abc"}
    assert config["extra_body"] == {"top_n": 3}
    GenerateConfig(**config)


def test_omitted_options_leave_the_generate_config_file_value(tmp_path: Path) -> None:
    path = tmp_path / "generate.yaml"
    path.write_text(yaml.safe_dump({"extra_body": {"top_n": 1}}))
    config = config_from_locals(
        {"generate_config": str(path), "extra_body": None, "extra_headers": None}
    )
    assert config["extra_body"] == {"top_n": 1}


def test_option_replaces_the_generate_config_file_value(tmp_path: Path) -> None:
    path = tmp_path / "generate.yaml"
    path.write_text(yaml.safe_dump({"extra_body": {"top_n": 1, "other": True}}))
    config = config_from_locals(
        {"generate_config": str(path), "extra_body": "{top_n: 2}"}
    )
    assert config["extra_body"] == {"top_n": 2}


def _invoke(
    command: click.Command, args: list[str], monkeypatch: pytest.MonkeyPatch
) -> tuple[Result, dict[str, Any]]:
    """Run a real eval command up to `eval_exec`, returning what it was passed."""
    received: dict[str, Any] = {}

    def fake_eval_exec(**kwargs: Any) -> bool:
        received.update(kwargs)
        return True

    monkeypatch.setattr(cli_eval, "eval_exec", fake_eval_exec)
    result = CliRunner().invoke(command, ["task.py", "--log-dir", "logs", *args])
    return result, received


@pytest.mark.parametrize("command", [cli_eval.eval_command, cli_eval.eval_set_command])
def test_command_passes_both_options_to_the_eval(
    command: click.Command, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, received = _invoke(
        command,
        [
            "--extra-headers",
            "{X-Trace-Id: abc}",
            "--extra-body",
            "{chat_template_kwargs: {enable_thinking: true}}",
        ],
        monkeypatch,
    )
    assert result.exit_code == 0, result.output
    assert received["extra_headers"] == {"X-Trace-Id": "abc"}
    assert received["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}


def test_command_reads_the_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSPECT_EVAL_EXTRA_HEADERS", '{"X-Trace-Id": "abc"}')
    monkeypatch.setenv("INSPECT_EVAL_EXTRA_BODY", "{top_n: 3}")
    result, received = _invoke(cli_eval.eval_command, [], monkeypatch)
    assert result.exit_code == 0, result.output
    assert received["extra_headers"] == {"X-Trace-Id": "abc"}
    assert received["extra_body"] == {"top_n": 3}


def test_command_reports_a_bad_value(monkeypatch: pytest.MonkeyPatch) -> None:
    result, received = _invoke(
        cli_eval.eval_command, ["--extra-headers", "{X-Retry: 3}"], monkeypatch
    )
    assert result.exit_code == 2, result.output
    assert "Invalid value for --extra-headers" in result.output
    assert "X-Retry" in result.output
    assert not received
