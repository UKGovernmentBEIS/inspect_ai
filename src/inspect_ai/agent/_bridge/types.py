from functools import lru_cache
from typing import Sequence, Set

from shortuuid import uuid

from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.agent._agent import AgentState
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
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
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo


class AgentBridge:
    """Agent bridge."""

    def __init__(
        self,
        state: AgentState,
        filter: GenerateFilter | None = None,
        retry_refusals: int | None = None,
        compaction: CompactionStrategy | None = None,
        model: str | None = None,
        model_aliases: dict[str, str | Model] | None = None,
    ) -> None:
        self.state = state
        self.filter = filter
        self.retry_refusals = retry_refusals
        self.model = model
        self.model_aliases: dict[str, str | Model] = model_aliases or {}
        self._compaction = compaction
        self._compaction_prefix = state.messages.copy()
        self._compact: Compact | None = None
        self._message_ids = {}
        self._tool_call_ids = {}
        self._last_message_count = 0

    state: AgentState
    """State updated from messages traveling over the bridge."""

    filter: GenerateFilter | None
    """Filter for bridge model generation.

    A filter may substitute for the default model generation by returning a ModelOutput or return None to allow default processing to continue.
    """

    model: str | None
    """Fallback model for requests that don't use ``inspect`` or ``inspect/``
    prefixed names.  ``None`` means no fallback (the request model name is
    used as-is).
    """

    model_aliases: dict[str, str | Model]
    """Map of model name aliases.  When a request uses a name that appears
    here, the corresponding value (a ``Model`` instance or model spec string)
    is used instead.  Checked before the fallback ``model``.
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
        return self._id_for_message_signature(_message_signature(message), conversation)

    def _id_for_message_signature(
        self, signature: str, conversation: list[ChatMessage]
    ) -> str:
        # do we already have an id for this signature that isn't in the conversation?
        conversation_ids: Set[str] = {m.id for m in conversation if m.id is not None}
        message_ids = self._message_ids.get(signature, [])
        for id in message_ids:
            if id not in conversation_ids:
                return id

        # otherwise generate a new one and update our record
        message_id = uuid()
        message_ids.append(message_id)
        self._message_ids[signature] = message_ids
        return message_id

    def _register_output_message(self, message: ChatMessage) -> None:
        """Register output ids so they survive a harness round trip.

        After ``model.generate()`` returns, the bridge knows the canonical
        ``ChatMessage.id`` and ``ToolCall.id`` values that will end up in
        the transcript. Native protocols (Gemini in particular) drop or
        rewrite both on round trip, so when the harness echoes the message
        back as input next turn the bridge has to be able to map back to
        them. This records that mapping keyed on a content-only signature
        so the lookup works even when ids changed in flight.
        """
        if message.id is None:
            return
        signature = _message_signature(message)
        pool = self._message_ids.setdefault(signature, [])
        if message.id not in pool:
            pool.append(message.id)
        if isinstance(message, ChatMessageAssistant) and message.tool_calls:
            for index, tool_call in enumerate(message.tool_calls):
                if tool_call.id:
                    self._tool_call_ids[(signature, index)] = tool_call.id

    _message_ids: dict[str, list[str]]
    _tool_call_ids: dict[tuple[str, int], str]

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
        self._last_message_count = len(messages)


@lru_cache(maxsize=100)
def message_json_hash(message_json: str) -> str:
    return mm3_hash(message_json)


def _message_signature(message: ChatMessage) -> str:
    """Return a content-only hash of *message*.

    Normalized to be invariant under harness round trips:

    * id fields are stripped (the message's own ``id``, every ``ToolCall.id``
      inside an assistant message, and the ``tool_call_id`` link on a tool
      message)
    * string content is promoted to ``[ContentText(text=...)]`` so a message
      whose content the harness reformatted from a plain string to a single
      text block (Gemini does this) still hashes the same as the outbound
      version.
    """
    from inspect_ai._util.content import ContentText

    canonical = message.model_copy(deep=True)
    canonical.id = None
    if isinstance(canonical.content, str):
        canonical.content = [ContentText(text=canonical.content)]
    if isinstance(canonical, ChatMessageAssistant) and canonical.tool_calls:
        canonical.tool_calls = [
            ToolCall(
                id="",
                function=tc.function,
                arguments=tc.arguments,
                parse_error=tc.parse_error,
                view=tc.view,
                type=tc.type,
            )
            for tc in canonical.tool_calls
        ]
    if isinstance(canonical, ChatMessageTool):
        canonical.tool_call_id = None
    return message_json_hash(to_json_str_safe(canonical))
