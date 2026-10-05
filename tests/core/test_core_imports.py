from pathlib import Path

import pytest

from inspect_ai.core._imports import ImportViolation, check_imports


def test_core_imports_only_allowed_modules() -> None:
    assert check_imports("inspect_ai.core") == []


def _package(root: Path, files: dict[str, str]) -> None:
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)


def _violations(violations: list[ImportViolation]) -> set[tuple[str, str, int, str]]:
    return {(Path(v.file).name, v.module, v.line, v.scope) for v in violations}


def test_check_imports_reports_each_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _package(
        tmp_path,
        {
            "monitors/__init__.py": "",
            "monitors/rules.py": (
                "from typing import TYPE_CHECKING\n"
                "import requests\n"
                "if TYPE_CHECKING:\n"
                "    import rich\n"
                "def check():\n"
                "    from inspect_ai.model import get_model\n"
            ),
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    assert _violations(check_imports("monitors")) == {
        ("rules.py", "requests", 2, "module"),
        ("rules.py", "rich", 4, "type_checking"),
        ("rules.py", "inspect_ai.model", 6, "function"),
    }


def test_check_imports_allows_own_package_core_and_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _package(
        tmp_path,
        {
            "monitors/__init__.py": "from . import rules\n",
            "monitors/rules.py": (
                "import json\n"
                "from pydantic import BaseModel\n"
                "from inspect_ai.core import ChatMessage\n"
                "from .helpers import util\n"
                "from extra_pkg.sub import thing\n"
            ),
            "monitors/helpers/__init__.py": "from .. import rules\n",
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    assert _violations(check_imports("monitors")) == {
        ("rules.py", "extra_pkg.sub", 5, "module")
    }
    assert check_imports("monitors", allowed=["extra_pkg"]) == []


def test_check_imports_single_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _package(tmp_path, {"single_monitor.py": "import inspect_ai\n"})
    monkeypatch.syspath_prepend(str(tmp_path))

    assert _violations(check_imports("single_monitor")) == {
        ("single_monitor.py", "inspect_ai", 1, "module")
    }


def test_check_imports_unknown_module() -> None:
    with pytest.raises(ModuleNotFoundError):
        check_imports("no_such_module_for_check_imports")
