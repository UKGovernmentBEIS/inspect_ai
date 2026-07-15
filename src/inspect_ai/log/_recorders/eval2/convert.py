"""Convert `.eval` logs to the experimental `.eval2` chunked format.

See ``format.py`` for the zip layout and
``design/plans/sample-data-pagination.md`` for the format design.
"""

import os
import shutil
import tempfile
from typing import Any, NamedTuple, Sequence
from zipfile import ZipFile

from pydantic import JsonValue

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
from inspect_ai.model._chat_message import ChatMessage

from ..._condense import (
    WalkContext,
    resolve_attachments_fn,
    walk_chat_message,
    walk_chat_messages,
    walk_events,
    walk_input,
    walk_json_value,
)
from ..._file import log_files_from_ls
from ..._log import EvalSample
from ..eval import (
    HEADER_JSON,
    REDUCTIONS_JSON,
    SUMMARIES_JSON,
    EvalRecorder,
)
from .format import (
    CALLS_SEQUENCE,
    DEFAULT_CHUNK_SIZE,
    EVAL2_LOG_FILE_EXTENSION,
    EVENTS_SEQUENCE,
    MESSAGES_SEQUENCE,
    chunk_entry_name,
    chunk_ranges,
    shell_entry_name,
)


def convert_eval_logs_to_eval2(
    path: str,
    output_dir: str,
    overwrite: bool = False,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> None:
    """Convert `.eval` log file(s) to the experimental `.eval2` chunked format.

    Args:
        path: Path to source log file(s). Either a single `.eval` file
            or a directory containing `.eval` files.
        output_dir: Output directory to write converted `.eval2` file(s) to.
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

        output_file = (
            f"{output_dir}{output_fs.sep}{output_file_basename}"
            f"{EVAL2_LOG_FILE_EXTENSION}"
        )
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
                "(only the .eval format can be converted to .eval2)."
            )
        convert_file(path)
    else:
        root_dir = fs.info(path).name
        eval_logs = log_files_from_ls(fs.ls(path, recursive=True), ["eval"], True)
        input_files = [
            eval_log.name.replace(f"{root_dir}/", "", 1) for eval_log in eval_logs
        ]
        display().print("Converting log files to .eval2...")
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
                for name in (HEADER_JSON, SUMMARIES_JSON, REDUCTIONS_JSON):
                    if directory.entry(name) is not None:
                        zip.writestr(name, await reader.read_member_fully(name))

                for id, epoch in sample_ids:
                    sample = await EvalRecorder.read_log_sample(
                        input_file, id, epoch, reader=reader
                    )
                    _write_eval2_sample(zip, sample, chunk_size)

            temp.seek(0)
            with file(output_file, "wb") as output:
                shutil.copyfileobj(temp, output)


class Eval2Sample(NamedTuple):
    """An `EvalSample` restructured into `.eval2` shell + sequences."""

    shell: dict[str, Any]
    messages: list[ChatMessage]
    events: list[Event]
    calls: list[JsonValue]


def eval2_sample(sample: EvalSample, chunk_size: int) -> Eval2Sample:
    """Restructure an `EvalSample` for the `.eval2` format.

    - Attachments are resolved fully into content (`.eval2` has no
      attachments entry); each message lives exactly once in the message
      sequence, so resolution does not re-duplicate large content.
    - The message sequence is the `events_data` pool (indices preserved,
      so existing `input_refs` remain valid) extended with any
      final-conversation messages not already pooled. The shell's final
      conversation becomes range-encoded refs (`message_refs`) into the
      sequence.
    - Inline `ModelEvent` inputs/calls (logs that predate pooling) are
      condensed into the sequences.
    """
    content_fn = resolve_attachments_fn(sample.attachments)
    # a single shared cache is safe (unlike condense_sample) because every
    # walk applies the same resolving content_fn
    context = WalkContext(message_cache={}, only_core=False)

    events_data = sample.events_data
    messages = [
        walk_chat_message(message, content_fn, context)
        for message in (events_data["messages"] if events_data else [])
    ]
    calls = [
        walk_json_value(call, content_fn, context)
        for call in (events_data["calls"] if events_data else [])
    ]
    events = walk_events(sample.events, content_fn, context)
    # walk_model_output walks only choices, not the stored completion field,
    # so refs written there by older inspect versions survive the events
    # walk — resolve them here
    events = [
        event.model_copy(
            update={
                "output": event.output.model_copy(
                    update={"completion": content_fn(event.output.completion)}
                )
            }
        )
        if isinstance(event, ModelEvent)
        else event
        for event in events
    ]
    final_messages = walk_chat_messages(sample.messages, content_fn, context)
    input = walk_input(sample.input, content_fn, context)

    events, msg_index, new_msgs = condense_model_event_inputs(
        events, len(messages), _build_msg_index(messages)
    )
    messages += [message for _, message in new_msgs]
    events, _, new_calls = condense_model_event_calls(
        events, len(calls), _build_call_index(calls)
    )
    calls += [call for _, call in new_calls]

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

    shell = sample.model_copy(update={"input": input}).model_dump(
        mode="json",
        exclude_none=True,
        exclude={"messages", "events", "attachments", "events_data"},
    )
    shell["message_refs"] = _compress_refs(indices)
    shell["sequences"] = {
        "chunk_size": chunk_size,
        "messages": {"count": len(messages)},
        "events": {"count": len(events)},
        "calls": {"count": len(calls)},
    }

    return Eval2Sample(shell=shell, messages=messages, events=events, calls=calls)


def _write_eval2_sample(zip: ZipFile, sample: EvalSample, chunk_size: int) -> None:
    converted = eval2_sample(sample, chunk_size)

    zip.writestr(
        shell_entry_name(sample.id, sample.epoch),
        to_json_safe(converted.shell, indent=None),
    )

    sequences: list[tuple[str, Sequence[Any]]] = [
        (MESSAGES_SEQUENCE, converted.messages),
        (EVENTS_SEQUENCE, converted.events),
        (CALLS_SEQUENCE, converted.calls),
    ]
    for sequence, items in sequences:
        for start, end_exclusive in chunk_ranges(len(items), chunk_size):
            zip.writestr(
                chunk_entry_name(
                    sample.id, sample.epoch, sequence, start, end_exclusive
                ),
                to_json_safe(items[start:end_exclusive], indent=None),
            )
