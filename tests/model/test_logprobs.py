import math

import pytest
from test_helpers.utils import (
    skip_if_github_action,
    skip_if_no_accelerate,
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
            logprobs=True,
            top_logprobs=2,
            temperature=0.001,
            max_tokens=50,
            max_retries=0,
        ),
        **model_kwargs,
    )

    message = ChatMessageUser(content="Hello.")
    return await model.generate(input=[message])


@skip_if_no_openai
async def test_openai_logprobs() -> None:
    response = await generate_with_logprobs("openai/gpt-3.5-turbo")
    assert response.choices[0].logprobs is not None
    assert response.choices[0].logprobs.content[0].top_logprobs is not None
    assert len(response.choices[0].logprobs.content[0].top_logprobs) == 2


@skip_if_no_openai
async def test_openai_responses_logprobs() -> None:
    response = await generate_with_logprobs("openai/gpt-4o-mini", responses_api=True)
    assert response.choices[0].logprobs is not None
    assert response.choices[0].logprobs.content[0].top_logprobs is not None
    assert len(response.choices[0].logprobs.content[0].top_logprobs) == 2


@pytest.mark.anyio
@skip_if_no_together
async def test_together_logprobs() -> None:
    response = await generate_with_logprobs("together/MiniMaxAI/MiniMax-M2.7")
    assert response.choices[0].logprobs is not None
    top_logprobs = response.choices[0].logprobs.content[0].top_logprobs
    assert top_logprobs is not None
    assert len(top_logprobs) == 1


@skip_if_no_together
async def test_together_logprobs_openai_format() -> None:
    response = await generate_with_logprobs("together/openai/gpt-oss-20b")
    assert response.choices[0].logprobs is not None
    top_logprobs = response.choices[0].logprobs.content[0].top_logprobs
    assert top_logprobs is not None
    assert len(top_logprobs) == 1


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_llama_cpp_python
async def test_llama_cpp_python_logprobs() -> None:
    response = await generate_with_logprobs("llama-cpp-python/default")
    assert (
        response.choices[0].logprobs
        and response.choices[0].logprobs.content[0].top_logprobs is not None
    )
    assert len(response.choices[0].logprobs.content[0].top_logprobs) == 2


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_prompt_logprobs() -> None:
    model = get_model(
        "vllm/EleutherAI/pythia-70m",
        config=GenerateConfig(max_tokens=1, prompt_logprobs=1),
        chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
    )
    message = ChatMessageUser(content="The quick brown fox")
    response = await model.generate(input=[message])

    choice = response.choices[0]
    assert choice.prompt_logprobs is not None
    assert len(choice.prompt_logprobs.content) > 0
    for lp in choice.prompt_logprobs.content:
        assert isinstance(lp.token, str)
        assert len(lp.token) > 0
        assert math.isfinite(lp.logprob)
        assert lp.logprob <= 0.0


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_prompt_logprobs_not_returned_when_not_requested() -> None:
    model = get_model(
        "vllm/EleutherAI/pythia-70m",
        config=GenerateConfig(max_tokens=1),
        chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
    )
    message = ChatMessageUser(content="Hello world")
    response = await model.generate(input=[message])

    assert response.choices[0].prompt_logprobs is None
