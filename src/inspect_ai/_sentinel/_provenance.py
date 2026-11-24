"""Which tool results a person's `human()` decision covers (`ReviewedResult`), for the live dispatcher, the agent bridge and replay alike.

A tool result message carries the execution it came from (`ChatMessageTool.execution_id`). A decision covers an execution's result only where the host can tell that the call that ran is the call the person decided on, compared by `call_digest()`. Each driver hands the same facts to the classes here, so live and replay build the same records.
"""

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from pydantic_core import to_jsonable_python

from inspect_ai.event._tool import ToolEvent
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._message_ids import same_content
from inspect_ai.tool._tool_call import ToolCall

if TYPE_CHECKING:
    from inspect_sentinel import HumanDecision


def call_digest(call: ToolCall) -> str | None:
    """The digest of a call's id, function and arguments, as `SentinelEvent.call_digest` records it: `sha256:<hex>` over them as canonical JSON (sorted keys, no whitespace, ASCII).

    The arguments are taken as JSON carries them, so a call read back from a log has the digest it had live. None for arguments JSON can't carry (a numpy array, a non-string key): such a call is never found to be the call a person decided on.
    """
    try:
        encoded = json.dumps(
            [call.id, call.function, to_jsonable_python(call.arguments)],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
    except Exception:
        # any value can fail to serialize, in any way
        return None
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def tool_event_call(event: ToolEvent) -> ToolCall:
    """The call a `ToolEvent` ran: its id, function and the arguments it records."""
    return ToolCall(id=event.id, function=event.function, arguments=event.arguments)


@dataclass(frozen=True)
class ReviewedResult:
    """A tool result a person's `human()` decision covers, published to the later steps of the decision's conversation.

    The host publishes one only where the call that ran is the call the person decided on: for a decision before the call ran (`tool_call`, or the turn that proposed it at `model_output`), when the execution completes and its call has the decided call's digest; for a decision after it ran (`tool_result`), when the step settles. A later change to the call (a peer protocol's or an approver's modify, a scaffold's edit of the turn's call) means no record.

    A message in a step's lists is this result where `covers()` says so. Name the call from the message's producing turn, the assistant message holding its call id, and only where that call's `call_digest()` is `call_digest`; a message whose producing turn is not in the list is not marked.

    Experimental: not yet a stable API; may change without notice.
    """

    decision: "HumanDecision"
    """The person's decision, as `kept_human_decision()` kept it."""

    execution_id: str
    """The execution the decision covers (`ToolEvent.execution_id`, or an agent bridge's handout), which its result message carries (`ChatMessageTool.execution_id`)."""

    call_digest: str
    """The call the person decided on, which is the call that ran (`call_digest()`)."""

    result: ChatMessageTool
    """A detached copy of the result: as the execution produced it for a native call, and as the scaffold reported it in a request for a bridged call."""

    observed: bool
    """Whether the host ran the call: true for a native call and an agent bridge's host tool, false for a tool an agent bridge's scaffold ran itself (or reported a result for without running), whose execution the host never saw. A decision before such a call ran was made before it was handed to the agent."""


def result_execution(message: ChatMessage) -> str | None:
    """The execution a message is the result of (`ChatMessageTool.execution_id`), or None for any other message and where the host recorded none."""
    return message.execution_id if isinstance(message, ChatMessageTool) else None


def covers(record: ReviewedResult, message: ChatMessage) -> bool:
    """Whether `message` is the result `record` covers: it carries the record's execution, has its result's id, and the same content (`same_content`: content, call id and error)."""
    return (
        isinstance(message, ChatMessageTool)
        and message.execution_id is not None
        and message.execution_id == record.execution_id
        and message.id == record.result.id
        and same_content(message, record.result)
    )


class _HeldCall(NamedTuple):
    decision: "HumanDecision"
    digest: str


class _HeldTurn(NamedTuple):
    decision: "HumanDecision"
    calls: dict[str, str | None]
    """By call id, the digest of each call of the turn not yet run, None for an id the turn holds more than once or arguments JSON can't carry."""


class Reviews:
    """One conversation's reviewed results, and the decisions made before a call ran that wait for an execution of it to complete."""

    def __init__(self) -> None:
        # only appended to: a step holds a view cut when it is built
        self.published: list[ReviewedResult] = []
        # by execution id, `tool_call` decisions
        self._calls: dict[str, list[_HeldCall]] = {}
        # by the turn's output message id, `model_output` decisions
        self._turns: dict[str, list[_HeldTurn]] = {}

    def keep(
        self,
        decision: "HumanDecision",
        *,
        execution_id: str | None,
        digest: str | None,
        result: ChatMessageTool | None = None,
        turn: ChatMessageAssistant | None = None,
    ) -> None:
        """Keep a native step's published `human()` decision.

        Args:
            decision: The decision, once its step settled.
            execution_id: The execution a tool-stage step judged.
            digest: The call the step judged (`SentinelEvent.call_digest`).
            result: At `tool_result`, the step's result.
            turn: At `model_output`, the turn's output message.
        """
        if decision.stage == "tool_result":
            if execution_id is not None and digest is not None and result is not None:
                self.published.append(
                    ReviewedResult(
                        decision,
                        execution_id,
                        digest,
                        result.model_copy(deep=True),
                        observed=True,
                    )
                )
        elif decision.stage == "tool_call":
            if execution_id is not None and digest is not None:
                self._calls.setdefault(execution_id, []).append(
                    _HeldCall(decision, digest)
                )
        elif decision.stage == "model_output":
            if turn is not None and turn.id is not None and turn.tool_calls:
                calls: dict[str, str | None] = {}
                for call in turn.tool_calls:
                    calls[call.id] = None if call.id in calls else call_digest(call)
                self._turns.setdefault(turn.id, []).append(_HeldTurn(decision, calls))

    def complete(
        self,
        execution_id: str,
        call: ToolCall,
        message_id: str | None,
        result: ChatMessageTool,
    ) -> None:
        """Publish the records of a native execution that ran `call` (`tool_event_call`), from the turn `message_id`, and produced `result`, once its own `tool_result` step settled.

        A `tool_call` decision about the execution covers it where it judged the call that ran. A `model_output` decision about the turn covers the first execution of each of its calls, where the turn's call under the id is the call that ran.
        """
        if not self._calls and not self._turns:
            return
        calls = self._calls.pop(execution_id, [])
        turns: list[_HeldTurn] = (
            [turn for turn in self._turns.get(message_id, []) if call.id in turn.calls]
            if message_id is not None
            else []
        )
        if not calls and not turns:
            return
        ran = call_digest(call)
        covered = [held.decision for held in calls if held.digest == ran]
        for turn in turns:
            if turn.calls.pop(call.id) == ran:
                covered.append(turn.decision)
        if ran is None or not covered:
            return
        copy = result.model_copy(deep=True)
        for decision in covered:
            self.published.append(
                ReviewedResult(decision, execution_id, ran, copy, observed=True)
            )


class _HeldBridged(NamedTuple):
    decision: "HumanDecision"
    digest: str
    conversation: str


class BridgedReviews:
    """A sample's `human()` decisions at an agent bridge's checks, each waiting for a request to carry the result of the execution it judged; and the host's runs of bridged tools.

    A decision is published, with the conversation of the check that made it, after the checks of the first request whose input holds one message carrying its execution (`ChatMessageTool.execution_id`, which the bridge sets), as the result that message is. Where the host ran the execution's tool (`ran`), it is published only if the host ran the decided call; otherwise it is published as not observed.
    """

    def __init__(self) -> None:
        self._held: dict[str, list[_HeldBridged]] = {}
        # by execution id, the digests of the calls the host ran under it
        self._ran: dict[str, set[str | None]] = {}

    def hold(
        self,
        execution_id: str | None,
        decision: "HumanDecision",
        digest: str | None,
        conversation: str,
        modified: bool,
    ) -> None:
        """Hold a bridge check's published decision.

        Args:
            execution_id: The execution the check judged.
            decision: The decision, once the check settled.
            digest: The call the check judged (`SentinelEvent.call_digest`).
            conversation: The check's conversation.
            modified: Whether any instance reported a modify at the check. The scaffold may then have been handed another call than the one decided on, which the host can't compare for a tool the scaffold runs, so a `tool_call` decision is not held.
        """
        if decision.stage not in ("tool_call", "tool_result"):
            return
        if decision.stage == "tool_call" and modified:
            return
        if execution_id is not None and digest is not None:
            self._held.setdefault(execution_id, []).append(
                _HeldBridged(decision, digest, conversation)
            )

    def ran(self, event: ToolEvent) -> None:
        """Note a host tool's run of a bridged call, once its event is complete."""
        if event.execution_id is not None and host_ran(event):
            self._ran.setdefault(event.execution_id, set()).add(
                call_digest(tool_event_call(event))
            )

    def place(
        self, input: Iterable[ChatMessage], reviews: Callable[[str], Reviews]
    ) -> None:
        """Publish the decisions whose execution's result `input` holds once, to the conversations `reviews` gives."""
        if not self._held:
            return
        found: dict[str, list[ChatMessageTool]] = {}
        for message in input:
            if (
                isinstance(message, ChatMessageTool)
                and message.execution_id is not None
                and message.execution_id in self._held
            ):
                found.setdefault(message.execution_id, []).append(message)
        for execution_id, messages in found.items():
            if len(messages) != 1:
                continue
            ran = self._ran.get(execution_id)
            result = messages[0].model_copy(deep=True)
            for held in self._held.pop(execution_id):
                if ran is not None and ran != {held.digest}:
                    continue
                reviews(held.conversation).published.append(
                    ReviewedResult(
                        held.decision,
                        execution_id,
                        held.digest,
                        result,
                        observed=ran is not None,
                    )
                )


def host_ran(event: ToolEvent) -> bool:
    """Whether an agent bridge's host tool ran for a complete `ToolEvent`: not a request refused before the tool was called (`parsing`, `approval`, `permission`), and not one that failed the sample."""
    return (
        not event.pending
        and not event.failed
        and (
            event.error is None
            or event.error.type not in ("parsing", "approval", "permission")
        )
    )
