"""Convert `.eval` logs to `.eval` files with chunked samples.

Every sample is converted to the chunked per-sample shape,
unconditionally — chunking is writer policy, and small samples chunk
too (see the "Small-sample monolith threshold" amendment in
``design/large-samples.md``). See ``format.py`` for the zip layout.
"""

import os
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
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._pool import (
    _build_call_index,
    _build_msg_index,
    _compress_refs,
    _msg_hash,
    condense_model_event_calls,
    condense_model_event_inputs,
)
from inspect_ai.event._subtask import SubtaskEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.model._chat_message import ChatMessage

from ..._condense import (
    ATTACHMENT_PROTOCOL,
    WalkContext,
    events_attachment_fn,
    walk_chat_messages,
    walk_events,
    walk_input,
    walk_json_value,
)
from ..._file import (
    contained_log_destination,
    log_files_from_ls,
    resolve_local_path,
)
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
    events_uuids_entry_name,
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
    attachments_chunk_bytes: int = DEFAULT_ATTACHMENTS_CHUNK_BYTES,
) -> None:
    """Convert `.eval` log file(s) to `.eval` files with chunked samples.

    Args:
        path: Path to source log file(s). Either a single `.eval` file
            or a directory containing `.eval` files.
        output_dir: Output directory to write converted `.eval` file(s) to.
        overwrite: Overwrite existing log files (defaults to `False`,
            raising an error if the output file path already exists).
        chunk_size: Maximum items per sequence chunk entry.
        attachments_chunk_bytes: Target uncompressed bytes per attachments
            chunk entry (attachments chunk by size, not count).
    """
    from inspect_ai._display import display

    fs = filesystem(path)
    if not fs.exists(path):
        raise PrerequisiteError(f"Error: path '{path}' does not exist.")

    output_dir = resolve_local_path(output_dir)
    output_fs = filesystem(output_dir)
    if output_dir.endswith(output_fs.sep):
        output_dir = output_dir[: -len(output_fs.sep)]
    output_fs.mkdir(output_dir, exist_ok=True)

    path_is_dir = fs.info(path).type == "directory"

    # convert a single file (input file is relative to 'path' for directories)
    def convert_file(input_file: str, output_file: str | None = None) -> None:
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

        if output_file is None:
            output_file = f"{output_dir}{output_fs.sep}{output_file_basename}.eval"
        if exists(output_file) and not overwrite:
            raise FileExistsError(
                f"Output file {output_file} already exists "
                "(use --overwrite to overwrite existing files)"
            )

        run_coroutine(
            _convert_log_file(
                input_file, output_file, chunk_size, attachments_chunk_bytes
            )
        )

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
        destinations = [
            contained_log_destination(
                eval_log.name, root_dir, output_dir, extension="eval"
            )
            for eval_log in eval_logs
        ]
        display().print("Converting log files to chunked samples...")
        with display().progress(total=len(destinations)) as p:
            for destination in destinations:
                convert_file(destination.relative, destination.destination)
                p.update()


async def _convert_log_file(
    input_file: str, output_file: str, chunk_size: int, attachments_chunk_bytes: int
) -> None:
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
                    _write_chunked_sample(
                        zip, sample, chunk_size, attachments_chunk_bytes
                    )

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


def chunked_sample(
    sample: EvalSample,
    chunk_size: int,
    attachments_chunk_bytes: int = DEFAULT_ATTACHMENTS_CHUNK_BYTES,
) -> ChunkedSample:
    """Restructure an `EvalSample` for the chunked per-sample shape.

    - The message sequence is the `events_data` pool (indices preserved,
      so existing `input_refs` remain valid) extended with any
      final-conversation messages not already pooled. The shell's final
      conversation becomes range-encoded refs (`message_refs`) into the
      sequence.
    - Inline `ModelEvent` inputs/calls (logs that predate pooling) are
      condensed into the sequences.
    - Attachments become a fourth sequence (identity = sequence index;
      refs in messages, events, calls and the shell are renumbered from
      `attachment://<hash>` to `attachment://<index>`). They stay extracted
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
        attachments_chunk_bytes,
    )
    attachment_index = {hash: i for i, hash in enumerate(attachments)}

    # renumber references only where the typed walkers resolve them, so
    # plain text that reads like a reference stays as written
    renumber_fn = _typed_ref_renumberer(attachment_index)

    def renumber_context() -> WalkContext:
        return WalkContext(message_cache={}, only_core=False, media_fn=renumber_fn)

    def renumber_events(events: list[Event]) -> list[Event]:
        events = _renumber_completion_refs(events, renumber_fn)
        events = _renumber_legacy_nested_refs(events, renumber_fn)
        return walk_events(events, renumber_fn, renumber_context())

    messages = walk_chat_messages(messages, renumber_fn, renumber_context())
    events = renumber_events(events)
    calls_context = renumber_context()
    calls = [
        walk_json_value(call, renumber_fn, calls_context, keep_too_deep=True)
        for call in calls
    ]
    input = walk_input(input, renumber_fn, renumber_context())
    error_retries = (
        [
            retry.model_copy(update={"events": renumber_events(retry.events)})
            if retry.events is not None
            else retry
            for retry in sample.error_retries
        ]
        if sample.error_retries is not None
        else None
    )

    shell = sample.model_copy(
        update={"input": input, "error_retries": error_retries}
    ).model_dump(
        mode="json",
        exclude_none=True,
        exclude={"messages", "events", "attachments", "events_data", "metadata"},
    )
    shell["message_refs"] = _compress_refs(indices)

    return ChunkedSample(
        shell=shell,
        messages=messages,
        events=events,
        calls=calls,
        attachments=attachment_contents,
        attachment_index=attachment_index,
        attachment_boundaries=attachment_boundaries,
    )


def _renumber_completion_refs(
    events: list[Event], renumber_fn: Callable[[str], str]
) -> list[Event]:
    """Renumber model-event completions that older logs condensed into a reference.

    Inspect no longer condenses `ModelOutput.completion`, which the typed
    walkers treat as plain text, but older logs hold a reference there: the
    same one as their first choice's message text. Only such a completion
    is renumbered; other completion text stays as written. (In a new log the
    message text is an attachment reference only when the completion is
    not the same string.)
    """

    def renumbered(event: Event) -> Event:
        if not isinstance(event, ModelEvent) or not event.output.choices:
            return event
        completion = event.output.completion
        if completion != event.output.choices[0].message.text:
            return event
        new_completion = renumber_fn(completion)
        if new_completion == completion:
            return event
        return event.model_copy(
            update={
                "output": event.output.model_copy(update={"completion": new_completion})
            }
        )

    return [renumbered(event) for event in events]


def _renumber_legacy_nested_refs(
    events: list[Event], renumber_fn: Callable[[str], str]
) -> list[Event]:
    """Renumber references in the deprecated nested events of older logs.

    `SubtaskEvent.events` and `ToolEvent.events` are typed `list[Any]`, so
    they reload as plain dicts, which the typed walkers leave untouched.
    Inspect no longer writes them; the older writers that did condensed them
    into references, so each string in them that is a whole reference is
    renumbered.
    """

    def renumbered_value(value: Any) -> Any:
        if isinstance(value, str):
            return renumber_fn(value)
        elif isinstance(value, list):
            return [renumbered_value(item) for item in value]
        elif isinstance(value, dict):
            return {key: renumbered_value(item) for key, item in value.items()}
        else:
            return value

    def renumbered_nested(nested: list[Any]) -> list[Any]:
        return [
            renumbered_value(item)
            if isinstance(item, dict)
            else renumbered(item)
            if isinstance(item, (SubtaskEvent, ToolEvent))
            else item
            for item in nested
        ]

    def renumbered(event: Event) -> Event:
        if isinstance(event, (SubtaskEvent, ToolEvent)) and event.events:
            return event.model_copy(update={"events": renumbered_nested(event.events)})
        return event

    return [renumbered(event) for event in events]


def _typed_ref_renumberer(attachment_index: dict[str, int]) -> Callable[[str], str]:
    """Content function rewriting an `attachment://<hash>` ref to `attachment://<index>`.

    Unknown hashes are left untouched, matching resolve_sample_attachments'
    fallback.
    """

    def renumber(text: str) -> str:
        if text.startswith(ATTACHMENT_PROTOCOL):
            index = attachment_index.get(text.removeprefix(ATTACHMENT_PROTOCOL))
            if index is not None:
                return f"{ATTACHMENT_PROTOCOL}{index}"
        return text

    return renumber


def _write_sidecar(zip: ZipFile, entry_name: str, sidecar: BaseModel) -> None:
    """Write a derived sidecar in its canonical JSON form (exclude_none)."""
    zip.writestr(
        entry_name,
        to_json_safe(sidecar.model_dump(mode="json", exclude_none=True), indent=None),
    )


def _write_chunked_sample(
    zip: ZipFile,
    sample: EvalSample,
    chunk_size: int,
    attachments_chunk_bytes: int = DEFAULT_ATTACHMENTS_CHUNK_BYTES,
) -> None:
    converted = chunked_sample(sample, chunk_size, attachments_chunk_bytes)

    zip.writestr(
        shell_entry_name(sample.id, sample.epoch),
        to_json_safe(converted.shell, indent=None),
    )

    # metadata holds raw values, never attachment references
    if sample.metadata:
        zip.writestr(
            metadata_entry_name(sample.id, sample.epoch),
            to_json_safe(sample.metadata, indent=None),
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
        event_stats(
            converted.events, chunk_boundaries(len(converted.events), chunk_size)
        ),
    )
    zip.writestr(
        events_uuids_entry_name(sample.id, sample.epoch),
        to_json_safe([event.uuid for event in converted.events], indent=None),
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
                to_json_safe(items[start:end_exclusive], indent=None),
            )

    # attachment contents are stored verbatim (no renumbering inside them)
    for start, end_exclusive in boundary_ranges(converted.attachment_boundaries):
        zip.writestr(
            chunk_entry_name(sample.id, sample.epoch, ATTACHMENTS_SEQUENCE, start),
            to_json_safe(converted.attachments[start:end_exclusive], indent=None),
        )
