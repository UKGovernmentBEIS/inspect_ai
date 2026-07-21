"""Convert `.eval` logs to `.eval` files with chunked samples.

Every sample is converted to the chunked per-sample shape,
unconditionally — chunking is writer policy, and small samples chunk
too (see the "Small-sample monolith threshold" amendment in
``design/large-samples.md``). See ``format.py`` for the zip layout.
"""

import os
import re
import shutil
import tempfile
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple
from zipfile import ZipFile

from pydantic import BaseModel, JsonValue

from inspect_ai._util._async import run_coroutine
from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import exists, file, filesystem
from inspect_ai._util.json import to_json_safe
from inspect_ai._util.zipfile import zipfile_compress_kwargs
from inspect_ai.event._event import Event
from inspect_ai.event._pool import (
    _build_call_index,
    _build_msg_index,
    _compress_refs,
    _msg_hash,
    condense_model_event_calls,
    condense_model_event_inputs,
)
from inspect_ai.model._chat_message import ChatMessage

from ..._condense import (
    WalkContext,
    events_attachment_fn,
    walk_chat_messages,
    walk_input,
)
from ..._file import log_files_from_ls
from ..._log import EvalSample
from ..._skeleton import sample_skeleton
from ..eval import (
    HEADER_JSON,
    JOURNAL_DIR,
    REDUCTIONS_JSON,
    SUMMARIES_JSON,
    EvalRecorder,
)
from .format import (
    ATTACHMENTS_SEQUENCE,
    CALLS_SEQUENCE,
    DEFAULT_ATTACHMENTS_CHUNK_BYTES,
    DEFAULT_CHUNK_SIZE,
    EVENTS_SEQUENCE,
    MESSAGES_SEQUENCE,
    attachment_chunk_boundaries,
    boundary_ranges,
    chunk_boundaries,
    chunk_entry_name,
    chunk_ranges,
    events_stats_entry_name,
    metadata_entry_name,
    shell_entry_name,
    skeleton_entry_name,
)
from .stats import event_stats


def convert_eval_logs_to_chunked(
    path: str,
    output_dir: str,
    overwrite: bool = False,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> None:
    """Convert `.eval` log file(s) to `.eval` files with chunked samples.

    Args:
        path: Path to source log file(s). Either a single `.eval` file
            or a directory containing `.eval` files.
        output_dir: Output directory to write converted `.eval` file(s) to.
        overwrite: Overwrite existing log files (defaults to `False`,
            raising an error if the output file path already exists).
        chunk_size: Maximum items per sequence chunk entry.
    """
    from inspect_ai._display import display

    fs = filesystem(path)
    if not fs.exists(path):
        raise PrerequisiteError(f"Error: path '{path}' does not exist.")

    output_fs = filesystem(output_dir)
    if output_dir.endswith(output_fs.sep):
        output_dir = output_dir[: -len(output_fs.sep)]
    output_fs.mkdir(output_dir, exist_ok=True)

    path_is_dir = fs.info(path).type == "directory"

    # convert a single file (input file is relative to 'path' for directories)
    def convert_file(input_file: str) -> None:
        input_name, _ = os.path.splitext(input_file)
        input_dir = os.path.dirname(input_name.replace("\\", "/"))

        if path_is_dir:
            target_dir = f"{output_dir}{output_fs.sep}{input_dir}"
            input_file = f"{path}{fs.sep}{input_file}"
            output_file_basename = input_name
        else:
            target_dir = output_dir
            output_file_basename = os.path.basename(input_name)

        output_fs.mkdir(target_dir, exist_ok=True)

        output_file = f"{output_dir}{output_fs.sep}{output_file_basename}.eval"
        if exists(output_file) and not overwrite:
            raise FileExistsError(
                f"Output file {output_file} already exists "
                "(use --overwrite to overwrite existing files)"
            )

        run_coroutine(_convert_log_file(input_file, output_file, chunk_size))

    if not path_is_dir:
        if not path.endswith(".eval"):
            raise PrerequisiteError(
                f"Error: '{path}' is not a .eval log file "
                "(only the .eval format can be converted to chunked samples)."
            )
        convert_file(path)
    else:
        root_dir = fs.info(path).name
        eval_logs = log_files_from_ls(fs.ls(path, recursive=True), ["eval"], True)
        input_files = [
            eval_log.name.replace(f"{root_dir}/", "", 1) for eval_log in eval_logs
        ]
        display().print("Converting log files to chunked samples...")
        with display().progress(total=len(input_files)) as p:
            for input_file in input_files:
                convert_file(input_file)
                p.update()


async def _convert_log_file(input_file: str, output_file: str, chunk_size: int) -> None:
    sample_ids = await EvalRecorder.read_log_sample_ids(input_file)

    async with AsyncFilesystem() as fs:
        reader = AsyncZipReader(fs, input_file)
        directory = await reader.entries()
        with tempfile.TemporaryFile() as temp:
            with ZipFile(temp, mode="w", **zipfile_compress_kwargs) as zip:
                # top-level entries (and _journal/) pass through unchanged
                top_level = [
                    name
                    for name in (HEADER_JSON, SUMMARIES_JSON, REDUCTIONS_JSON)
                    if directory.entry(name) is not None
                ]
                journal = [
                    entry.filename
                    for entry in directory.entries
                    if entry.filename.startswith(f"{JOURNAL_DIR}/")
                ]
                for name in top_level + journal:
                    zip.writestr(name, await reader.read_member_fully(name))

                for id, epoch in sample_ids:
                    sample = await EvalRecorder.read_log_sample(
                        input_file, id, epoch, reader=reader
                    )
                    _write_chunked_sample(zip, sample, chunk_size)

            temp.seek(0)
            with file(output_file, "wb") as output:
                shutil.copyfileobj(temp, output)


class ChunkedSample(NamedTuple):
    """An `EvalSample` restructured into the chunked shell + sequences."""

    shell: dict[str, Any]
    messages: list[ChatMessage]
    events: list[Event]
    calls: list[JsonValue]
    attachments: list[str]
    attachment_index: dict[str, int]
    """Attachment hash -> sequence index (for renumbering refs)."""
    attachment_boundaries: list[int]


def chunked_sample(sample: EvalSample, chunk_size: int) -> ChunkedSample:
    """Restructure an `EvalSample` for the chunked per-sample shape.

    - The message sequence is the `events_data` pool (indices preserved,
      so existing `input_refs` remain valid) extended with any
      final-conversation messages not already pooled. The shell's final
      conversation becomes range-encoded refs (`message_refs`) into the
      sequence.
    - Inline `ModelEvent` inputs/calls (logs that predate pooling) are
      condensed into the sequences.
    - Attachments become a fourth sequence (identity = sequence index;
      refs are renumbered from `attachment://<hash>` to
      `attachment://<index>` at serialization time). They stay extracted
      because content dedups *across containers* (pooled message, wire
      request/response, tool event, state delta, tool schema) — inlining
      measured ~5x content growth on attachment-heavy logs.
    """
    events_data = sample.events_data
    messages = list(events_data["messages"]) if events_data else []
    calls = list(events_data["calls"]) if events_data else []

    events, msg_index, new_msgs = condense_model_event_inputs(
        list(sample.events), len(messages), _build_msg_index(messages)
    )
    messages += [message for _, message in new_msgs]
    events, _, new_calls = condense_model_event_calls(
        events, len(calls), _build_call_index(calls)
    )
    calls += [call for _, call in new_calls]

    # walk the final conversation and input with the events-flavored
    # attachment extraction: sample.messages was written with the weaker
    # messages-flavor walk (long text left inline), and content-hash dedup
    # against the pool only merges identical bytes
    attachments = dict(sample.attachments)
    content_fn = events_attachment_fn(attachments, log_images=True)
    context = WalkContext(message_cache={}, only_core=False)
    final_messages = walk_chat_messages(sample.messages, content_fn, context)
    input = walk_input(sample.input, content_fn, context)

    # extend the sequence with final-conversation messages not already pooled
    indices: list[int] = []
    for message in final_messages:
        hash = _msg_hash(message)
        index = msg_index.get(hash)
        if index is None:
            index = len(messages)
            msg_index[hash] = index
            messages.append(message)
        indices.append(index)

    attachment_contents = list(attachments.values())
    attachment_boundaries = attachment_chunk_boundaries(
        [len(content.encode()) for content in attachment_contents],
        DEFAULT_ATTACHMENTS_CHUNK_BYTES,
    )

    shell = sample.model_copy(update={"input": input}).model_dump(
        mode="json",
        exclude_none=True,
        exclude={"messages", "events", "attachments", "events_data", "metadata"},
    )
    shell["message_refs"] = _compress_refs(indices)
    # must mirror the chunk entry names written by _write_chunked_sample
    shell["sequences"] = {
        MESSAGES_SEQUENCE: chunk_boundaries(len(messages), chunk_size),
        EVENTS_SEQUENCE: chunk_boundaries(len(events), chunk_size),
        CALLS_SEQUENCE: chunk_boundaries(len(calls), chunk_size),
        ATTACHMENTS_SEQUENCE: attachment_boundaries,
    }

    return ChunkedSample(
        shell=shell,
        messages=messages,
        events=events,
        calls=calls,
        attachments=attachment_contents,
        attachment_index={hash: i for i, hash in enumerate(attachments)},
        attachment_boundaries=attachment_boundaries,
    )


_ATTACHMENT_REF_PATTERN = re.compile(rb"attachment://([0-9a-f]{32})")


def _attachment_ref_renumberer(
    attachment_index: dict[str, int],
) -> Callable[[bytes], bytes]:
    """Rewrite `attachment://<hash>` refs to `attachment://<index>` in JSON bytes.

    Operates on serialized JSON so every ref site is covered uniformly
    (including ones the typed walkers miss, e.g. `ModelOutput.completion`,
    state-event deltas, and provider response payloads — the pattern's
    characters are never escaped by JSON encoding). Unknown hashes are left
    untouched, matching resolve_sample_attachments' fallback.
    """
    replacements = {
        hash.encode(): b"attachment://%d" % index
        for hash, index in attachment_index.items()
    }

    def renumber(data: bytes) -> bytes:
        return _ATTACHMENT_REF_PATTERN.sub(
            lambda m: replacements.get(m.group(1), m.group(0)), data
        )

    return renumber


def _write_sidecar(zip: ZipFile, entry_name: str, sidecar: BaseModel) -> None:
    """Write a derived sidecar in its canonical JSON form (exclude_none)."""
    zip.writestr(
        entry_name,
        to_json_safe(sidecar.model_dump(mode="json", exclude_none=True), indent=None),
    )


def _write_chunked_sample(zip: ZipFile, sample: EvalSample, chunk_size: int) -> None:
    converted = chunked_sample(sample, chunk_size)
    renumber = _attachment_ref_renumberer(converted.attachment_index)

    zip.writestr(
        shell_entry_name(sample.id, sample.epoch),
        renumber(to_json_safe(converted.shell, indent=None)),
    )

    if sample.metadata:
        zip.writestr(
            metadata_entry_name(sample.id, sample.epoch),
            renumber(to_json_safe(sample.metadata, indent=None)),
        )

    # derived sidecars: neither contains event payloads (span names, types,
    # timestamps, counts only), so no attachment-ref renumbering applies
    _write_sidecar(
        zip,
        skeleton_entry_name(sample.id, sample.epoch),
        sample_skeleton(converted.events),
    )
    _write_sidecar(
        zip,
        events_stats_entry_name(sample.id, sample.epoch),
        event_stats(converted.events, converted.shell["sequences"][EVENTS_SEQUENCE]),
    )

    sequences: list[tuple[str, Sequence[Any]]] = [
        (MESSAGES_SEQUENCE, converted.messages),
        (EVENTS_SEQUENCE, converted.events),
        (CALLS_SEQUENCE, converted.calls),
    ]
    for sequence, items in sequences:
        for start, end_exclusive in chunk_ranges(len(items), chunk_size):
            zip.writestr(
                chunk_entry_name(sample.id, sample.epoch, sequence, start),
                renumber(to_json_safe(items[start:end_exclusive], indent=None)),
            )

    # attachment contents are stored verbatim (no renumbering inside them)
    for start, end_exclusive in boundary_ranges(converted.attachment_boundaries):
        zip.writestr(
            chunk_entry_name(sample.id, sample.epoch, ATTACHMENTS_SEQUENCE, start),
            to_json_safe(converted.attachments[start:end_exclusive], indent=None),
        )
