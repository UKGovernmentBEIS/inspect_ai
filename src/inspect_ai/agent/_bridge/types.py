import json
from functools import lru_cache
from typing import Sequence, Set

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
        self._message_ids = {}
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
        self, message: ChatMessage, conversation: list[ChatMessage]
    ) -> str:
        # message_id we will return
        message_id: str | None = None

        # turn message into a normalized hash so it can be a dictionary key
        # We normalize to remove fields that may differ between message instances
        # that should be considered the same (e.g., source field, tool_call IDs)
        message_key = _normalized_message_hash(message)

        # do we already have an id for this message that isn't in the conversation?
        conversation_ids: Set[str] = {m.id for m in conversation if m.id is not None}
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

    _message_ids: dict[str, list[str]]

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
        if len(messages) > self._last_message_count:
            self.state.messages = messages
            self.state.output = output

            # Store the output message's hash->ID mapping so that when the same
            # content comes back as input in future requests, we can reuse the ID.
            # This is critical for message ID stability across API format conversions.
            out_msg = output.message
            if out_msg.id is not None:
                msg_key = _normalized_message_hash(out_msg)
                if msg_key not in self._message_ids:
                    self._message_ids[msg_key] = []
                if out_msg.id not in self._message_ids[msg_key]:
                    self._message_ids[msg_key].append(out_msg.id)

        self._last_message_count = len(messages)


@lru_cache(maxsize=100)
def message_json_hash(message_json: str) -> str:
    return mm3_hash(message_json)


def _normalized_message_hash(message: ChatMessage) -> str:
    """Create a hash for message matching that ignores variable fields.

    When messages travel through different API formats (e.g., Google Gemini -> Inspect),
    some fields may differ even for logically identical messages:
    - `id`: Always excluded (it's what we're trying to match)
    - `source`: May be present in outputs ("generate") but not in converted inputs
    - `model`: Present in outputs but not in converted inputs
    - `tool_calls[].id`: Different API formats use different ID schemes

    This function normalizes these differences to enable matching.
    """
    # Get message as dict
    msg_dict = message.model_dump()

    # Remove variable fields that may differ between output and converted input
    msg_dict.pop("id", None)
    msg_dict.pop("source", None)
    msg_dict.pop("model", None)

    # Normalize tool_calls by removing their IDs but keeping function name and arguments
    if "tool_calls" in msg_dict and msg_dict["tool_calls"]:
        normalized_tool_calls = []
        for tc in msg_dict["tool_calls"]:
            normalized_tc = {
                "function": tc.get("function"),
                "arguments": tc.get("arguments"),
                "type": tc.get("type"),
            }
            normalized_tool_calls.append(normalized_tc)
        msg_dict["tool_calls"] = normalized_tool_calls

    # Create deterministic JSON string for hashing
    normalized_json = json.dumps(msg_dict, sort_keys=True, default=str)
    return mm3_hash(normalized_json)
