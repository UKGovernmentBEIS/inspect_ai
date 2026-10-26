import json
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

import mmh3

from inspect_ai._util.hash import mm3_hash
from inspect_ai.log._transcript import Transcript, transcript
from inspect_ai.model._chat_message import ChatMessage, _logged_json_adapter


@dataclass
class _Sent:
    """What one conversation's agent turns have sent: every message once, where it was first sent.

    A message is new unless the previous input had the same content (`content_key()`) at the position the alignment has reached or later. Each input is aligned against the previous input only: the part that begins as the previous input did is matched whole; past it, a pointer walks the previous input, a message the same as one at or after the pointer is matched and moves the pointer past it, and anything else is new. So a message rebuilt with a fresh id where it was is matched; a message edited, reordered behind a later one, or dropped by one call and restored by a later one is new again; and two equal messages sent at different turns are two messages. Ids play no part, so the fold over a log's inputs is the fold live.
    """

    # every message sent, in the order sent, as the logged snapshots of
    # the inputs (`_snapshot_messages`)
    messages: list[ChatMessage] = field(default_factory=list)
    # the content key of each message of the previous input, in order
    previous: list[str] = field(default_factory=list)

    def record(self, input: Sequence[ChatMessage]) -> None:
        # each key is computed on every send, so an object the scaffold
        # changed in place since it was last sent counts as new
        keys = [content_key(message) for message in input]
        previous = self.previous
        prefix = 0
        while (
            prefix < len(keys)
            and prefix < len(previous)
            and keys[prefix] == previous[prefix]
        ):
            prefix += 1
        pointer = prefix
        later: dict[str, list[int]] | None = None
        for position in range(prefix, len(keys)):
            key = keys[position]
            if pointer < len(previous) and previous[pointer] == key:
                pointer += 1
                continue
            if later is None:
                later = {}
                for at in range(prefix, len(previous)):
                    later.setdefault(previous[at], []).append(at)
            found = later.get(key, [])
            at = bisect_left(found, pointer)
            if at < len(found):
                pointer = found[at] + 1
            else:
                self.messages.append(input[position])
        self.previous = keys


_EXCLUDED = {"id", "source", "metadata"}


def content_key(message: ChatMessage) -> str:
    """A hash of what the model is sent of a message: all but its id, source and metadata.

    It is encoded as the log is (`logged_json()`), so None, NaN and the infinities are told apart. Text with lone surrogates, which UTF-8 JSON cannot encode, is hashed from JSON with them escaped. A message that cannot be serialized at all (such as a numpy array in its tool arguments) is keyed by identity, so it matches only itself: a rebuilt copy of it is new, and an edit made to it in place is not seen.
    """
    try:
        return mmh3.hash_bytes(
            _logged_json_adapter.dump_json(message, exclude=_EXCLUDED)
        ).hex()
    except ValueError:
        pass
    # any value can fail to serialize, in any way; keyed by identity, a
    # message stays alive while its key can match, since the fold holds it
    try:
        logged = _logged_json_adapter.dump_python(
            message, mode="json", exclude=_EXCLUDED
        )
        return mm3_hash(json.dumps(logged))
    except Exception:
        return f"object:{id(message)}"


_sent: "WeakKeyDictionary[Transcript, dict[str, _Sent]]" = WeakKeyDictionary()


def record_sent(conversation: str, input: list[ChatMessage]) -> None:
    """Add what one of the conversation's agent turns sends to what it has sent (see `_Sent`)."""
    _sent.setdefault(transcript(), {}).setdefault(conversation, _Sent()).record(input)


def sent_messages(conversation: str) -> list[ChatMessage]:
    """Every message the conversation's agent turns have sent so far, in the order sent."""
    found = _sent.get(transcript(), {}).get(conversation)
    return list(found.messages) if found is not None else []
