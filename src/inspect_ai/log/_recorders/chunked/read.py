"""Read a chunked sample back as the `EvalSample` its monolith would give."""

import json
import re
from functools import partial
from typing import Any

from inspect_ai._util._async import tg_collect
from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.url import is_data_uri
from inspect_ai.event._pool import _expand_refs

from ..._condense import (
    ATTACHMENT_PROTOCOL,
    WalkContext,
    attachment_refs_from_object,
    walk_chat_messages,
    walk_input,
)
from ..._log import EvalSample
from .format import (
    ATTACHMENTS_SEQUENCE,
    CALLS_SEQUENCE,
    EVENTS_SEQUENCE,
    MESSAGES_SEQUENCE,
    chunk_entry_name,
    metadata_entry_name,
    sample_prefix,
    shell_entry_name,
)

# the on-disk refs are index-addressed whole JSON strings, so a literal
# "attachment://<n>" that is a whole short string is indistinguishable from a
# ref; the writer's hash form is not. The closing quote keeps
# "attachment://0abc" and longer text alone.
_INDEX_REF = re.compile(rb'attachment://(\d+)(?=")')


async def read_chunked_sample(
    reader: AsyncZipReader,
    names: set[str],
    id: str | int,
    epoch: int,
    exclude_fields: set[str] | None = None,
) -> EvalSample:
    """Inverse of `convert._write_chunked_sample`.

    Refs go back from `attachment://<index>` to `attachment://<hash>` (the hash
    is the content's `mm3_hash`, so the attachments map is keyed as a monolith's),
    the final conversation is expanded from `message_refs` into the messages
    sequence, and the text the writer extracted from it and from `input` is
    inlined again (a monolith writer extracts only images from those two). A
    sequence whose field is excluded is not read, so attachments referenced only
    from it are dropped.
    """
    exclude = exclude_fields or set()
    chunks = partial(_chunks, reader, names, id, epoch)
    attachments: list[str] = (
        [] if "attachments" in exclude else _items(await chunks(ATTACHMENTS_SEQUENCE))
    )
    hashes = [mm3_hash(content).encode() for content in attachments]

    def rekey(data: bytes) -> bytes:
        def hash_ref(match: re.Match[bytes]) -> bytes:
            index = int(match.group(1))
            if index < len(hashes):
                return ATTACHMENT_PROTOCOL.encode() + hashes[index]
            return match.group(0)

        return _INDEX_REF.sub(hash_ref, data)

    data: dict[str, Any] = json.loads(
        rekey(await reader.read_member_fully(shell_entry_name(id, epoch)))
    )
    message_refs = data.pop("message_refs")
    pool: list[Any] = []
    if not {"messages", "events"} <= exclude:
        pool = _items([rekey(chunk) for chunk in await chunks(MESSAGES_SEQUENCE)])
    if "messages" not in exclude:
        data["messages"] = _expand_refs(message_refs, pool)
    if "events" not in exclude:
        data["events"] = _items(
            [rekey(chunk) for chunk in await chunks(EVENTS_SEQUENCE)]
        )
        data["events_data"] = {
            "messages": pool,
            "calls": _items([rekey(chunk) for chunk in await chunks(CALLS_SEQUENCE)]),
        }
    metadata_entry = metadata_entry_name(id, epoch)
    if "metadata" not in exclude and metadata_entry in names:
        data["metadata"] = json.loads(
            rekey(await reader.read_member_fully(metadata_entry))
        )
    for field in exclude:
        data.pop(field, None)
    data["attachments"] = {
        hash.decode(): content for hash, content in zip(hashes, attachments)
    }
    sample = EvalSample.model_validate(data, context=get_deserializing_context())
    return _inline_extracted_text(sample)


def _inline_extracted_text(sample: EvalSample) -> EvalSample:
    inlined = False

    def content_fn(text: str) -> str:
        nonlocal inlined
        content = sample.attachments.get(text.removeprefix(ATTACHMENT_PROTOCOL))
        if content is None or is_data_uri(content):
            return text
        inlined = True
        return content

    context = WalkContext(message_cache={}, only_core=False)
    sample = sample.model_copy(
        update={
            "input": walk_input(sample.input, content_fn, context),
            "messages": walk_chat_messages(sample.messages, content_fn, context),
        }
    )
    if not inlined:
        return sample
    # an inlined text that nothing else refers to was never a monolith attachment
    referenced = attachment_refs_from_object(
        sample.model_copy(update={"attachments": {}})
    )
    return sample.model_copy(
        update={
            "attachments": {
                hash: content
                for hash, content in sample.attachments.items()
                if hash in referenced
            }
        }
    )


async def _chunks(
    reader: AsyncZipReader, names: set[str], id: str | int, epoch: int, sequence: str
) -> list[bytes]:
    """A sequence's chunk entries in order; each is named by its first item's index."""
    prefix = f"{sample_prefix(id, epoch)}/{sequence}/"
    starts = sorted(
        int(stem)
        for name in names
        if name.startswith(prefix)
        and (stem := name[len(prefix) :].removesuffix(".json")).isdigit()
    )
    return await tg_collect(
        [
            partial(
                reader.read_member_fully, chunk_entry_name(id, epoch, sequence, start)
            )
            for start in starts
        ]
    )


def _items(chunks: list[bytes]) -> list[Any]:
    return [item for chunk in chunks for item in json.loads(chunk)]
