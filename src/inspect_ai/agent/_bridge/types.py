import json
from typing import Sequence

from shortuuid import uuid

from inspect_ai._util.hash import mm3_hash
from inspect_ai.agent._agent import AgentState
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._compaction import (
    Compact,
    CompactionStrategy,
)
from inspect_ai.model._compaction import (
    compaction as create_compaction,
)
from inspect_ai.model._model import GenerateFilter, Model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_info import ToolInfo


class AgentBridge:
    """Agent bridge."""

    def __init__(
        self,
        state: AgentState,
        filter: GenerateFilter | None = None,
        retry_refusals: int | None = None,
        compaction: CompactionStrategy | None = None,
    ) -> None:
        self.state = state
        self.filter = filter
        self.retry_refusals = retry_refusals
        self._compaction = compaction
        self._compaction_prefix = state.messages.copy()
        self._compact: Compact | None = None
        self._message_ids: dict[str, list[str]] = {}
        self._last_message_count = 0

    state: AgentState
    """State updated from messages traveling over the bridge."""

    filter: GenerateFilter | None
    """Filter for bridge model generation.

    A filter may substitute for the default model generation by returning a ModelOutput or return None to allow default processing to continue.
    """

    def compaction(
        self, tools: Sequence[ToolInfo | Tool], model: Model
    ) -> Compact | None:
        """Compaction function for bridge.

        Note: This will always return the same compaction function for a
        given instance of the bridge.

        Args:
            tools: Tool definitions (included in token count as they consume context).
            model: Target model for compacted input.
        """
        if self._compact is None and self._compaction is not None:
            self._compact = create_compaction(
                self._compaction,
                prefix=self._compaction_prefix,
                tools=tools,
                model=model,
            )
        return self._compact

    def _id_for_message(
        self, message: ChatMessage, index: int, conversation: list[ChatMessage]
    ) -> str:
        # message_id we will return
        message_id: str | None = None
        message_key = _message_key(message, index)

        # do we already have an id for this message that isn't in the conversation?
        conversation_ids: set[str] = {m.id for m in conversation if m.id is not None}
        message_ids = self._message_ids.get(message_key, [])
        for id in message_ids:
            if id not in conversation_ids:
                message_id = id
                break

        # if we didn't find an id then generate a new one and update our record
        if message_id is None:
            message_id = uuid()
            message_ids.append(message_id)
            self._message_ids[message_key] = message_ids

        # return the id
        return message_id

    def _track_state(self, input: list[ChatMessage], output: ModelOutput) -> None:
        # automatically track agent state based on observing generations made through
        # the bridge. we need to distinguish between the "main" thread of generation
        # and various types of side / sub-agent calls to the model (e.g. claude code
        # does bash path detection using a side call). our heuristic is to keep the
        # number of messages that were in the _last_ generation, and to update the
        # state whenever the total messages exceeds it. this should pick up normal
        # agent loops that keep appending, while at the same time discarding side model
        # calls that tend to be shorter. finally, this should handle recovering from
        # history compaction, which will shorten the message history considerably
        messages = input + [output.message]

        # Detect compaction: input significantly shorter but not a trivial side call.
        min_main_thread_messages = 5
        if (
            len(input) >= min_main_thread_messages
            and self._last_message_count > 0
            and len(input) < self._last_message_count // 2
        ):
            self._last_message_count = 0

        if len(messages) > self._last_message_count:
            self.state.messages = messages
            self.state.output = output

            # Record hash->ID mappings so future requests can reuse IDs for the
            # same content (critical for stability across API format conversions).
            for idx, msg in enumerate(messages):
                if msg.id is not None:
                    msg_key = _message_key(msg, idx)
                    if msg_key not in self._message_ids:
                        self._message_ids[msg_key] = []
                    if msg.id not in self._message_ids[msg_key]:
                        self._message_ids[msg_key].append(msg.id)

            # Only update on state changes to maintain the high-water mark.
            self._last_message_count = len(messages)


def _message_key(message: ChatMessage, index: int) -> str:
    """Positional key for message ID lookup/storage."""
    return f"{index}:{_normalized_message_hash(message)}"


def _normalized_message_hash(message: ChatMessage) -> str:
    """Hash a message for content-based matching, ignoring fields that vary across API formats.

    Strips `id`, `source`, `model`, `tool_calls[].id`, and reasoning blocks
    before hashing, since these may differ between logically identical messages
    when converted between API formats.
    """
    msg_dict = message.model_dump()

    msg_dict.pop("id", None)
    msg_dict.pop("source", None)
    msg_dict.pop("model", None)

    if msg_dict.get("tool_calls"):
        msg_dict["tool_calls"] = [
            {
                "function": tc.get("function"),
                "arguments": tc.get("arguments"),
                "type": tc.get("type"),
            }
            for tc in msg_dict["tool_calls"]
        ]

    if isinstance(msg_dict.get("content"), list):
        msg_dict["content"] = [
            part
            for part in msg_dict["content"]
            if not (isinstance(part, dict) and part.get("type") == "reasoning")
        ]

    normalized_json = json.dumps(msg_dict, sort_keys=True, default=str)
    return mm3_hash(normalized_json)
