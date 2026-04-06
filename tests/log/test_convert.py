import json
import pathlib
import zipfile
from typing import Literal

import pytest

from inspect_ai.event import ModelEvent, SampleInitEvent
from inspect_ai.log._convert import convert_eval_logs
from inspect_ai.log._edit import (
    MetadataEdit,
    ProvenanceData,
    TagsEdit,
    edit_eval_log,
)
from inspect_ai.log._file import read_eval_log, write_eval_log
from inspect_ai.log._log import EvalLog

_TESTS_DIR = pathlib.Path(__file__).resolve().parent


@pytest.mark.parametrize(
    "stream", [True, False, 3], ids=["stream", "no-stream", "stream-3"]
)
@pytest.mark.parametrize("to", ["eval", "json"])
@pytest.mark.parametrize(
    "resolve_attachments",
    ["full", "core", False],
    ids=["resolve-attachments", "resolve-core-attachments", "no-resolve-attachments"],
)
def test_convert_eval_logs(
    tmp_path: pathlib.Path,
    stream: bool | int,
    to: Literal["eval", "json"],
    resolve_attachments: bool | Literal["full", "core"],
):
    input_file = (
        _TESTS_DIR
        / "test_list_logs/2024-11-05T13-32-37-05-00_input-task_hxs4q9azL3ySGkjJirypKZ.eval"
    )

    convert_eval_logs(
        str(input_file),
        to,
        str(tmp_path),
        resolve_attachments=resolve_attachments,
        stream=stream,
    )

    output_file = (tmp_path / input_file.name).with_suffix(f".{to}")
    assert output_file.exists()

    log = read_eval_log(str(output_file), resolve_attachments=resolve_attachments)
    assert isinstance(
        log,
        EvalLog,
    )
    assert log.samples
    assert log.samples[0].events
    sample_init_event = log.samples[0].events[0]
    assert isinstance(sample_init_event, SampleInitEvent)
    assert isinstance(sample_init_event.sample.input, str)
    if resolve_attachments is not False:
        assert sample_init_event.sample.input.startswith("Hey there, hipster!")
    else:
        assert sample_init_event.sample.input.startswith("attachment:")

    model_event = log.samples[0].events[6]
    assert isinstance(model_event, ModelEvent)
    assert model_event.call is not None
    model_event_call_messages = model_event.call.request.get("messages")
    assert isinstance(model_event_call_messages, list)
    model_event_call_message = model_event_call_messages[0]
    assert isinstance(model_event_call_message, dict)
    model_event_call_message_content = model_event_call_message.get("content")
    assert isinstance(model_event_call_message_content, str)
    if resolve_attachments == "full":
        assert model_event_call_message_content.startswith("Hey there, hipster!")
    else:
        assert model_event_call_message_content.startswith("attachment:")


@pytest.mark.parametrize("stream", [True, 3], ids=["stream", "stream-3"])
@pytest.mark.parametrize("to", ["eval", "json"])
def test_stream_convert_preserves_log_updates(
    tmp_path: pathlib.Path,
    stream: bool | int,
    to: Literal["eval", "json"],
) -> None:
    input_file = (
        _TESTS_DIR
        / "test_list_logs/2024-11-05T13-32-37-05-00_input-task_hxs4q9azL3ySGkjJirypKZ.eval"
    )
    edited_input = tmp_path / input_file.name

    log = read_eval_log(str(input_file))
    log = edit_eval_log(
        log,
        [
            TagsEdit(tags_add=["qa_reviewed"]),
            MetadataEdit(metadata_set={"reviewer": "alice"}),
        ],
        ProvenanceData(author="alice", reason="qa"),
    )
    write_eval_log(log, str(edited_input))

    convert_eval_logs(
        str(edited_input),
        to,
        str(tmp_path),
        overwrite=True,
        stream=stream,
    )

    output_file = (tmp_path / edited_input.name).with_suffix(f".{to}")

    # Check raw JSON on disk rather than read_eval_log, because the model
    # validator recomputes tags/metadata from log_updates and would mask
    # bugs where log_finish fails to persist the computed values.
    if to == "json":
        with open(output_file) as f:
            raw = json.load(f)
    else:
        with zipfile.ZipFile(output_file, "r") as zf:
            with zf.open("header.json") as f:
                raw = json.load(f)

    assert "qa_reviewed" in raw.get("tags", [])
    assert raw.get("metadata", {}).get("reviewer") == "alice"
    assert len(raw.get("log_updates", [])) == 1


@pytest.mark.parametrize("stream", [True, False], ids=["stream", "no-stream"])
def test_convert_applies_message_pool_dedup(
    tmp_path: pathlib.Path,
    stream: bool,
    monkeypatch: pytest.MonkeyPatch,
):
    """Converting a v2 .eval file should apply message pool dedup."""
    input_file = (
        _TESTS_DIR
        / "test_list_logs/2024-11-05T13-32-37-05-00_input-task_hxs4q9azL3ySGkjJirypKZ.eval"
    )

    convert_eval_logs(
        str(input_file),
        "eval",
        str(tmp_path),
        overwrite=True,
        stream=stream,
    )

    output_file = (tmp_path / input_file.name).with_suffix(".eval")
    assert output_file.exists()

    log = read_eval_log(str(output_file))
    assert log.version == 2
    assert log.samples

    for sample in log.samples:
        # read_eval_log resolves pools, so input_refs should be None
        # and events_data should be None after round-trip
        assert sample.events_data is None
        model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
        assert any(len(me.input) > 0 for me in model_events), (
            "At least one model event should have populated input"
        )
        for me in model_events:
            assert me.input_refs is None
