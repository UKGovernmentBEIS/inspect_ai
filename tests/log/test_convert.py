import json
import pathlib
import re
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
from inspect_ai.log._recorders.eval2 import convert_eval_logs_to_eval2

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


def test_convert_eval2(tmp_path: pathlib.Path):
    chunk_size = 3
    input_file = (
        _TESTS_DIR
        / "test_list_logs/2024-11-05T13-32-37-05-00_input-task_hxs4q9azL3ySGkjJirypKZ.eval"
    )

    convert_eval_logs_to_eval2(str(input_file), str(tmp_path), chunk_size=chunk_size)

    output_file = (tmp_path / input_file.name).with_suffix(".eval2")
    assert output_file.exists()

    with zipfile.ZipFile(output_file) as zf:
        names = set(zf.namelist())
        assert "header.json" in names
        assert "summaries.json" in names

        shell_entry = next(n for n in sorted(names) if n.endswith("/sample.json"))
        sample_prefix = shell_entry.removesuffix("sample.json")
        shell = json.loads(zf.read(shell_entry))

        # chunked/relocated fields must not appear in the shell
        for field in ("messages", "events", "attachments", "events_data", "metadata"):
            assert field not in shell

        # sequences = cumulative end-exclusive chunk boundaries per sequence;
        # chunks are named by their start index only
        sequences = shell["sequences"]

        def entry_start(entry: str) -> int:
            return int(entry.rsplit("/", 1)[1].removesuffix(".json"))

        def read_sequence(sequence: str, count_capped: bool = True) -> list:
            entries = sorted(
                (n for n in names if n.startswith(sample_prefix + sequence + "/")),
                key=entry_start,
            )
            boundaries = sequences[sequence]
            assert [entry_start(entry) for entry in entries] == [0, *boundaries[:-1]]
            items: list = []
            for entry, start, end_exclusive in zip(
                entries, [0, *boundaries[:-1]], boundaries
            ):
                chunk = json.loads(zf.read(entry))
                assert len(chunk) == end_exclusive - start
                if count_capped:
                    assert len(chunk) <= chunk_size
                items += chunk
            return items

        messages = read_sequence("messages")
        events = read_sequence("events")
        calls = read_sequence("calls")
        attachments = read_sequence("attachments", count_capped=False)

        # every ref is renumbered to a valid attachment sequence index
        # (no hash-form refs survive)
        refs = re.findall(
            r"attachment://([0-9a-f]{32}|\d+)",
            json.dumps([shell, messages, events, calls]),
        )
        assert refs
        assert all(ref.isdigit() and int(ref) < len(attachments) for ref in refs)

        # model event inputs/calls are condensed into sequence refs
        model_events = [e for e in events if e["event"] == "model"]
        assert any(e.get("input_refs") for e in model_events)
        assert all(not e.get("input") for e in model_events)
        assert any((e.get("call") or {}).get("call_refs") for e in model_events)

        # the shell's message_refs reconstruct the final conversation
        # (resolving numeric attachment refs through the sequence)
        def resolve(text: str) -> str:
            match = re.fullmatch(r"attachment://(\d+)", text)
            return attachments[int(match.group(1))] if match else text

        final = [
            messages[i]
            for start, end_exclusive in shell["message_refs"]
            for i in range(start, end_exclusive)
        ]
        original = read_eval_log(str(input_file), resolve_attachments="full")
        assert original.samples
        original_messages = original.samples[0].messages
        assert [m["role"] for m in final] == [m.role for m in original_messages]
        assert [
            resolve(m["content"]) for m in final if isinstance(m["content"], str)
        ] == [m.content for m in original_messages if isinstance(m.content, str)]

        # metadata lives in a sibling entry (written only when non-empty)
        metadata_entry = sample_prefix + "metadata.json"
        if original.samples[0].metadata:
            assert json.loads(zf.read(metadata_entry)) == original.samples[0].metadata
        else:
            assert metadata_entry not in names


@pytest.mark.parametrize("stream", [True, False], ids=["stream", "no-stream"])
def test_convert_applies_message_pool_dedup(tmp_path: pathlib.Path, stream: bool):
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
