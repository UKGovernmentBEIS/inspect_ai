import pytest

from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessageAssistant,
    ModelOutput,
)
from inspect_ai.model._error_handler import (
    CANT_ASSIST,
    LLMCannotAssistError,
    PromptTooLongError,
    handle_model_errors,
    raise_if_error,
)
from inspect_ai.model._model_call import ModelCall


def create_model_output(content):
    return ModelOutput(
        model="test_model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content=content, source="generate"),
                stop_reason="stop",
            )
        ],
    )


@pytest.mark.parametrize(
    "content,expected_exception,expected_tokens_used,expected_model_limit",
    [
        ("Normal response", None, None, None),
        (
            "Invalid 'messages[0].content': string too long",
            PromptTooLongError,
            None,
            None,
        ),
        (
            "This model's maximum context length is 4096 tokens. However, your messages resulted in 5000 tokens",
            PromptTooLongError,
            5000,
            4096,
        ),
        (
            "prompt is too long: 5000 tokens > 4096 maximum",
            PromptTooLongError,
            5000,
            4096,
        ),
        (CANT_ASSIST, LLMCannotAssistError, None, None),
    ],
)
def test_raise_if_error(
    content, expected_exception, expected_tokens_used, expected_model_limit
):
    model_output = create_model_output(content)

    if expected_exception:
        with pytest.raises(expected_exception) as exc_info:
            raise_if_error(model_output)

        if expected_exception == PromptTooLongError:
            error = exc_info.value
            assert error.message == content
            assert error.tokens_used == expected_tokens_used
            assert error.model_limit_tokens == expected_model_limit
    else:
        raise_if_error(model_output)  # Should not raise an exception


@pytest.mark.asyncio
async def test_handle_model_errors_decorator():
    @handle_model_errors
    async def mock_generate():
        return create_model_output(CANT_ASSIST)

    with pytest.raises(LLMCannotAssistError):
        await mock_generate()


@pytest.mark.asyncio
async def test_handle_model_errors_decorator_no_error():
    @handle_model_errors
    async def mock_generate():
        return create_model_output("This is a normal response")

    result = await mock_generate()
    assert isinstance(result, ModelOutput)
    assert result.choices[0].message.content == "This is a normal response"


@pytest.mark.asyncio
async def test_handle_model_errors_decorator_with_tuple():
    @handle_model_errors
    async def mock_generate():
        model_output = create_model_output(CANT_ASSIST)
        return model_output, ModelCall.create({}, {})

    with pytest.raises(LLMCannotAssistError):
        await mock_generate()
