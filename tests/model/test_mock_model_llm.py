import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._providers.mockllm import MockLLM
from inspect_ai.scorer import includes
from inspect_ai.solver import generate
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo


@pytest.mark.asyncio
@skip_if_trio
async def test_mock_generate_default() -> None:
    model = get_model("mockllm/model")

    response = await model.generate(input="unused")
    assert response.completion == MockLLM.default_output


@pytest.mark.asyncio
@skip_if_trio
async def test_mock_generate_custom_valid() -> None:
    custom_content_str = "custom #content"
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(model="mockllm", content=custom_content_str)
        ],
    )

    response = await model.generate(input="unused input")
    assert response.completion == custom_content_str


@pytest.mark.asyncio
@skip_if_trio
async def test_mock_generate_custom_invalid() -> None:
    model = get_model(
        "mockllm/model",
        custom_outputs=["this list of strings should actually be a ModelOutput"],
    )
    with pytest.raises(ValueError) as e_info:
        await model.generate([])
    assert "must be an instance of ModelOutput" in str(e_info.value)


@pytest.mark.asyncio
@skip_if_trio
async def test_mock_generate_custom_invalid_iterable_string() -> None:
    model = get_model(
        "mockllm/model",
        custom_outputs="this string should actually be a ModelOutput",
    )
    with pytest.raises(ValueError) as e_info:
        await model.generate([])
    assert "must be an instance of ModelOutput" in str(e_info.value)


@pytest.mark.asyncio
@skip_if_trio
async def test_mock_generate_custom_invalid_iterable_number() -> None:
    with pytest.raises(ValueError) as e_info:
        get_model(
            "mockllm/model",
            custom_outputs=0,
        )
    assert "must be an Iterable, Generator, or Callable" in str(e_info.value)


@pytest.mark.asyncio
@skip_if_trio
async def test_mock_generate_not_enough() -> None:
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(model="mockllm", content="first response"),
            ModelOutput.from_content(model="mockllm", content="second response"),
        ],
    )

    await model.generate(input="unused input")
    await model.generate(input="unused input")
    with pytest.raises(ValueError) as e_info:
        await model.generate(input="unused input")
        assert "custom_outputs ran out of values" in str(e_info.value)


@pytest.mark.asyncio
@skip_if_trio
async def test_mock_generate_custom_callable() -> None:
    def custom_output_generator(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        return ModelOutput.from_content(
            model="mockllm", content="response from callable"
        )

    model = get_model("mockllm/model", custom_outputs=custom_output_generator)

    response = await model.generate(input="unused input")
    assert response.completion == "response from callable"


@pytest.mark.asyncio
@skip_if_trio
async def test_mock_generate_custom_callable_with_params() -> None:
    def custom_output_generator(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        # Use the input to customize the response
        input_text = str(input) if input else "no input"
        return ModelOutput.from_content(
            model="mockllm", content=f"processed: {input_text}"
        )

    model = get_model("mockllm/model", custom_outputs=custom_output_generator)

    response = await model.generate(input="test input")
    assert "processed:" in response.completion
    assert "test input" in response.completion


def test_mock_model_eval():
    task = Task(
        dataset=[
            Sample(
                input="your responses are laughably predictable",
                target=MockLLM.default_output,
            ),
        ],
        solver=[generate()],
        scorer=includes(),
    )

    result = eval(task, model="mockllm/model")[0]

    assert result.status == "success"
    assert result.samples[0].messages[-1].content == MockLLM.default_output
