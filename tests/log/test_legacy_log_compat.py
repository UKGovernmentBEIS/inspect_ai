"""Legacy log compatibility and format detection via call_id sentinel."""

# pyright: reportImplicitRelativeImport=false

from pathlib import Path

from _helpers.event_assertions import model_events

from inspect_ai.log import read_eval_log

FIXTURE_DIR = Path(__file__).parent.parent / "_helpers" / "fixtures"
LEGACY = FIXTURE_DIR / "legacy" / "retry-2-then-success.eval"
POSTFIX = FIXTURE_DIR / "postfix" / "retry-2-then-success.eval"


def test_legacy_fixture_reads_without_crash() -> None:
    log = read_eval_log(str(LEGACY))
    assert log.samples


def test_legacy_fixture_has_no_call_id() -> None:
    log = read_eval_log(str(LEGACY))
    assert log.samples is not None
    events = model_events(log.samples[0])
    assert events
    assert all(event.call_id is None for event in events)
    assert all(event.attempt is None for event in events)


def test_legacy_fixture_preserves_rewrite_signature() -> None:
    log = read_eval_log(str(LEGACY))
    assert log.samples is not None
    events = model_events(log.samples[0])
    success = events[-1]
    failed = events[:-1]
    assert any(success.timestamp < event.timestamp for event in failed)


def test_postfix_fixture_has_call_id_and_attempt() -> None:
    log = read_eval_log(str(POSTFIX))
    assert log.samples is not None
    events = model_events(log.samples[0])
    assert events
    assert all(event.call_id is not None for event in events)
    assert [event.attempt for event in events] == [1, 2, 3]


def test_postfix_fixture_timestamps_non_decreasing() -> None:
    log = read_eval_log(str(POSTFIX))
    assert log.samples is not None
    events = model_events(log.samples[0])
    for previous, current in zip(events, events[1:]):
        assert current.timestamp >= previous.timestamp
