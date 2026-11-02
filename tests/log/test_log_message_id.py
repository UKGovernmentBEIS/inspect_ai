import os

import pytest

from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.log._file import read_eval_log
from inspect_ai.model._chat_message import ChatMessageUser


def test_message_id_auto_assign():
    message = ChatMessageUser(content="foo")
    assert message.id


def test_message_id_no_deserialize():
    log = read_eval_log(log_path("log_formats.json"))
    assert log.samples
    assert log.samples[0].messages[0].id is None

    log = read_eval_log(log_path("log_formats.eval"))
    assert log.samples
    assert log.samples[0].messages[0].id is None


def log_path(file: str) -> str:
    return os.path.join("tests", "log", "test_eval_log", f"{file}")


@pytest.mark.parametrize("file", ["log_formats.json", "log_images.json"])
def test_legacy_log_events_stable_across_reads(file: str) -> None:
    first = read_eval_log(log_path(file))
    second = read_eval_log(log_path(file))
    assert first.samples and second.samples
    assert first.samples[0].events == second.samples[0].events


def test_sample_init_input_message_id_no_deserialize() -> None:
    log = read_eval_log(log_path("log_images.json"))
    assert log.samples
    event = log.samples[0].events[0]
    assert isinstance(event, SampleInitEvent)
    assert not isinstance(event.sample.input, str)
    assert event.sample.input[0].id is None


def test_legacy_transcript_ids_no_deserialize() -> None:
    log = read_eval_log(log_path("log_formats.json"))
    assert log.samples
    events = log.samples[0].events
    assert all(event.uuid is None for event in events)
    model_events = [event for event in events if isinstance(event, ModelEvent)]
    assert model_events
    assert all(m.id is None for event in model_events for m in event.input)
