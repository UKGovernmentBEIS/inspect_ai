"""Meta-tests for the ``caplog`` override in tests/conftest.py.

The override attaches caplog's handler directly to the ``inspect_ai`` logger
so that records are captured whether or not ``init_logger()`` has already set
``propagate = False`` on it (which the first ``eval()`` in a process does,
permanently). These tests pin one-record-per-emission in both states, since
each state exercises a different path:

- ``propagate = True`` (fresh process): the record reaches caplog's handler
  both via the direct attachment and via propagation to the root logger, and
  the override's dedupe filter must collapse that to one record.
- ``propagate = False`` (after any eval has run): propagation-based capture is
  dead and the direct attachment alone must deliver the record.

The tests force each state explicitly rather than depending on suite ordering.
"""

import logging

import pytest

_probe_logger = logging.getLogger("inspect_ai._meta.caplog_probe")


def _emit_probe_warning(
    caplog: pytest.LogCaptureFixture, propagate: bool
) -> list[logging.LogRecord]:
    inspect_logger = logging.getLogger("inspect_ai")
    saved_propagate = inspect_logger.propagate
    inspect_logger.propagate = propagate
    try:
        with caplog.at_level(logging.WARNING, logger="inspect_ai"):
            _probe_logger.warning("caplog probe warning")
    finally:
        inspect_logger.propagate = saved_propagate
    return [r for r in caplog.records if r.message == "caplog probe warning"]


def test_caplog_captures_exactly_one_record_when_propagating(
    caplog: pytest.LogCaptureFixture,
) -> None:
    records = _emit_probe_warning(caplog, propagate=True)
    assert len(records) == 1


def test_caplog_captures_exactly_one_record_when_not_propagating(
    caplog: pytest.LogCaptureFixture,
) -> None:
    records = _emit_probe_warning(caplog, propagate=False)
    assert len(records) == 1
