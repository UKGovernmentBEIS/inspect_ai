import pytest

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.model._providers.mock_llm import MockLLM
from inspect_ai.scorer import includes
from inspect_ai.solver import generate


def test_mock_model_eval():
    task = Task(
        dataset=[
            Sample(
                input="your responses are laughably predictable",
                target=MockLLM.default_output,
            ),
        ],
        plan=[generate()],
        scorer=includes(),
    )

    result = eval(task, model="mockllm/model")[0]

    print(f"result: [{str(result)}]")

    assert result.status == "success"
    assert result.samples[0].messages[-1].content == MockLLM.default_output


@pytest.mark.asyncio
async def test_mock_generate_default() -> None:
    model = get_model("mockllm/model")

    response = await model.generate(input="unused")
    assert response.completion == MockLLM.default_output


@pytest.mark.asyncio
async def test_mock_generate_custom_valid() -> None:
    custom_content_str = "custom #content"
    model = get_model(
        "mockllm/model",
        custom_output=ModelOutput.from_content(
            model="mockllm", content=custom_content_str
        ),
    )

    response = await model.generate(input="unused input")
    assert response.completion == custom_content_str


@pytest.mark.asyncio
async def test_mock_generate_custom_invalid() -> None:
    with pytest.raises(ValueError) as e_info:
        get_model(
            "mockllm/model",
            custom_output="this string should actually be a ModelOutput",
        )
    assert "must be an instance of ModelOutput" in str(e_info.value)
