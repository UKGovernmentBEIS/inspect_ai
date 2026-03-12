from inspect_ai._util.content import ContentDocument, ContentImage, ContentText
from inspect_ai._util.registry import RegistryInfo, set_registry_info
from inspect_ai.model import ChatMessage, ChatMessageTool
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import (
    Model,
    ModelAPI,
    tool_result_document_text,
    tool_result_documents_as_text,
)
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo


def test_document_tool_results_are_converted_to_text():
    """Document tool results are downgraded to replay-safe text."""
    document = ContentDocument(document="/path/to/report.pdf")
    tool_message = ChatMessageTool(
        tool_call_id="doc",
        content=[document],
    )

    execute_and_assert(
        [tool_message],
        [
            ChatMessageTool(
                tool_call_id="doc",
                content=[tool_result_document_text(document)],
            )
        ],
    )


def test_non_document_tool_results_are_preserved():
    """Non-document tool results are left unchanged."""
    tool_message = ChatMessageTool(
        tool_call_id="mixed",
        content=[
            ContentText(text="Done"),
            ContentImage(image="image_for_tool"),
        ],
    )

    transformed = tool_result_documents_as_text([tool_message])

    assert transformed[0].content == tool_message.content


def test_mixed_document_tool_results_keep_other_content():
    """Only document blocks are rewritten in mixed tool results."""
    document = ContentDocument(document="/path/to/report.pdf")
    tool_message = ChatMessageTool(
        tool_call_id="mixed",
        content=[
            ContentText(text="Attached report"),
            document,
        ],
    )

    execute_and_assert(
        [tool_message],
        [
            ChatMessageTool(
                tool_call_id="mixed",
                content=[
                    ContentText(text="Attached report"),
                    tool_result_document_text(document),
                ],
            )
        ],
    )


async def test_model_generate_downgrades_document_tool_results_by_default():
    """Model.generate rewrites document tool results unless a provider opts in."""
    document = ContentDocument(document="/path/to/report.pdf")
    api = CaptureAPI()
    model = Model(api, GenerateConfig())

    await model.generate([ChatMessageTool(tool_call_id="doc", content=[document])])

    assert api.input is not None
    assert api.input[0].content == [tool_result_document_text(document)]


async def test_model_generate_preserves_document_tool_results_for_supported_providers():
    """Model.generate preserves document tool results for supporting providers."""
    document = ContentDocument(document="/path/to/report.pdf")
    api = CaptureAPI(replay_documents=True)
    model = Model(api, GenerateConfig())

    await model.generate([ChatMessageTool(tool_call_id="doc", content=[document])])

    assert api.input is not None
    assert api.input[0].content == [document]


def execute_and_assert(input_messages: list[ChatMessage], expected: list[ChatMessage]):
    transformed = tool_result_documents_as_text(input_messages)
    assert all(t.content == e.content for t, e in zip(transformed, expected))


class CaptureAPI(ModelAPI):
    def __init__(self, replay_documents: bool = False) -> None:
        super().__init__("model")
        set_registry_info(self, RegistryInfo(type="modelapi", name="capture"))
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
