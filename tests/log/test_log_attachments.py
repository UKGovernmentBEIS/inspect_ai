import dataclasses
import os
from collections.abc import Callable

import pytest
from pydantic import BaseModel, ConfigDict

from inspect_ai._util.json import JsonChange
from inspect_ai.dataset._dataset import Sample
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.event._store import StoreEvent
from inspect_ai.event._subtask import SubtaskEvent
from inspect_ai.log._condense import (
    ATTACHMENT_PROTOCOL,
    attachment_refs_from_object,
    attachment_refs_from_value,
    condense_event,
    condense_sample,
    resolve_sample_attachments,
)
from inspect_ai.log._file import read_eval_log
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams


def _refs_via_dump(event: Event) -> set[str]:
    return attachment_refs_from_value(event.model_dump(mode="python"))


def _model_event_with_refs_everywhere() -> ModelEvent:
    return ModelEvent(
        model="m",
        input=[
            ChatMessageUser(content="attachment://in-msg"),
            ChatMessageAssistant(
                content="plain text",
                tool_calls=[
                    ToolCall(
                        id="tc1",
                        function="fn",
                        # ToolCall is a pydantic *dataclass*, not a BaseModel —
                        # a BaseModel-only walker would miss this ref
                        arguments={"arg": "attachment://tool-arg"},
                    )
                ],
            ),
        ],
        tools=[
            ToolInfo(
                name="t",
                description="attachment://tool-desc",
                parameters=ToolParams(),
            )
        ],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("m", "attachment://out-msg"),
        call=ModelCall.create(
            {"messages": [{"role": "user", "content": "attachment://call-req"}]},
            {"content": "attachment://call-resp"},
        ),
    )


def _extras_model_event() -> Event:
    # extra="allow" models store extras in __pydantic_extra__, outside
    # __dict__, and dumps include them (e.g. CheckpointEvent round-trips
    # checkpoint-file extras)
    class ExtraModel(BaseModel):
        model_config = ConfigDict(extra="allow")

        name: str

    event = InfoEvent(data="ok")
    event.metadata = {
        "extra": ExtraModel.model_validate(
            {"name": "n", "x_extra": "attachment://extra-ref"}
        )
    }
    return event


def _any_slot_live_message_event() -> Event:
    # SubtaskEvent.result is Any and receives raw (un-jsonable-ized) values
    event = SubtaskEvent(name="sub", input={})
    event.result = {"m": ChatMessageUser(content="attachment://sub-msg")}
    return event


def _slots_dataclass_event() -> Event:
    # @dataclass(slots=True) has no __dict__; vars() would raise TypeError.
    # Reachable via SubtaskEvent.result (raw return values) and metadata.
    @dataclasses.dataclass(slots=True)
    class SlottedResult:
        note: str

    event = SubtaskEvent(name="sub", input={})
    event.result = SlottedResult(note="attachment://slot-ref")
    return event


@pytest.mark.parametrize(
    ("event_factory", "expected_refs"),
    [
        (
            _model_event_with_refs_everywhere,
            {
                "in-msg",
                "tool-arg",
                "tool-desc",
                "out-msg",
                "call-req",
                "call-resp",
            },
        ),
        (
            lambda: InfoEvent(data={"k": "attachment://info-ref"}),
            {"info-ref"},
        ),
        (
            lambda: StoreEvent(
                changes=[
                    JsonChange(op="replace", path="/k", value="attachment://store-ref")
                ]
            ),
            {"store-ref"},
        ),
        (
            lambda: SampleInitEvent(
                sample=Sample(
                    input=[ChatMessageUser(content="attachment://sample-msg")]
                ),
                state={"s": "attachment://state-ref"},
            ),
            {"sample-msg", "state-ref"},
        ),
        (_extras_model_event, {"extra-ref"}),
        (_any_slot_live_message_event, {"sub-msg"}),
        (_slots_dataclass_event, {"slot-ref"}),
    ],
    ids=[
        "model-event-refs-everywhere",
        "info-event",
        "store-event",
        "sample-init-event",
        "extras-model",
        "any-slot-live-message",
        "slots-dataclass",
    ],
)
def test_attachment_refs_from_object_parity(
    event_factory: Callable[[], Event], expected_refs: set[str]
) -> None:
    event = event_factory()
    refs = attachment_refs_from_object(event)
    assert refs == expected_refs
    assert refs == _refs_via_dump(event)


def test_attachment_refs_from_object_terminates_on_cycle() -> None:
    # today attachment_refs_from_value(model_dump(...)) raises RecursionError
    # on a cyclic metadata value (pydantic embeds the original cyclic object
    # in the dump); the object scanner must terminate and collect the ref
    cyc: dict[str, object] = {"ref": "attachment://cyc-ref"}
    cyc["self"] = cyc
    event = InfoEvent(data="ok")
    event.metadata = {"cyc": cyc}
    assert attachment_refs_from_object(event) == {"cyc-ref"}


def test_attachment_refs_from_object_terminates_on_list_cycle() -> None:
    # a self-referencing list would loop forever (not RecursionError) if the
    # list branch lost its visited-set guard
    cyc: list[object] = ["attachment://list-cyc"]
    cyc.append(cyc)
    event = InfoEvent(data="ok")
    event.metadata = {"cyc": cyc}
    assert attachment_refs_from_object(event) == {"list-cyc"}


@dataclasses.dataclass
class _RefDataclass:
    ref: str


class _RefModel(BaseModel):
    ref: str


@pytest.mark.parametrize(
    "make_container",
    [
        lambda ref: {"ref": ref},
        lambda ref: [ref],
        lambda ref: _RefModel(ref=ref),
        lambda ref: _RefDataclass(ref=ref),
    ],
    ids=["dict", "list", "basemodel", "dataclass"],
)
def test_attachment_refs_from_object_shared_subtree(
    make_container: Callable[[str], object],
) -> None:
    shared = make_container("attachment://shared-ref")
    event = InfoEvent(data="ok")
    event.metadata = {"a": shared, "b": shared}
    assert attachment_refs_from_object(event) == {"shared-ref"}


def test_attachment_refs_from_object_dict_keys_not_scanned() -> None:
    # parity: attachment_refs_from_value scans dict values only
    event = InfoEvent(data="ok")
    event.metadata = {"attachment://key-ref": "plain"}
    assert attachment_refs_from_object(event) == set()
    assert attachment_refs_from_object(event) == _refs_via_dump(event)


def test_attachment_refs_from_object_plain_object_stays_opaque() -> None:
    """Arbitrary non-model objects are left opaque, exactly as the dump leaves them."""

    class PlainObject:
        def __init__(self) -> None:
            self.ref = "attachment://opaque-ref"

    event = InfoEvent(data="ok")
    event.metadata = {"o": PlainObject()}
    assert attachment_refs_from_object(event) == set()
    assert attachment_refs_from_object(event) == _refs_via_dump(event)


def test_log_attachments_condense():
    # read and resolve attachments
    log_file = log_path("log_images.json")
    log = read_eval_log(log_file)
    assert log.samples
    log.samples = [resolve_sample_attachments(sample, "full") for sample in log.samples]

    # confirm there are no attachment refs
    assert len(log.samples[0].attachments) == 0
    assert ATTACHMENT_PROTOCOL not in log.model_dump_json()

    # now condense and confirm we have attachment refs
    log.samples = [condense_sample(sample) for sample in log.samples]
    assert ATTACHMENT_PROTOCOL in log.model_dump_json()


def test_log_attachments_migration():
    # check for old-style content ref
    log_file = log_path("log_images_tc.json")
    assert "tc://" in log_str(log_file)

    # read log and confirm we have migrated into attachments
    log = read_eval_log(log_path("log_images_tc.json"))
    assert log.samples
    assert list(log.samples[0].attachments.values())[0].startswith(
        "data:image/png;base64"
    )

    # also confirm that we've preserved (now deprecated) transcript
    assert len(log.samples[0].transcript.events) > 0


# def test_transcript_incremental_condense():
#     """Test that Transcript condenses ModelEvents immediately when added."""
#     transcript = Transcript()

#     # Create a long text that should be condensed (> 100 chars)
#     long_text = "x" * 200
#     message = ChatMessageUser(content=long_text)

#     # Create a model event with long content
#     event = ModelEvent(
#         model="test-model",
#         input=[message],
#         tools=[],
#         tool_choice="auto",
#         config=GenerateConfig(),
#         output=ModelOutput.from_content("test-model", "response"),
#     )

#     # Add event to transcript
#     transcript._event(event)

#     # Verify the event was condensed immediately
#     stored_event = transcript.events[0]
#     assert isinstance(stored_event, ModelEvent)
#     assert stored_event.input[0].content.startswith(ATTACHMENT_PROTOCOL)
#     assert stored_event.input[0].content != long_text

#     # Verify attachment was created
#     assert len(transcript.attachments) == 1
#     attachment_hash = stored_event.input[0].content.replace(ATTACHMENT_PROTOCOL, "")
#     assert attachment_hash in transcript.attachments
#     assert transcript.attachments[attachment_hash] == long_text


# def test_transcript_event_updated_condenses():
#     """Test that _event_updated condenses the output and call fields."""
#     transcript = Transcript()

#     # Create initial event with placeholder output
#     initial_message = ChatMessageUser(content="short input")
#     event = ModelEvent(
#         model="test-model",
#         input=[initial_message],
#         tools=[],
#         tool_choice="auto",
#         config=GenerateConfig(),
#         output=ModelOutput.from_content("test-model", ""),
#         pending=True,
#     )

#     # Add event to transcript
#     transcript._event(event)

#     # Simulate what happens in _record_model_interaction's complete() callback:
#     # Mutate the event's output with long content
#     long_response = "y" * 200
#     event.output = ModelOutput.from_content("test-model", long_response)
#     event.pending = None

#     # Call _event_updated to condense the new output
#     transcript._event_updated(event)

#     # Verify the output was condensed
#     stored_event = transcript.events[0]
#     assert isinstance(stored_event, ModelEvent)
#     # The output's message content should be condensed
#     output_content = stored_event.output.choices[0].message.content
#     assert output_content.startswith(ATTACHMENT_PROTOCOL)
#     assert output_content != long_response

#     # Verify attachment was created for the output
#     attachment_hash = output_content.replace(ATTACHMENT_PROTOCOL, "")
#     assert attachment_hash in transcript.attachments
#     assert transcript.attachments[attachment_hash] == long_response


# def test_transcript_deduplication_across_events():
#     """Test that identical content is deduplicated across multiple events."""
#     transcript = Transcript()

#     # Create the same long text that will appear in multiple events
#     repeated_text = "repeated content " * 20  # > 100 chars
#     message1 = ChatMessageUser(content=repeated_text)
#     message2 = ChatMessageUser(content=repeated_text)

#     # Create two events with the same content
#     event1 = ModelEvent(
#         model="test-model",
#         input=[message1],
#         tools=[],
#         tool_choice="auto",
#         config=GenerateConfig(),
#         output=ModelOutput.from_content("test-model", "response1"),
#     )

#     event2 = ModelEvent(
#         model="test-model",
#         input=[message2],
#         tools=[],
#         tool_choice="auto",
#         config=GenerateConfig(),
#         output=ModelOutput.from_content("test-model", "response2"),
#     )

#     # Add both events
#     transcript._event(event1)
#     transcript._event(event2)

#     # Verify both events reference the same attachment
#     stored_event1 = transcript.events[0]
#     stored_event2 = transcript.events[1]

#     assert isinstance(stored_event1, ModelEvent)
#     assert isinstance(stored_event2, ModelEvent)

#     content1 = stored_event1.input[0].content
#     content2 = stored_event2.input[0].content

#     # Both should have attachment references
#     assert content1.startswith(ATTACHMENT_PROTOCOL)
#     assert content2.startswith(ATTACHMENT_PROTOCOL)

#     # Both should reference the SAME attachment hash
#     assert content1 == content2

#     # There should be only ONE attachment (deduplicated)
#     assert len(transcript.attachments) == 1
#     attachment_hash = content1.replace(ATTACHMENT_PROTOCOL, "")
#     assert transcript.attachments[attachment_hash] == repeated_text


def test_condense_event_preserves_sample_attachments():
    """Test that condense_sample correctly includes transcript attachments."""
    # Read a log with attachments
    log_file = log_path("log_images.json")
    log = read_eval_log(log_file)
    assert log.samples

    sample = log.samples[0]

    # Verify the sample already has attachments from the log
    initial_attachment_count = len(sample.attachments)
    assert initial_attachment_count > 0

    # Condense again (simulating what happens during eval)
    condensed = condense_sample(sample, log_images=True)

    # Verify attachments are preserved and possibly extended
    assert len(condensed.attachments) >= initial_attachment_count

    # Verify all original attachments are still present
    for key, value in sample.attachments.items():
        assert key in condensed.attachments
        assert condensed.attachments[key] == value


def test_condense_event_function() -> None:
    """Test the condense_event function directly."""
    attachments: dict[str, str] = {}
    long_text = "z" * 200

    # Create an event with long content
    message = ChatMessageUser(content=long_text)
    event = ModelEvent(
        model="test-model",
        input=[message],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", "response"),
    )

    # Condense the event
    condensed_event = condense_event(event, attachments, log_images=True)

    # Verify the condensed event has attachment reference
    assert isinstance(condensed_event, ModelEvent)
    condensed_content = condensed_event.input[0].content
    assert isinstance(condensed_content, str)
    assert condensed_content.startswith(ATTACHMENT_PROTOCOL)
    assert condensed_content != long_text

    # Verify attachment was added to the dict
    assert len(attachments) == 1
    attachment_hash = condensed_content.replace(ATTACHMENT_PROTOCOL, "")
    assert attachment_hash in attachments
    assert attachments[attachment_hash] == long_text


def log_path(log: str) -> str:
    return os.path.join("tests", "log", "test_eval_log", log)


def log_str(log: str) -> str:
    with open(log, "r") as f:
        return f.read()
