from typing import Any

from test_helpers.message_ids import edited_id

from inspect_ai._util.content import (
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentText,
)
from inspect_ai._util.registry import RegistryInfo, set_registry_info
from inspect_ai.model import ChatMessage, ChatMessageTool, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import (
    Model,
    ModelAPI,
    tool_result_media_as_user_message,
)
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo


def test_multiple_tool_responses_remain_adjacent():
    """Consecutive document tool results are grouped into one user message."""
    document_a = ContentDocument(document="/path/to/report-a.pdf")
    document_b = ContentDocument(document="/path/to/report-b.pdf")
    tool_a = ChatMessageTool(tool_call_id="a", content=[document_a])
    tool_b = ChatMessageTool(tool_call_id="b", content=[document_b])

    execute_and_assert(
        [tool_a, tool_b],
        [
            _modified_document_response_message(tool_a),
            _modified_document_response_message(tool_b),
            ChatMessageUser(
                content=[document_a, document_b],
                tool_call_id=["a", "b"],
            ),
        ],
    )


def test_multiple_tool_responses_remain_adjacent_when_not_at_end_of_list():
    """Document tool results flush before the next non-tool message."""
    document_a = ContentDocument(document="/path/to/report-a.pdf")
    document_b = ContentDocument(document="/path/to/report-b.pdf")
    tool_a = ChatMessageTool(tool_call_id="a", content=[document_a])
    tool_b = ChatMessageTool(tool_call_id="b", content=[document_b])
    user = ChatMessageUser(content="yo")

    execute_and_assert(
        [tool_a, tool_b, user],
        [
            _modified_document_response_message(tool_a),
            _modified_document_response_message(tool_b),
            ChatMessageUser(
                content=[document_a, document_b],
                tool_call_id=["a", "b"],
            ),
            user,
        ],
    )


async def test_model_generate_replays_documents_as_user_messages():
    """Providers without native replay move documents into a fabricated user message."""
    document = ContentDocument(document="data:application/pdf;base64,AAAA")
    api = _CaptureAPI()
    model = Model(api, GenerateConfig())

    await model.generate([ChatMessageTool(tool_call_id="doc", content=[document])])

    assert api.input is not None
    assert_messages_equal(
        api.input,
        [
            ChatMessageTool(
                tool_call_id="doc",
                content=[ContentText(text="Document content is included below.")],
            ),
            ChatMessageUser(content=[document], tool_call_id=["doc"]),
        ],
    )


async def test_model_generate_preserves_document_tool_results_for_supporting_providers():
    """Native providers keep structured document tool results unchanged."""
    document = ContentDocument(document="data:application/pdf;base64,AAAA")
    api = _CaptureAPI(replay_documents=True)
    model = Model(api, GenerateConfig())

    await model.generate([ChatMessageTool(tool_call_id="doc", content=[document])])

    assert api.input is not None
    assert_messages_equal(
        api.input,
        [ChatMessageTool(tool_call_id="doc", content=[document])],
    )


async def test_model_generate_preserves_image_and_document_order_in_fallback():
    """Mixed media fallback preserves the original content order."""
    image = ContentImage(image="data:image/png;base64,AAAA")
    document = ContentDocument(document="data:application/pdf;base64,AAAA")
    api = _CaptureAPI()
    model = Model(api, GenerateConfig())

    await model.generate(
        [ChatMessageTool(tool_call_id="mixed", content=[image, document])]
    )

    assert api.input is not None
    assert_messages_equal(
        api.input,
        [
            ChatMessageTool(
                tool_call_id="mixed",
                content=[
                    ContentText(text="Image content is included below."),
                    ContentText(text="Document content is included below."),
                ],
            ),
            ChatMessageUser(content=[image, document], tool_call_id=["mixed"]),
        ],
    )


def test_combined_image_and_document_extraction():
    """Extracting both images and documents in a single call works correctly."""
    image = ContentImage(image="image_for_tool")
    document = ContentDocument(document="/path/to/report.pdf")
    tool = ChatMessageTool(tool_call_id="mixed", content=[image, document])

    transformed = tool_result_media_as_user_message(
        [tool], (ContentImage, ContentDocument)
    )
    assert_messages_equal(
        transformed,
        [
            ChatMessageTool(
                tool_call_id="mixed",
                content=[
                    ContentText(text="Image content is included below."),
                    ContentText(text="Document content is included below."),
                ],
            ),
            ChatMessageUser(content=[image, document], tool_call_id=["mixed"]),
        ],
    )


def test_non_placeholder_media_does_not_leak_tool_call_id():
    """Media without a placeholder cannot leak its ID across a user boundary."""
    audio = ContentAudio(audio="a.mp3", format="mp3")
    image = ContentImage(image="image_for_tool")
    user = ChatMessageUser(content="in between")

    transformed = tool_result_media_as_user_message(
        [
            ChatMessageTool(
                tool_call_id="call_AUDIO",
                function="listen",
                content=[audio],
            ),
            user,
            ChatMessageTool(
                tool_call_id="call_IMG",
                function="shot",
                content=[image],
            ),
        ],
        (ContentAudio, ContentImage),
    )

    assert_messages_equal(
        transformed,
        [
            ChatMessageTool(
                tool_call_id="call_AUDIO",
                function="listen",
                content=[audio],
            ),
            user,
            ChatMessageTool(
                tool_call_id="call_IMG",
                function="shot",
                content=[ContentText(text="Image content is included below.")],
            ),
            ChatMessageUser(content=[image], tool_call_id=["call_IMG"]),
        ],
    )


def execute_and_assert(input_messages: list[ChatMessage], expected: list[ChatMessage]):
    transformed = tool_result_media_as_user_message(input_messages, (ContentDocument,))
    assert_messages_equal(transformed, expected)


def assert_messages_equal(
    actual: list[ChatMessage], expected: list[ChatMessage]
) -> None:
    assert [_comparable(message) for message in actual] == [
        _comparable(message) for message in expected
    ]


def _comparable(message: ChatMessage) -> dict[str, Any]:
    """The message without its id, which `test_media_message_ids` checks."""
    return message.model_dump(exclude={"id"})


def test_media_message_ids() -> None:
    """Edited tool messages and the new user message get ids derived from their sources."""
    tool_a = ChatMessageTool(
        tool_call_id="a", content=[ContentDocument(document="a.pdf")]
    )
    tool_b = ChatMessageTool(
        tool_call_id="b", content=[ContentDocument(document="b.pdf")]
    )
    user = ChatMessageUser(content="next")

    transformed = tool_result_media_as_user_message(
        [tool_a, tool_b, user], (ContentDocument,)
    )

    for edited, source in zip(transformed[:2], [tool_a, tool_b]):
        assert edited.id == edited_id(source.id, edited) != source.id
        assert edited.metadata is None
    again = tool_result_media_as_user_message(
        [tool_a, tool_b, user], (ContentDocument,)
    )
    assert [m.id for m in again] == [m.id for m in transformed]
    media = transformed[2]
    assert media.id not in {tool_a.id, tool_b.id, user.id}
    assert media.metadata is None
    assert transformed[3] is user


def _modified_document_response_message(message: ChatMessageTool) -> ChatMessageTool:
    return message.model_copy(
        update={"content": [ContentText(text="Document content is included below.")]}
    )


class _CaptureAPI(ModelAPI):
    def __init__(self, *, replay_documents: bool = False) -> None:
        super().__init__("model")
        set_registry_info(self, RegistryInfo(type="modelapi", name="test"))
        self.input: list[ChatMessage] | None = None
        self._replay_documents = replay_documents

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        self.input = input
        return ModelOutput.from_content("model", "ok")

    def tool_result_documents(self) -> bool:
        return self._replay_documents


def test_media_message_id_depends_on_what_was_moved() -> None:
    """Models with different media support move different content: different ids."""
    source = ChatMessageTool(
        tool_call_id="a",
        content=[
            ContentImage(image="data:image/png;base64,iVBORw0KGgo="),
            ContentDocument(document="report.pdf"),
        ],
    )

    images = tool_result_media_as_user_message([source], (ContentImage,))
    both = tool_result_media_as_user_message([source], (ContentImage, ContentDocument))
    again = tool_result_media_as_user_message([source], (ContentImage,))

    assert images[1].content != both[1].content
    assert images[1].id != both[1].id
    assert images[0].id != both[0].id
    assert [m.id for m in again] == [m.id for m in images]
