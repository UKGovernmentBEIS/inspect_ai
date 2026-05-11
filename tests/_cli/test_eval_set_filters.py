from pathlib import Path

import click
import pytest

from inspect_ai._cli.eval import _filter_task_identifiers


def _write_task_file(path: Path) -> None:
    path.write_text(
        """
from inspect_ai import Task, task


@task(light=True, draft=False)
def light_task():
    return Task([])


@task(light=False, draft=True)
def draft_task():
    return Task([])
""".lstrip()
    )


def test_filter_task_identifiers_returns_original_tasks_without_filters() -> None:
    assert _filter_task_identifiers(("tasks.py",), None) == ("tasks.py",)


def test_filter_task_identifiers_matches_task_attributes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_task_file(tmp_path / "tasks.py")
    monkeypatch.chdir(tmp_path)

    assert _filter_task_identifiers(None, ("light=true",)) == ("tasks.py@light_task",)
    assert _filter_task_identifiers(("tasks.py",), ("draft~=true",)) == (
        "tasks.py@light_task",
    )


def test_filter_task_identifiers_fails_when_no_tasks_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_task_file(tmp_path / "tasks.py")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(click.ClickException, match="No tasks matched"):
        _filter_task_identifiers(None, ("light=false", "draft=false"))
