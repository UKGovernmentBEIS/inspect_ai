from pathlib import Path

from pytest import MonkeyPatch

from inspect_ai.util._sandbox.compose import parse_compose_yaml

COMPOSE_UTF8 = """\
services:
  app:
    image: python:3.11
    environment:
      GREETING: 你好
"""


def write_compose(directory: Path, content: str = COMPOSE_UTF8) -> Path:
    path = directory / "compose.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_compose_yaml_round_trips_utf8_environment(tmp_path: Path) -> None:
    path = write_compose(tmp_path)

    config = parse_compose_yaml(str(path))

    environment = config.services["app"].environment
    assert isinstance(environment, dict)
    assert environment["GREETING"] == "你好"


def test_parse_compose_yaml_reads_utf8_under_non_utf8_platform_default(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Reproduce the reported Windows/cp936 corruption on any platform: a
    # platform whose preferred text encoding is cp936 makes open() without an
    # explicit encoding decode UTF-8 bytes as cp936. parse_compose_yaml must
    # stay correct regardless of the platform default.
    import builtins

    import inspect_ai.util._sandbox.compose as compose_module

    real_open = builtins.open

    def cp936_default_open(file, mode="r", *args, **kwargs):
        if kwargs.get("encoding") is None:
            kwargs["encoding"] = "cp936"
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(compose_module, "open", cp936_default_open, raising=False)
    path = write_compose(tmp_path)

    config = parse_compose_yaml(str(path))

    environment = config.services["app"].environment
    assert isinstance(environment, dict)
    assert environment["GREETING"] == "你好"
