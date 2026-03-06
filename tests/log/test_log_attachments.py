import os

from inspect_ai.event._model import ModelEvent
from inspect_ai.log._condense import (
    ATTACHMENT_PROTOCOL,
    condense_event,
    condense_sample,
    resolve_sample_attachments,
)
from inspect_ai.log._file import read_eval_log
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput


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
