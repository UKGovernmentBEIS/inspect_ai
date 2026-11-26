import dataclasses
import gc
import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import anyio
import pytest
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_serializer

from inspect_ai import Task, eval_retry, task
from inspect_ai import eval as inspect_eval
from inspect_ai._eval.score import score
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._eval.task.run import _seed_error_retries
from inspect_ai._util.constants import BASE_64_DATA_REMOVED
from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.json import JsonChange
from inspect_ai.dataset._dataset import Sample
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._pool import materialize_pooled_events
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.event._store import StoreEvent
from inspect_ai.event._subtask import SubtaskEvent
from inspect_ai.event._timeline import Timeline, TimelineEvent, TimelineSpan
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log import EvalRetryError, EvalSample
from inspect_ai.log import _condense as condense_module
from inspect_ai.log._condense import (
    ATTACHMENT_PROTOCOL,
    attachment_refs_from_object,
    attachment_refs_from_value,
    condense_event,
    condense_sample,
    condensed_sample_summary,
    mark_attachments_resolved,
    resolve_event_calls,
    resolve_events_attachments,
    resolve_sample_attachments,
)
from inspect_ai.log._convert import convert_eval_logs
from inspect_ai.log._file import (
    read_eval_log,
    read_eval_log_sample_summaries,
    write_eval_log,
)
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalSampleSummary,
    EvalSpec,
)
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.types import Samples
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._recover._reconstruct import reconstruct_events
from inspect_ai.log._resolve import resolve_sample_events_data
from inspect_ai.log._samples import set_active_model_event_call
from inspect_ai.log._transcript import (
    Transcript,
    _transcript,
    init_transcript,
    transcript,
)
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import ModelAPI, get_model
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput
from inspect_ai.model._registry import modelapi
from inspect_ai.scorer import Score, Scorer, Target, match, mean, scorer
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, use_tools
from inspect_ai.tool import Tool, tool
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams


def _refs_via_dump(event: Event) -> set[str]:
    """Independent oracle: collect refs by recursing over the event's dump.

    Deliberately not ``attachment_refs_from_value`` — that delegates to
    ``attachment_refs_from_object``, so the parity assertions would compare
    the object walker against itself. Kept naive on purpose (tuple/set are
    defensive: ``mode="python"`` output is not strictly JSON).
    """
    refs: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, str):
            if value.startswith(ATTACHMENT_PROTOCOL):
                refs.add(value.removeprefix(ATTACHMENT_PROTOCOL))
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                collect(item)

    collect(event.model_dump(mode="python"))
    return refs


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
    # the recursive scan this walker replaced raised RecursionError on a
    # cyclic metadata value (pydantic embeds the original cyclic object in
    # the dump); the object scanner must terminate and collect the ref
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


def _model_event_outputs(log: EvalLog) -> list[ModelOutput]:
    assert log.samples
    outputs = [
        event.output
        for sample in log.samples
        for event in sample.events
        if isinstance(event, ModelEvent)
    ]
    assert outputs
    return outputs


@pytest.mark.parametrize(
    "log_name",
    [
        "2024-11-05T13-32-37-05-00_input-task_hxs4q9azL3ySGkjJirypKZ.eval",
        "2024-11-05T13-31-45-05-00_input-task_8zXjbRzCWrL9GXiXo2vus9.json",
    ],
)
@pytest.mark.parametrize("resolve_attachments", [True, "core"])
def test_resolve_completion_derived_from_condensed_text(
    log_name: str, resolve_attachments: bool | Literal["core"], tmp_path: Path
) -> None:
    # These logs predate stored completions (0.3.123), so the validator
    # derives each completion from the condensed message text.
    log_file = os.path.join("tests", "log", "test_list_logs", log_name)
    for output in _model_event_outputs(read_eval_log(log_file)):
        assert output.completion.startswith(ATTACHMENT_PROTOCOL)

    log = read_eval_log(log_file, resolve_attachments=resolve_attachments)
    completions = [output.completion for output in _model_event_outputs(log)]
    for output in _model_event_outputs(log):
        assert not output.completion.startswith(ATTACHMENT_PROTOCOL)
        assert output.completion == output.message.text

    # rewriting the log stores the text, not the reference
    rewritten = tmp_path / f"rewritten{Path(log_name).suffix}"
    write_eval_log(log, rewritten)
    reread = read_eval_log(rewritten)
    assert [o.completion for o in _model_event_outputs(reread)] == completions


@pytest.mark.parametrize("resolve_attachments", [True, "core"])
def test_resolve_keeps_stored_completion_with_literal_ref(
    resolve_attachments: bool | Literal["core"],
) -> None:
    reply = "model reply " + ("x" * 200)
    prompt = "system prompt " + ("y" * 200)
    reply_hash, prompt_hash = mm3_hash(reply), mm3_hash(prompt)
    literal = f"{ATTACHMENT_PROTOCOL}{prompt_hash}"
    event = ModelEvent(
        model="test-model",
        input=[ChatMessageUser(content="hello")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(
            model="test-model",
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=f"{ATTACHMENT_PROTOCOL}{reply_hash}"
                    )
                )
            ],
            completion=literal,
        ),
    )
    sample = EvalSample(
        id="sample",
        epoch=1,
        input="input",
        target="target",
        events=[event],
        attachments={reply_hash: reply, prompt_hash: prompt},
    )

    resolved = resolve_sample_attachments(sample, resolve_attachments)

    [resolved_event] = resolved.events
    assert isinstance(resolved_event, ModelEvent)
    assert resolved_event.output.message.text == reply
    assert resolved_event.output.completion == literal


def test_condense_leaves_completion_inline() -> None:
    reply = "model reply " + ("x" * 200)
    sample = EvalSample(
        id="sample",
        epoch=1,
        input="input",
        target="target",
        events=[
            ModelEvent(
                model="test-model",
                input=[ChatMessageUser(content="hello")],
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput.from_content("test-model", reply),
            )
        ],
    )

    [event] = condense_sample(sample).events

    assert isinstance(event, ModelEvent)
    assert event.output.message.text.startswith(ATTACHMENT_PROTOCOL)
    assert event.output.completion == reply


def test_retry_event_attachments_round_trip() -> None:
    image_data_uri = "data:image/png;base64," + ("A" * 120)
    event = ModelEvent(
        model="test-model",
        input=[
            ChatMessageUser(content=[ContentImage(image=image_data_uri)]),
        ],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", "response"),
    )
    sample = EvalSample(
        id="sample",
        epoch=1,
        input="input",
        target="target",
        error_retries=[
            EvalRetryError(
                message="retry",
                traceback="",
                traceback_ansi="",
                events=[event],
            )
        ],
    )

    condensed = condense_sample(sample, log_images=True)
    assert condensed.error_retries is not None
    condensed_events = condensed.error_retries[0].events
    assert condensed_events is not None
    condensed_event = condensed_events[0]
    assert isinstance(condensed_event, ModelEvent)
    condensed_content = condensed_event.input[0].content
    assert isinstance(condensed_content, list)
    condensed_image = condensed_content[0]
    assert isinstance(condensed_image, ContentImage)
    assert condensed_image.image.startswith(ATTACHMENT_PROTOCOL)

    resolved = resolve_sample_attachments(condensed, "full")
    assert resolved.error_retries is not None
    resolved_events = resolved.error_retries[0].events
    assert resolved_events is not None
    resolved_event = resolved_events[0]
    assert isinstance(resolved_event, ModelEvent)
    resolved_content = resolved_event.input[0].content
    assert isinstance(resolved_content, list)
    resolved_image = resolved_content[0]
    assert isinstance(resolved_image, ContentImage)
    assert resolved_image.image == image_data_uri


def test_recondense_without_images_removes_existing_media_attachments() -> None:
    image_data_uri = "data:image/png;base64," + ("A" * 120)
    message = ChatMessageUser(content=[ContentImage(image=image_data_uri)])
    event = ModelEvent(
        model="test-model",
        input=[message],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", "response"),
    )
    sample = EvalSample(
        id="sample",
        epoch=1,
        input=[message],
        target="target",
        messages=[message],
        events=[event],
        error_retries=[
            EvalRetryError(
                message="retry",
                traceback="",
                traceback_ansi="",
                events=[event],
            )
        ],
    )

    with_images = condense_sample(sample, log_images=True)
    assert image_data_uri in with_images.attachments.values()

    without_images = condense_sample(with_images, log_images=False)
    serialized = without_images.model_dump_json()
    assert image_data_uri not in serialized
    assert image_data_uri not in without_images.attachments.values()
    assert BASE_64_DATA_REMOVED in serialized


def test_recondense_preserves_attachment_shared_by_messages_and_events() -> None:
    long_text = "shared attachment content " * 8
    attachment_hash = mm3_hash(long_text)
    attachment_ref = f"{ATTACHMENT_PROTOCOL}{attachment_hash}"
    message = ChatMessageUser(content=attachment_ref)
    event = ModelEvent(
        model="test-model",
        input=[message],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", "response"),
    )
    sample = EvalSample(
        id="sample",
        epoch=1,
        input="input",
        target="target",
        messages=[message],
        events=[event],
        attachments={attachment_hash: long_text},
    )

    condensed = condense_sample(sample)
    referenced = attachment_refs_from_value(
        condensed.model_dump(mode="python", exclude={"attachments"})
    )

    assert condensed.messages[0].content == long_text
    assert attachment_hash in referenced
    assert referenced <= set(condensed.attachments)

    resolved = resolve_sample_attachments(condensed, "full")
    assert resolved.events is not None
    resolved_event = next(
        event for event in resolved.events if isinstance(event, ModelEvent)
    )
    assert resolved_event.input[0].content == long_text


def test_recondense_preserves_unreferenced_existing_attachment() -> None:
    orphan_hash = mm3_hash("legacy attachment")
    sample = EvalSample(
        id="sample",
        epoch=1,
        input="input",
        target="target",
        attachments={orphan_hash: "legacy attachment"},
    )

    condensed = condense_sample(sample)

    assert condensed.attachments == {orphan_hash: "legacy attachment"}


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


_TOOL_RESULT_IMAGE = "data:image/png;base64," + ("B" * 120)
_TOOL_RESULT_TEXT = "tool text"


def _sample_with_tool_result(result: ToolResult) -> EvalSample:
    """A sample whose only tool call returned ``result``.

    The tool message and the tool event carry the same result, as they do
    in a recorded eval, so a test can check that both copies follow the
    image logging policy.
    """
    content: str | list[Content]
    if isinstance(result, list):
        content = list(result)
    elif isinstance(result, str | int | float | bool):
        content = str(result)
    else:
        content = [result]
    tool_message = ChatMessageTool(content=content, tool_call_id="call", function="fn")
    event = ToolEvent(
        id="call",
        function="fn",
        arguments={},
        result=result,
        timestamp=datetime.now(timezone.utc),
        message_id=tool_message.id,
    )
    return EvalSample(
        id="sample",
        epoch=1,
        input="input",
        target="target",
        messages=[ChatMessageUser(content="hello"), tool_message],
        events=[event],
    )


def _tool_event(sample: EvalSample) -> ToolEvent:
    tool_events = [event for event in sample.events if isinstance(event, ToolEvent)]
    assert len(tool_events) == 1
    return tool_events[0]


def _tool_message_image(sample: EvalSample) -> str:
    message = sample.messages[1]
    assert isinstance(message, ChatMessageTool)
    assert isinstance(message.content, list)
    image = message.content[1]
    assert isinstance(image, ContentImage)
    return image.image


def test_tool_event_result_image_becomes_attachment() -> None:
    sample = _sample_with_tool_result(
        [ContentText(text=_TOOL_RESULT_TEXT), ContentImage(image=_TOOL_RESULT_IMAGE)]
    )

    condensed = condense_sample(sample, log_images=True)
    result = _tool_event(condensed).result
    assert isinstance(result, list)
    text, image = result
    assert isinstance(text, ContentText)
    assert text.text == _TOOL_RESULT_TEXT
    assert isinstance(image, ContentImage)
    assert image.image.startswith(ATTACHMENT_PROTOCOL)
    # the event and the tool message share one attachment
    assert image.image == _tool_message_image(condensed)
    assert condensed.attachments[image.image.removeprefix(ATTACHMENT_PROTOCOL)] == (
        _TOOL_RESULT_IMAGE
    )

    resolved = resolve_sample_attachments(condensed, "full")
    result = _tool_event(resolved).result
    assert isinstance(result, list)
    text, image = result
    assert isinstance(text, ContentText)
    assert text.text == _TOOL_RESULT_TEXT
    assert isinstance(image, ContentImage)
    assert image.image == _TOOL_RESULT_IMAGE
    assert _tool_message_image(resolved) == _TOOL_RESULT_IMAGE


def test_tool_event_result_image_removed_without_log_images() -> None:
    sample = _sample_with_tool_result(
        [ContentText(text=_TOOL_RESULT_TEXT), ContentImage(image=_TOOL_RESULT_IMAGE)]
    )

    condensed = condense_sample(sample, log_images=False)
    result = _tool_event(condensed).result
    assert isinstance(result, list)
    text, image = result
    assert isinstance(text, ContentText)
    assert text.text == _TOOL_RESULT_TEXT
    assert isinstance(image, ContentImage)
    assert image.image == BASE_64_DATA_REMOVED
    assert _tool_message_image(condensed) == BASE_64_DATA_REMOVED
    assert _TOOL_RESULT_IMAGE not in condensed.attachments.values()


@pytest.mark.parametrize("log_images", [True, False])
def test_tool_event_single_content_result_follows_log_images(
    log_images: bool,
) -> None:
    sample = _sample_with_tool_result(ContentImage(image=_TOOL_RESULT_IMAGE))

    condensed = condense_sample(sample, log_images=log_images)
    image = _tool_event(condensed).result
    assert isinstance(image, ContentImage)
    if log_images:
        assert image.image.startswith(ATTACHMENT_PROTOCOL)
        resolved = _tool_event(resolve_sample_attachments(condensed, "full")).result
        assert isinstance(resolved, ContentImage)
        assert resolved.image == _TOOL_RESULT_IMAGE
    else:
        assert image.image == BASE_64_DATA_REMOVED


@pytest.mark.parametrize("log_images", [True, False])
def test_tool_event_long_text_result_stays_inline(log_images: bool) -> None:
    long_text = "tool output " * 20
    assert len(long_text) > 100
    sample = _sample_with_tool_result(long_text)

    condensed = condense_sample(sample, log_images=log_images)
    assert _tool_event(condensed).result == long_text
    assert long_text not in condensed.attachments.values()


def _eval_log(sample: EvalSample) -> EvalLog:
    return EvalLog(
        eval=EvalSpec(
            created=datetime.now(timezone.utc).isoformat(),
            task="test_task",
            model="mockllm/model",
            dataset=EvalDataset(name="test", samples=1),
            config=EvalConfig(),
        ),
        samples=[sample],
    )


def test_tool_event_result_image_round_trips_through_eval_log(tmp_path: str) -> None:
    sample = _sample_with_tool_result(
        [ContentText(text=_TOOL_RESULT_TEXT), ContentImage(image=_TOOL_RESULT_IMAGE)]
    )
    log_file = os.path.join(tmp_path, "tool_result.eval")
    write_eval_log(_eval_log(sample), log_file)

    # the persisted form holds the image once, as an attachment
    stored = read_eval_log(log_file, resolve_attachments=False)
    assert stored.samples
    result = _tool_event(stored.samples[0]).result
    assert isinstance(result, list)
    image = result[1]
    assert isinstance(image, ContentImage)
    assert image.image.startswith(ATTACHMENT_PROTOCOL)
    assert image.image == _tool_message_image(stored.samples[0])
    assert list(stored.samples[0].attachments.values()) == [_TOOL_RESULT_IMAGE]

    # and reading with attachments resolved restores it byte-identically
    resolved = read_eval_log(log_file, resolve_attachments="full")
    assert resolved.samples
    result = _tool_event(resolved.samples[0]).result
    assert isinstance(result, list)
    text, image = result
    assert isinstance(text, ContentText)
    assert text.text == _TOOL_RESULT_TEXT
    assert isinstance(image, ContentImage)
    assert image.image == _TOOL_RESULT_IMAGE


# a 1x1 GIF: a valid data URI shorter than the event text-pooling threshold
_MEDIA_KINDS = ["image", "audio", "video", "document"]


def _media(kind: str, source: str) -> Content:
    if kind == "image":
        return ContentImage(image=source)
    elif kind == "audio":
        return ContentAudio(audio=source, format="mp3")
    elif kind == "video":
        return ContentVideo(video=source, format="mp4")
    else:
        return ContentDocument(document=source, filename="report.pdf")


def _media_source(content: object) -> str:
    if isinstance(content, ContentImage):
        return content.image
    elif isinstance(content, ContentAudio):
        return content.audio
    elif isinstance(content, ContentVideo):
        return content.video
    assert isinstance(content, ContentDocument)
    return content.document


_SHORT_IMAGE = (
    "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)
_URL_IMAGE = "https://example.org/" + ("x" * 120) + ".png"


def _media_result(kind: str, source: str, as_list: bool) -> ToolResult:
    media = _media(kind, source)
    assert isinstance(
        media, ContentImage | ContentAudio | ContentVideo | ContentDocument
    )
    return [ContentText(text=_TOOL_RESULT_TEXT), media] if as_list else media


def _result_media(result: ToolResult) -> str:
    return _media_source(result[-1] if isinstance(result, list) else result)


@pytest.mark.parametrize("log_images", [True, False])
@pytest.mark.parametrize("as_list", [True, False])
@pytest.mark.parametrize("kind", _MEDIA_KINDS)
def test_tool_event_short_data_uri_result_follows_message_policy(
    kind: str, log_images: bool, as_list: bool
) -> None:
    # message media policy: every data URI is pooled or removed, whatever its
    # length; the event text policy would leave this one inline
    assert len(_SHORT_IMAGE) <= 100
    sample = _sample_with_tool_result(_media_result(kind, _SHORT_IMAGE, as_list))

    condensed = condense_sample(sample, log_images=log_images)
    source = _result_media(_tool_event(condensed).result)
    message = condensed.messages[1]
    assert isinstance(message, ChatMessageTool)
    assert isinstance(message.content, list)
    assert source == _media_source(message.content[-1])
    if log_images:
        assert source.startswith(ATTACHMENT_PROTOCOL)
        resolved = resolve_sample_attachments(condensed, "full")
        assert _result_media(_tool_event(resolved).result) == _SHORT_IMAGE
    else:
        assert source == BASE_64_DATA_REMOVED


@pytest.mark.parametrize("log_images", [True, False])
@pytest.mark.parametrize("as_list", [True, False])
@pytest.mark.parametrize("kind", _MEDIA_KINDS)
def test_tool_event_url_result_stays_inline(
    kind: str, log_images: bool, as_list: bool
) -> None:
    # message media policy: a URL is not a data URI, so it stays inline
    # whatever its length; the event text policy would pool it
    assert len(_URL_IMAGE) > 100
    sample = _sample_with_tool_result(_media_result(kind, _URL_IMAGE, as_list))

    condensed = condense_sample(sample, log_images=log_images)
    assert _result_media(_tool_event(condensed).result) == _URL_IMAGE
    assert _URL_IMAGE not in condensed.attachments.values()


def test_condense_event_tool_result_follows_message_policy() -> None:
    # condense_event (transcript store, log recovery) pools the event's text
    # under the event policy and its result media under the message policy
    attachments: dict[str, str] = {}
    long_argument = "z" * 200
    event = ToolEvent(
        id="call",
        function="fn",
        arguments={"path": long_argument},
        result=[ContentText(text=_TOOL_RESULT_TEXT), ContentImage(image=_SHORT_IMAGE)],
        timestamp=datetime.now(timezone.utc),
    )

    condensed = condense_event(event, attachments, log_images=True)
    assert isinstance(condensed, ToolEvent)
    argument = condensed.arguments["path"]
    assert isinstance(argument, str)
    assert argument.startswith(ATTACHMENT_PROTOCOL)
    image = _result_media(condensed.result)
    assert image.startswith(ATTACHMENT_PROTOCOL)
    assert attachments[image.removeprefix(ATTACHMENT_PROTOCOL)] == _SHORT_IMAGE
    assert set(attachments.values()) == {long_argument, _SHORT_IMAGE}

    removed = condense_event(event, {}, log_images=False)
    assert isinstance(removed, ToolEvent)
    assert _result_media(removed.result) == BASE_64_DATA_REMOVED


@pytest.mark.parametrize("container", ["tool", "subtask"])
def test_nested_tool_event_result_stays_inline_through_eval_log(
    container: str, tmp_path: str
) -> None:
    # deprecated nested events reload as dicts that the attachment walk skips,
    # so a nested result image must stay inline or it could not be resolved
    nested = ToolEvent(
        id="nested",
        function="nested_fn",
        arguments={},
        result=[
            ContentText(text=_TOOL_RESULT_TEXT),
            ContentImage(image=_TOOL_RESULT_IMAGE),
        ],
        timestamp=datetime.now(timezone.utc),
    )
    parent: Event
    if container == "tool":
        parent = ToolEvent(
            id="parent",
            function="fn",
            arguments={},
            events=[nested],
            timestamp=datetime.now(timezone.utc),
        )
    else:
        parent = SubtaskEvent(
            name="sub", input={}, events=[nested], timestamp=datetime.now(timezone.utc)
        )
    sample = EvalSample(
        id="sample",
        epoch=1,
        input="input",
        target="target",
        messages=[ChatMessageUser(content="hello")],
        events=[parent],
    )

    condensed = condense_sample(sample, log_images=True)
    parent_condensed = condensed.events[0]
    assert isinstance(parent_condensed, ToolEvent | SubtaskEvent)
    nested_condensed = parent_condensed.events[0]
    assert isinstance(nested_condensed, ToolEvent)
    assert _result_media(nested_condensed.result) == _TOOL_RESULT_IMAGE
    assert _TOOL_RESULT_IMAGE not in condensed.attachments.values()

    log_file = os.path.join(tmp_path, "nested.eval")
    write_eval_log(_eval_log(sample), log_file)
    resolved = read_eval_log(log_file, resolve_attachments="full")
    assert resolved.samples
    parent_read = resolved.samples[0].events[0]
    assert isinstance(parent_read, ToolEvent | SubtaskEvent)
    nested_read = parent_read.events[0]
    assert isinstance(nested_read, dict)
    assert nested_read["result"][1]["image"] == _TOOL_RESULT_IMAGE
    assert resolved.samples[0].attachments == {}
    assert ATTACHMENT_PROTOCOL not in resolved.model_dump_json()


def _sample_with_model_call_payload(payload: str) -> EvalSample:
    event = ModelEvent(
        model="test-model",
        input=[ChatMessageUser(content="hello")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", "response"),
        call=ModelCall(request={"system": payload}, response={"ok": True}),
    )
    return EvalSample(
        id="sample",
        epoch=1,
        input="input",
        target="target",
        messages=[ChatMessageUser(content="hello")],
        events=[event],
    )


def test_resolve_core_retains_attachments_still_referenced_by_model_call() -> None:
    payload = "model-call-payload-" + ("q" * 200)
    condensed = condense_sample(_sample_with_model_call_payload(payload))
    assert payload in condensed.attachments.values()

    resolved = resolve_sample_attachments(condensed, "core")

    # "core" leaves ModelEvent.call condensed, so its refs survive. Every
    # surviving ref must still resolve against the retained attachments.
    refs = attachment_refs_from_value(
        resolved.model_dump(mode="python", exclude={"attachments"})
    )
    assert refs
    assert refs <= set(resolved.attachments)
    assert payload in resolved.attachments.values()


def test_resolve_full_clears_attachments() -> None:
    payload = "model-call-payload-" + ("q" * 200)
    condensed = condense_sample(_sample_with_model_call_payload(payload))

    resolved = resolve_sample_attachments(condensed, "full")

    # "full" resolves every reference inline, so nothing points at the map.
    assert len(resolved.attachments) == 0
    assert ATTACHMENT_PROTOCOL not in resolved.model_dump_json()


def test_resolve_core_ignores_refs_held_by_timeline_events() -> None:
    call_payload = "model-call-payload-" + ("q" * 200)
    output_text = "model-output-" + ("o" * 200)
    sample = _sample_with_model_call_payload(call_payload)
    event = sample.events[0]
    assert isinstance(event, ModelEvent)
    event.output = ModelOutput.from_content("test-model", output_text)
    condensed = condense_sample(sample)
    assert output_text in condensed.attachments.values()
    # timelines are rebound only after resolution, so while resolving they
    # still hold the condensed events (whose output is an attachment ref)
    condensed.timelines = [
        Timeline(
            name="t",
            description="",
            root=TimelineSpan(
                id="root",
                name="root",
                span_type="agent",
                content=[TimelineEvent(event=e) for e in condensed.events],
            ),
        )
    ]

    resolved = resolve_sample_attachments(condensed, "core")

    assert list(resolved.attachments.values()) == [call_payload]


def test_resolve_full_expanded_shared_call_messages() -> None:
    long_text = "shared-call-message-" + ("m" * 200)
    shared: dict[str, JsonValue] = {"role": "user", "content": long_text}
    reply: dict[str, JsonValue] = {"role": "assistant", "content": "hi"}
    requests: list[list[JsonValue]] = [[shared], [shared, reply]]
    events: list[Event] = [
        ModelEvent(
            model="test-model",
            input=[],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(),
            call=ModelCall(request={"messages": msgs}, response={"ok": True}),
        )
        for msgs in requests
    ]
    sample = EvalSample(
        id="sample", epoch=1, input="input", target="target", events=events
    )
    # pool refs expanded before resolving, as recorder read_log does
    expanded = resolve_sample_events_data(condense_sample(sample))

    resolved = resolve_sample_attachments(expanded, "full")

    msgs = [
        e.call.request["messages"]
        for e in resolved.events
        if isinstance(e, ModelEvent) and e.call
    ]
    assert msgs == requests
    assert ATTACHMENT_PROTOCOL not in resolved.model_dump_json()


class _SerializesToRef(BaseModel):
    key: str

    @field_serializer("key")
    def _ref(self, key: str) -> str:
        return f"{ATTACHMENT_PROTOCOL}{key}"


class _ExcludedRef(BaseModel):
    ref: str = Field(exclude=True)


def _sample_with_live_metadata(
    sample_metadata: object, message_metadata: object
) -> EvalSample:
    sample = _sample_with_model_call_payload("payload")
    event = sample.events[0]
    assert isinstance(event, ModelEvent)
    event.input = [
        ChatMessageUser(content="hello", metadata={"live": message_metadata})
    ]
    sample.metadata = {"live": sample_metadata}
    sample.attachments = {"payload": "content"}
    return sample


@pytest.mark.parametrize("where", ["sample", "message"])
def test_resolve_core_retains_attachments_referenced_by_serializers(
    where: str,
) -> None:
    live = _SerializesToRef(key="payload")
    sample = _sample_with_live_metadata(
        live if where == "sample" else None, live if where == "message" else None
    )

    resolved = resolve_sample_attachments(sample, "core")

    assert f"{ATTACHMENT_PROTOCOL}payload" in resolved.model_dump_json()
    assert resolved.attachments == {"payload": "content"}


@pytest.mark.parametrize("where", ["sample", "message"])
def test_resolve_core_ignores_refs_in_excluded_fields(where: str) -> None:
    live = _ExcludedRef(ref=f"{ATTACHMENT_PROTOCOL}payload")
    sample = _sample_with_live_metadata(
        live if where == "sample" else None, live if where == "message" else None
    )

    resolved = resolve_sample_attachments(sample, "core")

    assert resolved.attachments == {}


class _RedactingUser(ChatMessageUser):
    @field_serializer("metadata")
    def _redact(self, metadata: object) -> None:
        return None


def test_resolve_core_scans_messages_as_declared_type() -> None:
    # logs serialize messages through the declared ChatMessage type, which
    # ignores a subclass's own serializers
    sample = _sample_with_model_call_payload("payload")
    event = sample.events[0]
    assert isinstance(event, ModelEvent)
    event.input = [
        _RedactingUser(
            content="hello", metadata={"ref": f"{ATTACHMENT_PROTOCOL}payload"}
        )
    ]
    sample.attachments = {"payload": "content"}

    resolved = resolve_sample_attachments(sample, "core")

    assert resolved.attachments == {"payload": "content"}


def _count_strings(value: object) -> int:
    if isinstance(value, str):
        return 1
    if isinstance(value, dict):
        return sum(_count_strings(v) for v in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return sum(_count_strings(v) for v in value)
    return 0


def _strings_scanned_resolving(turns: int, monkeypatch: pytest.MonkeyPatch) -> int:
    payload = "model-call-payload-" + ("q" * 200)
    messages: list[ChatMessage] = [
        ChatMessageUser(content=f"message {i}") for i in range(turns)
    ]
    call_messages: list[JsonValue] = [
        {"role": "user", "content": f"message {i}"} for i in range(turns)
    ]
    events: list[Event] = [
        ModelEvent(
            model="test-model",
            input=messages[: i + 1],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput.from_content("test-model", "response"),
            call=ModelCall(
                request={"system": payload, "messages": call_messages[: i + 1]},
                response={"ok": True},
            ),
        )
        for i in range(turns)
    ]
    sample = EvalSample(
        id="sample", epoch=1, input="input", target="target", events=events
    )
    condensed = condense_sample(sample)

    scanned = 0
    scan = condense_module.attachment_refs_from_value

    def counting_scan(value: JsonValue) -> set[str]:
        nonlocal scanned
        scanned += _count_strings(value)
        return scan(value)

    monkeypatch.setattr(condense_module, "attachment_refs_from_value", counting_scan)
    resolved = resolve_sample_attachments(condensed, "core")
    monkeypatch.undo()
    assert resolved.attachments == {mm3_hash(payload): payload}
    return scanned


def test_resolve_core_scan_is_linear_in_conversation_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # each event's input and call messages extend a shared conversation, so
    # scanning them per event would grow quadratically with its length
    short = _strings_scanned_resolving(50, monkeypatch)
    long = _strings_scanned_resolving(100, monkeypatch)
    assert long < 2.5 * short


def log_path(log: str) -> str:
    return os.path.join("tests", "log", "test_eval_log", log)


def log_str(log: str) -> str:
    with open(log, "r") as f:
        return f.read()


# -- literal strings that look like attachment references --

_LITERAL_SYSTEM_PROMPT = "You are a careful assistant who answers in full. " * 4
_LITERAL_KEY = mm3_hash(_LITERAL_SYSTEM_PROMPT)


@tool
def _ref_echo(value: str) -> Tool:
    async def execute() -> str:
        """Return a fixed string."""
        return value

    return execute


def _run_literal_eval(
    log_dir: str,
    log_format: Literal["eval", "json"],
    literal: str,
    after: list[Solver] | None = None,
) -> str:
    """Run a sample whose model reply and tool result are `literal`; return the log path.

    `after` runs after the reply.
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call("mockllm/model", "_ref_echo", {}),
            ModelOutput.from_content("mockllm/model", literal),
        ],
    )
    task = Task(
        dataset=[
            Sample(
                input=[
                    ChatMessageSystem(content=_LITERAL_SYSTEM_PROMPT),
                    ChatMessageUser(content="hello"),
                ]
            )
        ],
        solver=[use_tools(_ref_echo(literal)), generate(), *(after or [])],
        scorer=match(),
    )
    [log] = inspect_eval(
        task, model=model, log_dir=log_dir, log_format=log_format, display="none"
    )
    assert log.status == "success"
    assert log.location
    return log.location


def _assert_literals_read_back(
    sample: EvalSample, literal: str, calls: bool = True
) -> None:
    """The literal reads back as written everywhere; genuine refs still resolve.

    With `calls`, the model call payloads are checked too (the sample must be
    fully resolved).
    """
    assert sample.messages[0].text == _LITERAL_SYSTEM_PROMPT
    tool_message = sample.messages[-2]
    assert isinstance(tool_message, ChatMessageTool)
    assert tool_message.text == literal
    assert sample.messages[-1].text == literal
    assert sample.output.completion == literal

    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len(model_events) == 2
    last = model_events[-1]
    assert last.output.completion == literal
    assert last.output.message.text == literal
    # the long system prompt was pooled as a genuine reference
    assert last.input[0].text == _LITERAL_SYSTEM_PROMPT
    assert last.input[-1].text == literal

    [tool_event] = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert tool_event.result == literal

    if calls:
        assert last.call is not None
        request_messages = last.call.request["messages"]
        assert isinstance(request_messages, list)
        contents = [
            message["content"]
            for message in request_messages
            if isinstance(message, dict)
        ]
        # the pooled system prompt, and the tool result the model was sent
        assert contents[0] == _LITERAL_SYSTEM_PROMPT
        assert contents[-1] == literal
        assert last.call.response == {"content": literal}


@pytest.mark.parametrize("log_format", ["eval", "json"])
@pytest.mark.parametrize("protocol", ["attachment://", "tc://"])
def test_literal_reference_text_reads_back_as_written(
    tmp_path: str, log_format: Literal["eval", "json"], protocol: str
) -> None:
    literal = f"{protocol}{_LITERAL_KEY}"
    log_file = _run_literal_eval(str(tmp_path), log_format, literal)

    # the literal names an attachment the sample really holds
    stored = read_eval_log(log_file)
    assert stored.samples
    assert stored.samples[0].attachments[_LITERAL_KEY] == _LITERAL_SYSTEM_PROMPT

    for resolve in (True, "core", "full"):
        log = read_eval_log(log_file, resolve_attachments=resolve)
        assert log.samples
        sample = log.samples[0]
        _assert_literals_read_back(sample, literal, calls=resolve != "core")
        if resolve == "core":
            _assert_literals_read_back(
                resolve_sample_attachments(sample, "full"), literal
            )


@solver
def _assert_events_evicted() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        assert transcript().history.resident_events_truncated
        return state

    return solve


@pytest.mark.parametrize("log_format", ["eval", "json"])
@pytest.mark.parametrize("protocol", ["attachment://", "tc://"])
def test_literal_reference_text_reads_back_from_bounded_transcript(
    tmp_path: str,
    monkeypatch: pytest.MonkeyPatch,
    log_format: Literal["eval", "json"],
    protocol: str,
) -> None:
    """The finished log takes evicted events from the sample buffer."""
    import inspect_ai._eval.task.run as run_module

    monkeypatch.setattr(run_module, "DEFAULT_RESIDENT_TAIL", 1)
    monkeypatch.setenv("INSPECT_TRANSCRIPT_BOUNDED", "true")
    literal = f"{protocol}{_LITERAL_KEY}"
    log_file = _run_literal_eval(
        str(tmp_path), log_format, literal, after=[_assert_events_evicted()]
    )

    for resolve in (True, "core", "full"):
        log = read_eval_log(log_file, resolve_attachments=resolve)
        assert log.samples
        sample = log.samples[0]
        _assert_literals_read_back(sample, literal, calls=resolve != "core")
        if resolve == "core":
            _assert_literals_read_back(
                resolve_sample_attachments(sample, "full"), literal
            )


@pytest.mark.parametrize("protocol", ["attachment://", "tc://"])
def test_recondensing_keeps_literals_and_genuine_references(
    tmp_path: str, protocol: str
) -> None:
    literal = f"{protocol}{_LITERAL_KEY}"
    log_file = _run_literal_eval(str(tmp_path), "eval", literal)
    log = read_eval_log(log_file)
    assert log.samples
    condensed = log.samples[0]

    once = condense_sample(condensed)
    twice = condense_sample(once)
    assert twice.model_dump() == once.model_dump()
    _assert_literals_read_back(resolve_sample_attachments(twice, "full"), literal)

    # write_eval_log condenses again on the way out
    log.samples = [twice]
    for log_format in ("eval", "json"):
        rewritten = os.path.join(tmp_path, f"rewritten.{log_format}")
        write_eval_log(log, rewritten)
        reread = read_eval_log(rewritten, resolve_attachments=True)
        assert reread.samples
        _assert_literals_read_back(reread.samples[0], literal)


@pytest.fixture(scope="module")
def literal_eval_log(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[str], str]:
    """Log of `_run_literal_eval` for a literal with the given prefix, run once per prefix."""
    logs: dict[str, str] = {}

    def get(protocol: str) -> str:
        if protocol not in logs:
            logs[protocol] = _run_literal_eval(
                str(tmp_path_factory.mktemp("literal")),
                "eval",
                f"{protocol}{_LITERAL_KEY}",
            )
        return logs[protocol]

    return get


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("resolve", [False, True, "core", "full"])
@pytest.mark.parametrize("to", ["eval", "json"])
@pytest.mark.parametrize("protocol", ["attachment://", "tc://"])
def test_convert_keeps_literals_and_genuine_references(
    tmp_path: str,
    literal_eval_log: Callable[[str], str],
    stream: bool,
    resolve: bool | Literal["full", "core"],
    to: Literal["eval", "json"],
    protocol: str,
) -> None:
    log_file = literal_eval_log(protocol)
    output_dir = os.path.join(tmp_path, "converted")
    convert_eval_logs(
        log_file,
        to,
        output_dir,
        resolve_attachments=resolve,
        stream=stream,
    )
    converted = os.path.join(
        output_dir, os.path.splitext(os.path.basename(log_file))[0] + f".{to}"
    )
    log = read_eval_log(converted, resolve_attachments=True)
    assert log.samples
    _assert_literals_read_back(log.samples[0], f"{protocol}{_LITERAL_KEY}")


@pytest.mark.parametrize("log_format", ["eval", "json"])
@pytest.mark.parametrize("protocol", ["attachment://", "tc://"])
def test_summary_input_keeps_literal_reference_text(
    tmp_path: str, log_format: Literal["eval", "json"], protocol: str
) -> None:
    # `named` names the system prompt's attachment; `chained` names the
    # attachment that holds `named` once it is stored as a literal
    named = f"{protocol}{_LITERAL_KEY}"
    chained = f"attachment://{mm3_hash(named)}"
    texts = [
        _LITERAL_SYSTEM_PROMPT,
        "attachment://ordinary-user-text",
        "tc://ordinary-user-text",
        named,
        chained,
    ]
    task = Task(
        dataset=[
            Sample(
                input=[
                    ChatMessageSystem(content=texts[0]),
                    *[ChatMessageUser(content=text) for text in texts[1:]],
                ]
            )
        ]
    )
    [log] = inspect_eval(
        task,
        model="mockllm/model",
        log_dir=str(tmp_path),
        log_format=log_format,
        display="none",
    )
    assert log.location

    def input_texts(input: str | list[ChatMessage]) -> list[str]:
        assert isinstance(input, list)
        return [message.text for message in input]

    # the summaries the recorder stored
    [summary] = read_eval_log_sample_summaries(log.location)
    assert input_texts(summary.input) == texts

    # summaries of the sample as read, which mirror its input
    for resolve in (False, True, "core", "full"):
        read = read_eval_log(log.location, resolve_attachments=resolve)
        assert read.samples
        sample = read.samples[0]
        assert sample.summary().input == sample.input
        if resolve:
            assert input_texts(sample.summary().input) == texts
        else:
            assert input_texts(condensed_sample_summary(sample).input) == texts


_GRADER_PROMPT = "Grade the answer against the target, in full detail please. " * 3
_GRADER_REQUEST_LITERAL = "tc://grader-request-text"


class _FailedRequestAPI(ModelAPI):
    """Answers as providers answer a request they could not run (e.g. too long): an empty output with the call marked as an error."""

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> tuple[ModelOutput, ModelCall]:
        call = set_active_model_event_call(
            {
                "messages": [
                    {"role": "user", "content": _GRADER_PROMPT},
                    {"role": "user", "content": _GRADER_REQUEST_LITERAL},
                ]
            }
        )
        call.set_error({"error": "The request is too long."})
        return (
            ModelOutput.from_content(self.model_name, "", stop_reason="model_length"),
            call,
        )


@modelapi(name="failedrequest")
def _failed_request_api() -> type[ModelAPI]:
    return _FailedRequestAPI


@scorer(metrics=[mean()])
def _literal_grader(literal: str) -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        # scoring keeps the call of a request the provider could not run
        failed = get_model("failedrequest/model", memoize=False)
        await failed.generate("Grade the answer.")
        grader = get_model(
            "mockllm/model",
            custom_outputs=[ModelOutput.from_content("mockllm/model", literal)],
            memoize=False,
        )
        output = await grader.generate("Grade the answer.")
        return Score(value=1, explanation=output.completion)

    return score


def _assert_failed_grader_call(model_events: list[ModelEvent]) -> None:
    """The grader's failed call kept its request, pooled and literal text alike."""
    failed = model_events[-2]
    assert failed.call is not None
    assert failed.call.error is True
    assert failed.call.request["messages"] == [
        {"role": "user", "content": _GRADER_PROMPT},
        {"role": "user", "content": _GRADER_REQUEST_LITERAL},
    ]


@pytest.mark.parametrize("log_format", ["eval", "json"])
@pytest.mark.parametrize("action", ["append", "overwrite"])
@pytest.mark.parametrize("read", [False, "core"])
def test_rescoring_keeps_literal_reference_text(
    tmp_path: str,
    log_format: Literal["eval", "json"],
    action: Literal["append", "overwrite"],
    read: Literal[False, "core"],
) -> None:
    literal = f"attachment://{_LITERAL_KEY}"
    log_file = _run_literal_eval(str(tmp_path), log_format, literal)

    scored = score(
        read_eval_log(log_file, resolve_attachments=read),
        _literal_grader(literal),
        action=action,
        display="none",
    )
    rescored = os.path.join(tmp_path, f"rescored.{log_format}")
    write_eval_log(scored, rescored)

    reread = read_eval_log(rescored, resolve_attachments=True)
    assert reread.samples
    sample = reread.samples[0]
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len(model_events) == 4
    assert model_events[0].input[0].text == _LITERAL_SYSTEM_PROMPT
    grader_event = model_events[-1]
    assert grader_event.input[0].text == "Grade the answer."
    assert grader_event.output.message.text == literal
    _assert_failed_grader_call(model_events)
    assert sample.messages[-1].text == literal


@pytest.mark.parametrize("log_format", ["eval", "json"])
@pytest.mark.parametrize("action", ["append", "overwrite"])
def test_rescoring_fully_read_log_keeps_literal_reference_text(
    tmp_path: str,
    log_format: Literal["eval", "json"],
    action: Literal["append", "overwrite"],
) -> None:
    # the earlier reply names the attachment the grader's text is stored in
    grader_text = "tc://ordinary-grader-text"
    reply = f"attachment://{mm3_hash(grader_text)}"
    log_file = _run_literal_eval(str(tmp_path), log_format, reply)

    scored = score(
        read_eval_log(log_file, resolve_attachments="full"),
        _literal_grader(grader_text),
        action=action,
        display="none",
    )
    rescored = os.path.join(tmp_path, f"rescored.{log_format}")
    write_eval_log(scored, rescored)

    reread = read_eval_log(rescored, resolve_attachments=True)
    assert reread.samples
    sample = reread.samples[0]
    assert sample.messages[0].text == _LITERAL_SYSTEM_PROMPT
    assert sample.messages[-1].text == reply
    assert sample.output.completion == reply
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len(model_events) == 4
    assert model_events[1].input[0].text == _LITERAL_SYSTEM_PROMPT
    assert model_events[1].output.message.text == reply
    assert model_events[-1].output.message.text == grader_text
    _assert_failed_grader_call(model_events)


@pytest.mark.parametrize("to", ["eval", "json"])
@pytest.mark.parametrize("resolve", [False, "core", "full"])
@pytest.mark.parametrize("protocol", ["attachment://", "tc://"])
def test_writing_read_log_keeps_literals_and_genuine_references(
    tmp_path: str,
    literal_eval_log: Callable[[str], str],
    to: Literal["eval", "json"],
    resolve: Literal[False, "core", "full"],
    protocol: str,
) -> None:
    # after a "core" read the sample keeps the system prompt's attachment,
    # which its model calls reference and the literal names
    log = read_eval_log(literal_eval_log(protocol), resolve_attachments=resolve)
    copy = os.path.join(tmp_path, f"copy.{to}")
    write_eval_log(log, copy)

    reread = read_eval_log(copy, resolve_attachments=True)
    assert reread.samples
    _assert_literals_read_back(reread.samples[0], f"{protocol}{_LITERAL_KEY}")


def _resolved_core_sample() -> EvalSample:
    """Sample whose message text names an attachment that its model call references."""
    long_text = "genuine long text " * 10
    key = mm3_hash(long_text)
    event = ModelEvent(
        model="test-model",
        input=[ChatMessageUser(content=long_text)],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", "reply"),
        call=ModelCall(
            request={"messages": [{"role": "user", "content": f"attachment://{key}"}]},
            response={},
        ),
    )
    return EvalSample(
        id="sample",
        epoch=1,
        input="input",
        target="target",
        messages=[ChatMessageAssistant(content=f"attachment://{key}")],
        events=[event],
        attachments={key: long_text},
    )


def test_unmarked_sample_is_condensed_as_holding_references() -> None:
    sample = mark_attachments_resolved(_resolved_core_sample(), "core")
    literal = sample.messages[0].text
    long_text = next(iter(sample.attachments.values()))

    resolved = resolve_sample_attachments(condense_sample(sample), "full")
    assert resolved.messages[0].text == literal

    # dumping and validating drops the mark, so the literal is taken as a
    # reference, as before the mark existed
    unmarked = EvalSample.model_validate(sample.model_dump())
    resolved = resolve_sample_attachments(condense_sample(unmarked), "full")
    assert resolved.messages[0].text == long_text


def test_resolving_a_resolved_sample_resolves_only_what_is_left() -> None:
    sample = mark_attachments_resolved(_resolved_core_sample(), "core")
    literal = sample.messages[0].text
    long_text = next(iter(sample.attachments.values()))

    assert resolve_sample_attachments(sample, "core") is sample
    full = resolve_sample_attachments(sample, "full")
    assert full.messages[0].text == literal
    [event] = [e for e in full.events if isinstance(e, ModelEvent)]
    assert event.call is not None
    assert event.call.request["messages"] == [{"role": "user", "content": long_text}]
    assert full.attachments == {}
    assert resolve_sample_attachments(full, "full") is full


_RETRY_IMAGE = "data:image/png;base64," + ("A" * 200)


@solver
def _fail_when_marked() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.metadata.get("fail"):
            raise ValueError("Marked to fail.")
        return state

    return solve


@task
def literal_retry_task() -> Task:
    return Task(
        dataset=[
            Sample(
                id=1,
                input=[
                    ChatMessageSystem(content=_LITERAL_SYSTEM_PROMPT),
                    ChatMessageUser(
                        content=[
                            ContentText(text="Describe the image."),
                            ContentImage(image=_RETRY_IMAGE),
                        ]
                    ),
                ],
            ),
            Sample(id=2, input="fail", metadata={"fail": True}),
        ],
        solver=[_fail_when_marked(), generate()],
    )


@pytest.mark.parametrize(
    "log_format,seeded",
    [
        # no seed: run.py logs the reused prior sample through condense_sample
        ("eval", False),
        # a .json log is seeded by re-logging each prior sample
        ("json", True),
    ],
)
def test_retry_reuse_keeps_genuine_references(
    tmp_path: str,
    monkeypatch: pytest.MonkeyPatch,
    log_format: Literal["eval", "json"],
    seeded: bool,
) -> None:
    literal = f"attachment://{_LITERAL_KEY}"
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", literal)],
    )
    [log] = inspect_eval(
        literal_retry_task(),
        model=model,
        log_dir=str(tmp_path),
        log_format=log_format,
        max_samples=1,
        display="none",
    )
    assert log.status == "error"

    if not seeded:

        async def no_seed(*args: object, **kwargs: object) -> None:
            return None

        monkeypatch.setattr(TaskLogger, "seed_from_prior", no_seed)

    [retried] = eval_retry(log, log_dir=str(tmp_path), display="none")
    assert retried.location

    stored = read_eval_log(retried.location)
    assert stored.samples
    [reused] = [s for s in stored.samples if s.id == 1]
    # genuine references were kept, not stored as literal text
    assert {
        value
        for value in reused.attachments.values()
        if value.startswith(ATTACHMENT_PROTOCOL)
    } == {literal}

    [sample] = [s for s in _resolved_samples(retried.location) if s.id == 1]
    assert sample.messages[0].text == _LITERAL_SYSTEM_PROMPT
    image = sample.messages[1].content
    assert isinstance(image, list)
    assert isinstance(image[1], ContentImage)
    assert image[1].image == _RETRY_IMAGE
    assert sample.messages[-1].text == literal
    [model_event] = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert model_event.input[0].text == _LITERAL_SYSTEM_PROMPT
    assert model_event.output.message.text == literal


def _resolved_samples(location: str) -> list[EvalSample]:
    log = read_eval_log(location, resolve_attachments=True)
    assert log.samples
    return log.samples


def test_recondense_does_not_wrap_genuine_references() -> None:
    image = "data:image/png;base64," + ("B" * 120)
    long_text = "genuine long text " * 10
    attachments = {mm3_hash(image): image, mm3_hash(long_text): long_text}
    image_ref = f"{ATTACHMENT_PROTOCOL}{mm3_hash(image)}"
    text_ref = f"{ATTACHMENT_PROTOCOL}{mm3_hash(long_text)}"
    event = ModelEvent(
        model="test-model",
        input=[ChatMessageUser(content=text_ref)],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", text_ref),
        call=ModelCall(
            request={"messages": [{"role": "user", "content": text_ref}]},
            response={"content": text_ref},
        ),
    )
    sample = EvalSample(
        id="sample",
        epoch=1,
        input="input",
        target="target",
        messages=[ChatMessageUser(content=[ContentImage(image=image_ref)])],
        events=[event],
        attachments=attachments,
    )

    for condensed in (
        condense_sample(sample),
        condense_sample(condense_sample(sample)),
    ):
        assert condensed.attachments == attachments
        image_content = condensed.messages[0].content
        assert isinstance(image_content, list)
        assert isinstance(image_content[0], ContentImage)
        assert image_content[0].image == image_ref
        resolved = resolve_sample_attachments(condensed, "full")
        [model_event] = [e for e in resolved.events if isinstance(e, ModelEvent)]
        assert model_event.input[0].text == long_text
        assert model_event.output.message.text == long_text
        assert model_event.call is not None
        assert model_event.call.response == {"content": long_text}


def test_condense_core_sample_escapes_literals_outside_model_calls() -> None:
    long_text = "genuine long text " * 10
    text_ref = f"{ATTACHMENT_PROTOCOL}{mm3_hash(long_text)}"
    event = ModelEvent(
        model="test-model",
        input=[ChatMessageUser(content=long_text)],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", text_ref),
        # the transcript condensed the call while the sample ran
        call=ModelCall(
            request={"messages": [{"role": "user", "content": text_ref}]},
            response={},
        ),
    )
    sample = EvalSample(
        id="sample",
        epoch=1,
        input="input",
        target="target",
        messages=[ChatMessageAssistant(content=text_ref)],
        events=[event],
        attachments={mm3_hash(long_text): long_text},
    )

    resolved = resolve_sample_attachments(
        condense_sample(mark_attachments_resolved(sample, "core")), "full"
    )
    assert resolved.messages[0].text == text_ref
    [model_event] = [e for e in resolved.events if isinstance(e, ModelEvent)]
    assert model_event.output.message.text == text_ref
    assert model_event.input[0].text == long_text
    assert model_event.call is not None
    assert model_event.call.request["messages"] == [
        {"role": "user", "content": long_text}
    ]


def test_seeded_error_retries_are_resolved() -> None:
    long_text = "earlier attempt input " * 10
    text_ref = f"{ATTACHMENT_PROTOCOL}{mm3_hash(long_text)}"
    event = ModelEvent(
        model="test-model",
        input=[ChatMessageUser(content=text_ref)],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", "response"),
    )
    prior = EvalSample(
        id="sample",
        epoch=1,
        input="input",
        target="target",
        error_retries=[
            EvalRetryError(
                message="retry", traceback="", traceback_ansi="", events=[event]
            )
        ],
        attachments={mm3_hash(long_text): long_text},
    )

    [seeded] = _seed_error_retries(prior)
    assert seeded.events is not None
    [seeded_event] = seeded.events
    assert isinstance(seeded_event, ModelEvent)
    assert seeded_event.input[0].text == long_text

    # condensed for the new attempt's log, the retry history still resolves
    rerun = EvalSample(
        id="sample", epoch=1, input="input", target="target", error_retries=[seeded]
    )
    resolved = resolve_sample_attachments(
        condense_sample(mark_attachments_resolved(rerun, "core")), "full"
    )
    assert resolved.error_retries is not None
    retry_events = resolved.error_retries[0].events
    assert retry_events is not None
    assert isinstance(retry_events[0], ModelEvent)
    assert retry_events[0].input[0].text == long_text


def _literal_call_event(literal: str) -> ModelEvent:
    return ModelEvent(
        model="test-model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", literal),
        pending=True,
    )


def test_transcript_condenses_each_model_call_once() -> None:
    long_text = "genuine long text " * 10
    text_ref = f"{ATTACHMENT_PROTOCOL}{mm3_hash(long_text)}"
    # names the attachment the long text is pooled in
    literal = text_ref
    raw = ModelCall(
        request={
            "messages": [
                {"role": "user", "content": long_text},
                {"role": "assistant", "content": literal},
            ]
        },
        response={"content": literal},
    )

    transcript = Transcript(log_model_api=True)
    notified: list[ModelCall] = []

    def record(event: Event) -> None:
        if isinstance(event, ModelEvent) and event.call is not None:
            notified.append(event.call.model_copy(deep=True))

    transcript._subscribe(record)
    event = _literal_call_event(literal)
    transcript._event(event)
    event.call = raw
    event.pending = None
    transcript._event_updated(event)  # completion
    condensed = event.call
    transcript._event_updated(event)  # timestamps
    assert event.call is condensed

    [resolved] = resolve_event_calls([event], transcript.attachments)
    assert isinstance(resolved, ModelEvent)
    assert resolved.call is not None
    assert resolved.call.request == raw.request
    assert resolved.call.response == raw.response

    # subscribers keep their own attachment store, so they are given the
    # literal inline: first the raw call, then the call with long text pooled
    assert [call.model_dump() for call in notified] == [
        raw.model_dump(),
        raw.model_copy(
            update={
                "request": {
                    "messages": [
                        {"role": "user", "content": text_ref},
                        {"role": "assistant", "content": literal},
                    ]
                }
            }
        ).model_dump(),
    ]

    # a call restored from a checkpoint is condensed already
    restored = Transcript(log_model_api=True)
    restored._extend_restored_events(
        [event.model_copy(update={"uuid": "restored"})], transcript.attachments
    )
    [restored_event] = restored.events
    assert isinstance(restored_event, ModelEvent)
    restored_call = restored_event.call
    restored._event_updated(restored_event)
    assert restored_event.call is restored_call


@solver
def _fail_first_attempt(marker: str) -> Solver:
    # a marker file, since eval_retry loads the task module again
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if not os.path.exists(marker):
            Path(marker).touch()
            raise ValueError("First attempt fails.")
        return state

    return solve


@solver
def _reply_with(text: str) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # a model of its own, so that eval_retry can rebuild the task's model
        model = get_model(
            "mockllm/model",
            custom_outputs=[ModelOutput.from_content("mockllm/model", text)],
            memoize=False,
        )
        output = await model.generate(state.messages)
        state.messages.append(output.message)
        return state

    return solve


@task
def literal_call_retry_task(marker: str, reply: str) -> Task:
    return Task(
        dataset=[
            Sample(
                input=[
                    ChatMessageSystem(content=_LITERAL_SYSTEM_PROMPT),
                    ChatMessageUser(content="hello"),
                ]
            )
        ],
        solver=[_reply_with(reply), _fail_first_attempt(marker)],
    )


@pytest.mark.parametrize("source", ["transcript", "realtime", "seeded"])
def test_error_retry_calls_keep_literals_and_genuine_references(
    tmp_path: Path, source: Literal["transcript", "realtime", "seeded"]
) -> None:
    literal = f"attachment://{_LITERAL_KEY}"
    task = literal_call_retry_task(marker=str(tmp_path / "failed"), reply=literal)
    if source == "seeded":
        # the retry history is seeded from the errored sample of the prior log
        [log] = inspect_eval(
            task, model="mockllm/model", log_dir=str(tmp_path), display="none"
        )
        assert log.status == "error"
        [log] = eval_retry(log, log_dir=str(tmp_path), display="none")
    else:
        # read from the transcript, with the sample buffer off and on
        [log] = inspect_eval(
            task,
            model="mockllm/model",
            log_dir=str(tmp_path),
            retry_on_error=1,
            log_realtime=source == "realtime",
            display="none",
        )
    assert log.status == "success"
    assert log.location

    [sample] = _resolved_samples(log.location)
    assert sample.error_retries is not None
    [retry] = sample.error_retries
    assert retry.events is not None
    [model_event] = [e for e in retry.events if isinstance(e, ModelEvent)]
    assert model_event.call is not None
    request_messages = model_event.call.request["messages"]
    assert isinstance(request_messages, list)
    assert isinstance(request_messages[0], dict)
    assert request_messages[0]["content"] == _LITERAL_SYSTEM_PROMPT
    assert model_event.call.response == {"content": literal}


@pytest.mark.parametrize("ending", ["error", "cancel"])
async def test_subscribers_see_the_error_completion_of_a_call_with_literals(
    tmp_path: Path, ending: Literal["error", "cancel"]
) -> None:
    long_text = "genuine long text " * 10
    # long enough to be pooled as an attachment
    long_error = "The provider failed to answer this request. " * 3
    literal = f"{ATTACHMENT_PROTOCOL}{mm3_hash(long_text)}"
    request: dict[str, JsonValue] = {
        "messages": [
            {"role": "user", "content": long_text},
            {"role": "user", "content": literal},
        ]
    }
    published = anyio.Event()

    async def outputs(*args: object) -> ModelOutput:
        # a provider publishes its request before sending it
        set_active_model_event_call(request)
        if ending == "error":
            raise RuntimeError(long_error)
        published.set()
        await anyio.sleep_forever()
        raise AssertionError("not reached")

    model = get_model("mockllm/model", custom_outputs=outputs, memoize=False)
    transcript = Transcript(log_model_api=True)
    notified: list[ModelCall] = []

    def record(event: Event) -> None:
        if isinstance(event, ModelEvent) and event.call is not None:
            notified.append(event.call.model_copy(deep=True))

    transcript._subscribe(record)
    buffer = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    buffer.start_sample(EvalSampleSummary(id="s1", epoch=1, input="in", target="t"))
    transcript._subscribe_store(
        lambda e, attachments: buffer.log_events(
            [SampleEvent(id="s1", epoch=1, event=e)], attachments
        )
    )
    token = _transcript.set(None)
    try:
        init_transcript(transcript)
        if ending == "error":
            with pytest.raises(RuntimeError, match="The provider failed"):
                await model.generate("hello")
        else:
            async with anyio.create_task_group() as tg:
                tg.start_soon(model.generate, "hello")
                await published.wait()
                tg.cancel_scope.cancel()
    finally:
        _transcript.reset(token)

    [event] = [e for e in transcript.events if isinstance(e, ModelEvent)]
    assert event.call is not None
    assert event.call.error is True
    assert event.call.response is not None
    [resolved] = resolve_event_calls([event], transcript.attachments)
    assert isinstance(resolved, ModelEvent) and resolved.call is not None
    assert resolved.call.request == request

    error_response = resolved.call.response
    assert error_response is not None
    if ending == "error":
        assert long_error in json.dumps(error_response)

    # the last notification carries the error completion raw, literals inline
    last = notified[-1]
    assert last.error is True
    assert last.response == error_response
    assert last.request == {
        "messages": [
            {"role": "user", "content": literal},
            {"role": "user", "content": literal},
        ]
    }

    # the sample buffer holds the whole error response
    with buffer.open_sample_history("s1", 1) as history:
        buffered = resolve_events_attachments(
            materialize_pooled_events(
                list(history.iter_events()),
                history.events_data["messages"],
                history.events_data["calls"],
            ),
            history.attachments,
            "full",
        )
    [buffered_event] = [e for e in buffered if isinstance(e, ModelEvent)]
    assert buffered_event.call is not None
    assert buffered_event.call.response == error_response
    assert buffered_event.call.request == request


def test_evicted_call_is_renotified_with_its_literals(tmp_path: Path) -> None:
    """An evicted model event re-notified while it is still held keeps its literals."""
    literal = "attachment://as-written"
    transcript = Transcript(log_model_api=True, bounded=True, resident_tail=1)
    buffer = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    buffer.start_sample(EvalSampleSummary(id="s", epoch=1, input="in", target="t"))
    transcript._subscribe_store(
        lambda e, attachments: buffer.log_events(
            [SampleEvent(id="s", epoch=1, event=e)], attachments
        )
    )
    event = ModelEvent(
        model="m",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("m", ""),
        pending=True,
    )
    transcript._event(event)
    event.call = ModelCall(request={"messages": [{"content": literal}]})
    transcript._event_updated(event)
    transcript._event(InfoEvent(data="other activity while call is pending"))
    event.call = ModelCall(
        request={"messages": [{"content": literal}]}, response={"content": "ok"}
    )
    event.pending = None
    transcript._event_updated(event)
    assert event not in transcript.history.resident_events

    # Model.generate re-notifies the completed event with its timings
    transcript._event_updated(event)

    with buffer.open_sample_history("s", 1) as history:
        events = resolve_events_attachments(
            materialize_pooled_events(
                list(history.iter_events()),
                history.events_data["messages"],
                history.events_data["calls"],
            ),
            history.attachments,
            "full",
        )
    [stored] = [e for e in events if isinstance(e, ModelEvent)]
    assert stored.call is not None
    assert stored.call.request == {"messages": [{"content": literal}]}

    # the kept call is released at the next eviction after the event is freed
    del event
    gc.collect()
    transcript._event(InfoEvent(data="more activity"))
    assert transcript._condensed_calls == {}
    assert transcript._evicted_call_events == {}


async def test_live_sample_data_keeps_literals_and_genuine_references(
    tmp_path: Path,
) -> None:
    """The sample buffer stores literal reference text as attachments of its own.

    It is given the run's events as the sample transcript gives them to
    subscribers that keep their own attachment store. A reader that resolves
    each reference once, as the viewer does with `get_sample_data`, reads
    the literal back, and the pooled system prompt as its text.
    """
    literal = f"{ATTACHMENT_PROTOCOL}{_LITERAL_KEY}"
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", literal)],
        memoize=False,
    )
    transcript = Transcript(log_model_api=True)
    buffer = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    buffer.start_sample(
        EvalSampleSummary(
            id="s1", epoch=1, input=[ChatMessageUser(content=literal)], target="t"
        )
    )
    transcript._subscribe_store(
        lambda e, attachments: buffer.log_events(
            [SampleEvent(id="s1", epoch=1, event=e)], attachments
        )
    )
    token = _transcript.set(None)
    try:
        init_transcript(transcript)
        await model.generate(
            [
                ChatMessageSystem(content=_LITERAL_SYSTEM_PROMPT),
                ChatMessageUser(content=literal),
            ]
        )
    finally:
        _transcript.reset(token)

    data = buffer.get_sample_data("s1", 1)
    assert data is not None
    attachments = {
        attachment.hash: attachment.content for attachment in data.attachments
    }
    assert attachments[_LITERAL_KEY] == _LITERAL_SYSTEM_PROMPT
    [event] = [
        e
        for e in resolve_events_attachments(
            reconstruct_events(data), attachments, "full"
        )
        if isinstance(e, ModelEvent)
    ]
    assert [message.text for message in event.input] == [
        _LITERAL_SYSTEM_PROMPT,
        literal,
    ]
    assert event.output.message.text == literal
    assert event.call is not None
    request_messages = event.call.request["messages"]
    assert isinstance(request_messages, list)
    assert [
        message["content"] for message in request_messages if isinstance(message, dict)
    ] == [_LITERAL_SYSTEM_PROMPT, literal]
    assert event.call.response == {"content": literal}

    samples = buffer.get_samples()
    assert isinstance(samples, Samples)
    [summary] = samples.samples
    assert isinstance(summary.input, list)
    assert summary.input[0].text == literal
