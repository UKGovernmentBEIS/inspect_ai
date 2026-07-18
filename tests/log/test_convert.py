import json
import pathlib
import re
import zipfile
from typing import Literal

import pytest

from inspect_ai._util.constants import get_deserializing_context
from inspect_ai.event import ModelEvent, SampleInitEvent
from inspect_ai.log._convert import convert_eval_logs
from inspect_ai.log._edit import (
    MetadataEdit,
    ProvenanceData,
    TagsEdit,
    edit_eval_log,
)
from inspect_ai.log._file import read_eval_log, write_eval_log
from inspect_ai.log._log import EvalLog, EvalSample
from inspect_ai.log._recorders.chunked import convert_eval_logs_to_chunked
from inspect_ai.log._recorders.chunked.format import (
    attachment_chunk_boundaries,
    boundary_ranges,
    chunk_boundaries,
    chunk_entry_name,
    chunk_ranges,
    classify_sample_shape,
    events_stats_entry_name,
    metadata_entry_name,
    monolith_entry_name,
    sample_prefix,
    shell_entry_name,
    skeleton_entry_name,
)
from inspect_ai.log._recorders.chunked.stats import event_stats
from inspect_ai.log._resolve import resolve_sample_events_data

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


# -- chunked per-sample shape (format core + converter) --


def test_chunk_ranges():
    assert chunk_ranges(0, 3) == []
    assert chunk_ranges(3, 3) == [(0, 3)]
    assert chunk_ranges(7, 3) == [(0, 3), (3, 6), (6, 7)]
    assert chunk_ranges(2, 1000) == [(0, 2)]


def test_chunk_boundaries():
    assert chunk_boundaries(0, 3) == []
    assert chunk_boundaries(7, 3) == [3, 6, 7]
    # last boundary is always the sequence count
    assert chunk_boundaries(9, 3)[-1] == 9


def test_attachment_chunk_boundaries():
    assert attachment_chunk_boundaries([], 10) == []
    # pack until target exceeded
    assert attachment_chunk_boundaries([4, 4, 4], 10) == [2, 3]
    # oversized item gets a chunk to itself
    assert attachment_chunk_boundaries([25, 1, 1], 10) == [1, 3]
    assert attachment_chunk_boundaries([1, 25, 1], 10) == [1, 2, 3]
    # everything fits in one chunk
    assert attachment_chunk_boundaries([1, 2, 3], 10) == [3]


def test_boundary_ranges():
    assert boundary_ranges([]) == []
    assert boundary_ranges([3, 6, 7]) == [(0, 3), (3, 6), (6, 7)]


def test_event_stats():
    from pydantic import TypeAdapter

    from inspect_ai.event._event import DiscriminatedEvent, Event

    adapter: TypeAdapter[list[Event]] = TypeAdapter(list[DiscriminatedEvent])
    ts = {"timestamp": "2026-01-01T00:00:00+00:00", "working_start": 0.0}
    model = {
        "event": "model",
        "span_id": "S1",
        "model": "mockllm/model",
        "input": [],
        "tools": [],
        "tool_choice": "auto",
        "config": {},
        "output": {},
        **ts,
    }
    events = adapter.validate_python(
        [
            {"event": "span_begin", "id": "S1", "name": "agent", "type": "agent", **ts},
            model,
            {"event": "info", "span_id": "S1", "data": "note", **ts},
            model,
            {"event": "span_end", "id": "S1", **ts},
        ],
        context=get_deserializing_context(),
    )

    stats = event_stats(events, [3, 5])
    assert [chunk.start for chunk in stats.chunks] == [0, 3]
    first_chunk, last_chunk = stats.chunks
    assert first_chunk.type_counts == {"span_begin": 1, "model": 1, "info": 1}
    assert (first_chunk.first.type, first_chunk.first.span_id) == ("span_begin", None)
    assert (first_chunk.last.type, first_chunk.last.span_id) == ("info", "S1")
    assert last_chunk.type_counts == {"model": 1, "span_end": 1}
    assert (last_chunk.first.type, last_chunk.first.span_id) == ("model", "S1")
    assert (last_chunk.last.type, last_chunk.last.span_id) == ("span_end", None)

    # canonical JSON form omits null span_id
    dumped = stats.model_dump(mode="json", exclude_none=True)
    assert "span_id" not in dumped["chunks"][0]["first"]
    assert dumped["chunks"][0]["last"]["span_id"] == "S1"

    assert event_stats([], []).chunks == []


def test_monolith_entry_name_matches_eval_recorder():
    from inspect_ai.log._recorders.eval import _sample_filename

    assert monolith_entry_name("abc", 2) == _sample_filename("abc", 2)
    assert monolith_entry_name(5, 1) == _sample_filename(5, 1)


def test_classify_sample_shape_mixed_log():
    names = {
        monolith_entry_name("mono", 1),
        shell_entry_name("chunky", 1),
        chunk_entry_name("chunky", 1, "events", 0),
        chunk_entry_name("chunky", 1, "messages", 0),
        "header.json",
        "summaries.json",
    }
    assert classify_sample_shape(names, "mono", 1) == "monolith"
    assert classify_sample_shape(names, "chunky", 1) == "chunked"
    assert classify_sample_shape(names, "chunky", 2) is None
    assert classify_sample_shape(names, "absent", 1) is None


_CHUNK_SIZE = 3

_SEQUENCES = ("messages", "events", "calls", "attachments")


def _read_chunked_sequence(
    zf: zipfile.ZipFile, id: str | int, epoch: int, sequence: str, boundaries: list[int]
) -> list:
    """Read a full sequence, verifying entry names/extents against boundaries."""
    names = set(zf.namelist())
    prefix = f"{sample_prefix(id, epoch)}/{sequence}/"

    def entry_start(entry: str) -> int:
        return int(entry.rsplit("/", 1)[1].removesuffix(".json"))

    def is_chunk(entry: str) -> bool:
        # chunk entry names are purely numeric (events/ also holds stats.json)
        return entry.rsplit("/", 1)[1].removesuffix(".json").isdigit()

    entries = sorted(
        (n for n in names if n.startswith(prefix) and is_chunk(n)), key=entry_start
    )
    # chunk entry names carry the start index only
    assert [entry_start(entry) for entry in entries] == [0, *boundaries[:-1]]
    items: list = []
    for entry, (start, end_exclusive) in zip(entries, boundary_ranges(boundaries)):
        chunk = json.loads(zf.read(entry))
        assert len(chunk) == end_exclusive - start
        items += chunk
    return items


def _reassemble_chunked_sample(
    zf: zipfile.ZipFile, id: str | int, epoch: int
) -> tuple[EvalSample, dict[str, str]]:
    """Reassemble a chunked sample into an `EvalSample` + its attachment map.

    Returns the sample with pool refs resolved (`input_refs`/`call_refs`
    expanded back to inline input/calls) and an attachment map keyed by
    sequence index (for resolving `attachment://<index>` refs).
    """
    names = set(zf.namelist())
    shell = json.loads(zf.read(shell_entry_name(id, epoch)))
    boundaries = shell["sequences"]

    messages, events, calls, attachments = (
        _read_chunked_sequence(zf, id, epoch, sequence, boundaries[sequence])
        for sequence in _SEQUENCES
    )

    data = dict(shell)
    message_refs = data.pop("message_refs")
    data.pop("sequences")
    data["messages"] = [
        message
        for start, end_exclusive in message_refs
        for message in messages[start:end_exclusive]
    ]
    data["events"] = events
    data["events_data"] = {"messages": messages, "calls": calls}
    attachment_map = {str(i): content for i, content in enumerate(attachments)}
    data["attachments"] = attachment_map

    metadata_entry = metadata_entry_name(id, epoch)
    if metadata_entry in names:
        data["metadata"] = json.loads(zf.read(metadata_entry))

    sample = EvalSample.model_validate(data, context=get_deserializing_context())
    return resolve_sample_events_data(sample), attachment_map


_ATTACHMENT_REF = re.compile(r"attachment://([0-9a-f]{32}|\d+)")


def _resolved_dump(sample: EvalSample, attachments: dict[str, str]) -> dict:
    """Dump a sample to JSON with every attachment ref resolved to content.

    Resolves refs textually (rather than via the typed walkers) so ref
    sites the walkers miss — e.g. provider payloads, state deltas — are
    covered uniformly on both sides of the round-trip comparison. Unknown
    refs are left as-is (symmetric with the converter's renumberer).
    """

    def resolve(value):
        if isinstance(value, str):
            return _ATTACHMENT_REF.sub(
                lambda m: attachments.get(m.group(1), m.group(0)), value
            )
        if isinstance(value, list):
            return [resolve(v) for v in value]
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        return value

    dump = sample.model_dump(mode="json", exclude_none=True)
    # attachments are a different currency per shape (hash map vs sequence)
    dump.pop("attachments", None)
    # events in logs that predate working_start get a parse-time
    # default_factory value, nondeterministic across parses (two plain
    # read_eval_log calls differ too) — exclude it from the comparison
    for event in dump["events"]:
        event.pop("working_start", None)
    return resolve(dump)


def test_convert_chunked_layout(tmp_path: pathlib.Path):
    input_file = (
        _TESTS_DIR
        / "test_list_logs/2024-11-05T13-32-37-05-00_input-task_hxs4q9azL3ySGkjJirypKZ.eval"
    )

    convert_eval_logs_to_chunked(str(input_file), str(tmp_path), chunk_size=_CHUNK_SIZE)

    output_file = tmp_path / input_file.name
    assert output_file.exists()
    assert output_file.suffix == ".eval"

    original = read_eval_log(str(input_file), resolve_attachments="full")
    assert original.samples
    original_sample = original.samples[0]
    id, epoch = original_sample.id, original_sample.epoch

    with zipfile.ZipFile(input_file) as zf:
        journal_entries = {
            n: zf.read(n) for n in zf.namelist() if n.startswith("_journal/")
        }
    assert journal_entries

    with zipfile.ZipFile(output_file) as zf:
        names = set(zf.namelist())
        assert "header.json" in names
        assert "summaries.json" in names

        # _journal/ entries pass through unchanged
        for name, content in journal_entries.items():
            assert zf.read(name) == content

        # every sample entry lives under the per-sample prefix (no
        # monolith entries remain)
        sample_entries = [n for n in names if n.startswith("samples/")]
        prefix = sample_prefix(id, epoch) + "/"
        assert sample_entries
        assert all(n.startswith(prefix) for n in sample_entries)
        assert classify_sample_shape(names, id, epoch) == "chunked"

        shell = json.loads(zf.read(shell_entry_name(id, epoch)))

        # chunked/relocated fields must not appear in the shell
        for field in ("messages", "events", "attachments", "events_data", "metadata"):
            assert field not in shell

        # all four sequences are present with count-capped chunks
        # (attachments chunk by bytes, not count)
        sequences = shell["sequences"]
        assert set(sequences) == set(_SEQUENCES)
        for sequence in ("messages", "events", "calls"):
            for start, end_exclusive in boundary_ranges(sequences[sequence]):
                assert 0 < end_exclusive - start <= _CHUNK_SIZE

        messages, events, calls, attachments = (
            _read_chunked_sequence(zf, id, epoch, sequence, sequences[sequence])
            for sequence in _SEQUENCES
        )

        # every ref is renumbered to a valid attachment sequence index
        # (no hash-form refs survive)
        refs = _ATTACHMENT_REF.findall(json.dumps([shell, messages, events, calls]))
        assert refs
        assert all(ref.isdigit() and int(ref) < len(attachments) for ref in refs)

        # model event inputs/calls are condensed into range-encoded refs
        # (half-open [start, end_exclusive) pairs, never flat lists)
        model_events = [e for e in events if e["event"] == "model"]
        input_refs = [r for e in model_events for r in e.get("input_refs") or []]
        assert input_refs
        assert all(
            len(ref) == 2 and ref[0] < ref[1] <= len(messages) for ref in input_refs
        )
        assert all(not e.get("input") for e in model_events)
        assert any((e.get("call") or {}).get("call_refs") for e in model_events)

        # the shell's message_refs are half-open ranges reconstructing the
        # final conversation (stored once — in the message sequence)
        assert all(
            len(ref) == 2 and ref[0] < ref[1] <= len(messages)
            for ref in shell["message_refs"]
        )
        final = [
            messages[i]
            for start, end_exclusive in shell["message_refs"]
            for i in range(start, end_exclusive)
        ]
        assert [m["role"] for m in final] == [m.role for m in original_sample.messages]

        # metadata lives in a sibling entry (written only when non-empty)
        if original_sample.metadata:
            assert json.loads(zf.read(metadata_entry_name(id, epoch))) == (
                original_sample.metadata
            )
        else:
            assert metadata_entry_name(id, epoch) not in names

    # the source (monolith) log classifies as monolith with the same helper
    with zipfile.ZipFile(input_file) as zf:
        assert classify_sample_shape(set(zf.namelist()), id, epoch) == "monolith"


@pytest.mark.parametrize(
    "fixture,pooled",
    [
        (
            "test_list_logs/2024-11-05T13-32-37-05-00_input-task_hxs4q9azL3ySGkjJirypKZ.eval",
            False,
        ),
        (
            "test_list_logs/2024-11-05T13-32-37-05-00_input-task_hxs4q9azL3ySGkjJirypKZ.eval",
            True,
        ),
        ("test_eval_log/log_streaming.eval", False),
    ],
    ids=["input-task", "input-task-pooled", "multi-sample"],
)
def test_convert_chunked_round_trip(tmp_path: pathlib.Path, fixture: str, pooled: bool):
    """Reassembled chunked samples are content-equal to the originals."""
    input_file = _TESTS_DIR / fixture

    if pooled:
        # produce an events_data-pooled input (exercises preserved pool indices)
        pooled_dir = tmp_path / "pooled"
        convert_eval_logs(str(input_file), "eval", str(pooled_dir))
        input_file = pooled_dir / input_file.name

    output_dir = tmp_path / "chunked"
    convert_eval_logs_to_chunked(
        str(input_file), str(output_dir), chunk_size=_CHUNK_SIZE
    )

    original = read_eval_log(str(input_file))
    assert original.samples

    with zipfile.ZipFile(output_dir / input_file.name) as zf:
        for original_sample in original.samples:
            reassembled, attachment_map = _reassemble_chunked_sample(
                zf, original_sample.id, original_sample.epoch
            )
            assert _resolved_dump(reassembled, attachment_map) == _resolved_dump(
                original_sample, original_sample.attachments
            )


def test_convert_chunked_sidecars(tmp_path: pathlib.Path):
    """Every converted sample carries skeleton.json + events/stats.json.

    Stats are consistent with the skeleton (per-type chunk counts sum to
    sample totals) and with raw chunk contents (first/last at chunk
    edges); rechunking changes stats but never the skeleton.
    """
    input_file = _TESTS_DIR / "test_eval_log/log_streaming.eval"

    dirs = (tmp_path / "a", tmp_path / "b")
    for dir, chunk_size in zip(dirs, (_CHUNK_SIZE, _CHUNK_SIZE + 2)):
        convert_eval_logs_to_chunked(str(input_file), str(dir), chunk_size=chunk_size)

    original = read_eval_log(str(input_file))
    assert original.samples

    def read_sidecars(
        zf: zipfile.ZipFile, id: str | int, epoch: int
    ) -> tuple[dict, dict, list[int]]:
        shell = json.loads(zf.read(shell_entry_name(id, epoch)))
        skeleton = json.loads(zf.read(skeleton_entry_name(id, epoch)))
        stats = json.loads(zf.read(events_stats_entry_name(id, epoch)))
        return skeleton, stats, shell["sequences"]["events"]

    with (
        zipfile.ZipFile(dirs[0] / input_file.name) as zf_a,
        zipfile.ZipFile(dirs[1] / input_file.name) as zf_b,
    ):
        rechunked_stats = 0
        for sample in original.samples:
            id, epoch = sample.id, sample.epoch
            skeleton, stats, boundaries = read_sidecars(zf_a, id, epoch)

            # one stats entry per chunk, starts mirroring the chunk entry names
            assert stats["version"] == 1
            chunks = stats["chunks"]
            assert [c["start"] for c in chunks] == [0, *boundaries[:-1]]

            # per-chunk type_counts sum to the skeleton's sample totals
            assert (
                sum(sum(c["type_counts"].values()) for c in chunks)
                == skeleton["counts"]["events"]
            )
            assert (
                sum(c["type_counts"].get("model", 0) for c in chunks)
                == skeleton["counts"]["models"]
            )

            # first/last (type + span_id) match raw chunk contents at the edges
            for c, (start, _) in zip(chunks, boundary_ranges(boundaries)):
                raw = json.loads(
                    zf_a.read(chunk_entry_name(id, epoch, "events", start))
                )
                assert sum(c["type_counts"].values()) == len(raw)
                for edge, event in (("first", raw[0]), ("last", raw[-1])):
                    assert c[edge]["type"] == event["event"]
                    assert c[edge].get("span_id") == event.get("span_id")

            # rechunking changes stats but never the skeleton (modulo
            # `working`: events predating working_start get a parse-time
            # default_factory value, nondeterministic across the two
            # conversions' independent parses — same caveat as _resolved_dump)
            skeleton_b, stats_b, boundaries_b = read_sidecars(zf_b, id, epoch)
            for span in skeleton["spans"] + skeleton_b["spans"]:
                span.pop("working")
            assert skeleton_b == skeleton
            if boundaries_b != boundaries:
                assert stats_b != stats
                rechunked_stats += 1
        # at least one sample spans multiple chunks, exercising the rechunk case
        assert rechunked_stats > 0


def test_convert_chunked_overwrite(tmp_path: pathlib.Path):
    input_file = (
        _TESTS_DIR
        / "test_list_logs/2024-11-05T13-32-37-05-00_input-task_hxs4q9azL3ySGkjJirypKZ.eval"
    )

    convert_eval_logs_to_chunked(str(input_file), str(tmp_path))
    with pytest.raises(FileExistsError):
        convert_eval_logs_to_chunked(str(input_file), str(tmp_path))
    convert_eval_logs_to_chunked(str(input_file), str(tmp_path), overwrite=True)


def test_convert_chunked_cli_hidden():
    from inspect_ai._cli.log import log_command

    command = log_command.get_command(None, "convert-chunked")
    assert command is not None
    assert command.hidden
