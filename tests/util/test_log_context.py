import logging
from types import SimpleNamespace
from typing import Any

import pytest

from inspect_ai._util import log_context
from inspect_ai._util.log_context import (
    SampleContextFilter,
    install_sample_context_filter,
    set_run_shape,
)


@pytest.fixture(autouse=True)
def _reset_run_shape() -> None:
    set_run_shape([], 1)


def _active(task: str, sample_id: Any, epoch: int) -> SimpleNamespace:
    return SimpleNamespace(task=task, sample=SimpleNamespace(id=sample_id), epoch=epoch)


def _record(msg: str, args: tuple[Any, ...] | None = None) -> logging.LogRecord:
    return logging.LogRecord(
        name="inspect_ai.x",
        level=logging.WARNING,
        pathname="x.py",
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_no_active_sample_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "inspect_ai.log._samples.sample_active", lambda: None, raising=True
    )
    record = _record("hello")
    assert SampleContextFilter().filter(record) is True
    assert record.getMessage() == "hello"
    assert not hasattr(record, "task")
    assert not hasattr(record, "sample_id")
    assert not hasattr(record, "epoch")


@pytest.mark.parametrize(
    ("task_names", "max_epochs", "expected_prefix"),
    [
        (["audit"], 1, "sample=seed_01"),
        (["audit"], 3, "sample=seed_01 epoch=2"),
        (["audit_a", "audit_b"], 1, "task=audit_a sample=seed_01"),
        (["audit_a", "audit_b"], 3, "task=audit_a sample=seed_01 epoch=2"),
    ],
)
def test_prefix_format(
    monkeypatch: pytest.MonkeyPatch,
    task_names: list[str],
    max_epochs: int,
    expected_prefix: str,
) -> None:
    monkeypatch.setattr(
        "inspect_ai.log._samples.sample_active",
        lambda: _active("audit_a", "seed_01", 2),
        raising=True,
    )
    set_run_shape(task_names, max_epochs)

    record = _record("something happened")
    assert SampleContextFilter().filter(record) is True
    assert record.getMessage() == f"{expected_prefix}\nsomething happened"
    assert getattr(record, "task") == "audit_a"
    assert getattr(record, "sample_id") == "seed_01"
    assert getattr(record, "epoch") == 2


def test_set_run_shape_overwrites_state() -> None:
    set_run_shape(["a"], 7)
    assert log_context._task_names == {"a"}
    assert log_context._max_epochs == 7
    set_run_shape(["a", "b"], 1)
    assert log_context._task_names == {"a", "b"}
    assert log_context._max_epochs == 1


def test_args_with_format_specifiers_are_preformatted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "inspect_ai.log._samples.sample_active",
        lambda: _active("t", "s", 1),
        raising=True,
    )
    set_run_shape(["t"], 1)
    record = _record("hello %s, %d items", args=("world", 3))
    assert SampleContextFilter().filter(record) is True
    # args cleared, message resolved
    assert record.args is None
    assert record.getMessage() == "sample=s\nhello world, 3 items"


def test_percent_in_sample_id_does_not_break_formatting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "inspect_ai.log._samples.sample_active",
        lambda: _active("t", "100%_id", 1),
        raising=True,
    )
    set_run_shape(["t"], 1)
    record = _record("hello")
    assert SampleContextFilter().filter(record) is True
    assert record.getMessage() == "sample=100%_id\nhello"


def test_install_is_idempotent() -> None:
    handler = logging.Handler()
    install_sample_context_filter(handler)
    install_sample_context_filter(handler)
    assert sum(isinstance(f, SampleContextFilter) for f in handler.filters) == 1
