import pytest
from test_helpers.utils import (
    skip_if_github_action,
    skip_if_no_accelerate,
    skip_if_no_grok,
    skip_if_no_llama_cpp_python,
    skip_if_no_openai,
    skip_if_no_together,
    skip_if_no_transformers,
    skip_if_no_vllm,
)

from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelOutput, get_model


async def generate_with_logprobs(model_name, **model_kwargs) -> ModelOutput:
    model = get_model(
        model_name,
        config=GenerateConfig(
            logprobs=True, top_logprobs=2, temperature=0.001, max_tokens=50
        ),
        **model_kwargs,
    )

    message = ChatMessageUser(content="Hello.")
    return await model.generate(input=[message])


@pytest.mark.asyncio
@skip_if_no_openai
async def test_openai_logprobs() -> None:
    response = await generate_with_logprobs("openai/gpt-3.5-turbo")
    assert response.choices[0].logprobs is not None
    assert response.choices[0].logprobs.content[0].top_logprobs is not None
    assert len(response.choices[0].logprobs.content[0].top_logprobs) == 2


@pytest.mark.asyncio
@skip_if_no_grok
async def test_grok_logprobs() -> None:
    response = await generate_with_logprobs("grok/grok-beta")
    assert response.choices[0].logprobs is not None
    assert response.choices[0].logprobs.content[0].top_logprobs is not None


@pytest.mark.asyncio
@skip_if_no_together
async def test_together_logprobs() -> None:
    response = await generate_with_logprobs(
        "together/meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"
    )
    assert (
        response.choices[0].logprobs is not None
        and response.choices[0].logprobs.content[0].top_logprobs
        is None  # together only ever returns top-1, so top_logprobs should always be None
    )


@pytest.mark.asyncio
@skip_if_github_action
@skip_if_no_transformers
@skip_if_no_accelerate
async def test_hf_logprobs() -> None:
    response = await generate_with_logprobs(
        "hf/EleutherAI/pythia-70m",
        chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
    )
    assert (
        response.choices[0].logprobs
        and response.choices[0].logprobs.content[0].top_logprobs is not None
    )
    assert len(response.choices[0].logprobs.content[0].top_logprobs) == 2


@pytest.mark.asyncio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_logprobs() -> None:
    response = await generate_with_logprobs(
        "vllm/EleutherAI/pythia-70m",
        chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
    )
    assert (
        response.choices[0].logprobs
        and response.choices[0].logprobs.content[0].top_logprobs is not None
    )
    assert len(response.choices[0].logprobs.content[0].top_logprobs) == 2


@pytest.mark.asyncio
@skip_if_github_action
@skip_if_no_llama_cpp_python
async def test_llama_cpp_python_logprobs() -> None:
    response = await generate_with_logprobs("llama-cpp-python/default")
    assert (
        response.choices[0].logprobs
        and response.choices[0].logprobs.content[0].top_logprobs is not None
    )
    assert len(response.choices[0].logprobs.content[0].top_logprobs) == 2
