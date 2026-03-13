from inspect_ai._util.content import ContentDocument, ContentImage, ContentText
from inspect_ai._util.registry import RegistryInfo, set_registry_info
from inspect_ai.model import ChatMessage, ChatMessageTool, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import (
    Model,
    ModelAPI,
    tool_result_documents_as_user_message,
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
    document = ContentDocument(document="/path/to/report.pdf")
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
    document = ContentDocument(document="/path/to/report.pdf")
    api = _CaptureAPI(replay_documents=True)
    model = Model(api, GenerateConfig())

    await model.generate([ChatMessageTool(tool_call_id="doc", content=[document])])

    assert api.input is not None
    assert_messages_equal(
        api.input,
        [ChatMessageTool(tool_call_id="doc", content=[document])],
    )


async def test_model_generate_applies_image_and_document_rewrites_together():
    """Image and document fallbacks both run when native replay is unavailable."""
    image = ContentImage(image="image_for_tool")
    document = ContentDocument(document="/path/to/report.pdf")
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
            ChatMessageUser(content=[document], tool_call_id=["mixed"]),
            ChatMessageUser(content=[image], tool_call_id=["mixed"]),
        ],
    )


def execute_and_assert(input_messages: list[ChatMessage], expected: list[ChatMessage]):
    transformed = tool_result_documents_as_user_message(input_messages)
    assert_messages_equal(transformed, expected)


def assert_messages_equal(
    actual: list[ChatMessage], expected: list[ChatMessage]
) -> None:
    assert [message.model_dump(exclude={"id"}) for message in actual] == [
        message.model_dump(exclude={"id"}) for message in expected
    ]


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
