from contextlib import nullcontext
from typing import Any

import anyio
import anyio.lowlevel
import httpx2
import pytest
from openai import BadRequestError
from openai.types.chat import ChatCompletion
from test_helpers.utils import skip_if_no_perplexity

from inspect_ai._util._async import tg_collect
from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentText
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    ModelCall,
    ModelOutput,
    get_model,
)
from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI
from inspect_ai.model._providers.perplexity import PerplexityAPI, _response
from inspect_ai.tool._tool_info import ToolInfo


@pytest.mark.anyio
@skip_if_no_perplexity
async def test_perplexity_api() -> None:
    model = get_model(
        "perplexity/sonar",
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=50,
            presence_penalty=0.0,
            seed=None,
            temperature=0.0,
            top_p=1.0,
            extra_body={
                "search_mode": "academic",
                "web_search_options": {"search_context_size": "low"},
            },
        ),
    )

    message = ChatMessageUser(content="What is Python programming language?")
    response = await model.generate(input=[message])

    # Validate basic response structure
    assert len(response.completion) >= 1
    # The API returns model name without provider prefix
    assert response.model == "sonar"

    # Validate usage information is present
    assert response.usage is not None
    assert response.usage.input_tokens > 0
    assert response.usage.output_tokens > 0
    assert response.usage.total_tokens > 0

    # Validate Perplexity-specific usage metrics
    if (
        hasattr(response.usage, "reasoning_tokens")
        and response.usage.reasoning_tokens is not None
    ):
        assert response.usage.reasoning_tokens >= 0

    # Validate metadata contains Perplexity-specific fields
    assert response.metadata is not None
    if "search_context_size" in response.metadata:
        context_size = response.metadata["search_context_size"]
        # Since we explicitly requested "low", verify it matches
        assert context_size == "low"
    if "citation_tokens" in response.metadata:
        citation_tokens = response.metadata["citation_tokens"]
        assert citation_tokens >= 0
    if "num_search_queries" in response.metadata:
        search_queries = response.metadata["num_search_queries"]
        assert search_queries >= 0

    # Check if citations are present
    choice = response.choices[0]
    if hasattr(choice.message, "content") and isinstance(choice.message.content, list):
        for part in choice.message.content:
            if (
                isinstance(part, ContentText)
                and hasattr(part, "citations")
                and part.citations
            ):
                # If citations exist, validate they are UrlCitation objects
                for citation in part.citations:
                    assert isinstance(citation, UrlCitation)
                    assert citation.url.startswith(("http://", "https://"))


@pytest.mark.anyio
async def test_perplexity_citation_mapping(monkeypatch) -> None:
    # Complete sample response based on Perplexity API documentation
    # Source: https://docs.perplexity.ai/api-reference/chat-completions-post
    sample_response = {
        "id": "test-completion-id",
        "model": "perplexity/sonar",
        "created": 1234567890,
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"content": "Test response content", "role": "assistant"},
            }
        ],
        "citations": ["https://example.com"],
        "search_results": [
            {"title": "Example", "url": "https://example.com", "date": "2023-12-25"}
        ],
        "usage": {
            "prompt_tokens": 2,
            "completion_tokens": 3,
            "total_tokens": 5,
            "search_context_size": "low",
            "citation_tokens": 1,
            "num_search_queries": 1,
            "reasoning_tokens": 1,
        },
    }

    output = ModelOutput(
        model="perplexity/sonar",
        choices=[ChatCompletionChoice(message=ChatMessageAssistant(content="hello"))],
    )
    call = ModelCall.create({}, {})

    async def fake_generate(self, input, tools, tool_choice, config):
        self.on_response(sample_response)
        return output, call

    provider = PerplexityAPI(
        model_name="perplexity/sonar",
        api_key="sk-test",
        base_url="https://api.perplexity.ai",
    )

    monkeypatch.setattr(OpenAICompatibleAPI, "generate", fake_generate)

    result, _ = await provider.generate([], [], "none", GenerateConfig())

    assert isinstance(result, ModelOutput)
    assert isinstance(result.choices[0].message.content, list)
    part = result.choices[0].message.content[0]
    assert isinstance(part, ContentText)
    assert part.citations is not None
    assert isinstance(part.citations[0], UrlCitation)
    assert part.citations[0].url == "https://example.com"
    assert result.usage is not None
    assert result.usage.input_tokens == 2
    assert result.usage.reasoning_tokens == 1
    assert result.metadata is not None
    assert result.metadata["search_context_size"] == "low"


@pytest.mark.anyio
async def test_perplexity_web_search_options(monkeypatch) -> None:
    captured = {}

    async def fake_generate(self, input, tools, tool_choice, config):
        captured["tools"] = tools
        captured["config"] = config
        return (
            ModelOutput(model="perplexity/sonar", choices=[]),
            ModelCall.create({}, {}),
        )

    provider = PerplexityAPI(model_name="perplexity/sonar", api_key="sk-test")
    monkeypatch.setattr(OpenAICompatibleAPI, "generate", fake_generate)

    tool = ToolInfo(
        name="web_search",
        description="",
        options={
            "perplexity": {
                "search_mode": "academic",
                "web_search_options": {"search_context_size": "low"},
            }
        },
    )
    await provider.generate([], [tool], "none", GenerateConfig())

    assert captured["tools"] == []
    assert captured["config"].extra_body == {
        "search_mode": "academic",
        "web_search_options": {"search_context_size": "low"},
    }


def _search_completion(name: str, tokens: int) -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": f"completion-{name}",
            "model": "sonar",
            "created": 1234567890,
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"content": f"answer {name}", "role": "assistant"},
                }
            ],
            "search_results": [
                {"title": name, "url": f"https://example.com/{name}"},
            ],
            "usage": {
                "prompt_tokens": tokens,
                "completion_tokens": tokens,
                "total_tokens": 2 * tokens,
                "reasoning_tokens": tokens,
                "num_search_queries": tokens,
            },
        }
    )


def _citation_urls(output: ModelOutput) -> list[str]:
    content = output.choices[0].message.content
    if isinstance(content, str):
        return []
    return [
        citation.url
        for part in content
        if isinstance(part, ContentText)
        for citation in part.citations or []
        if isinstance(citation, UrlCitation)
    ]


@pytest.mark.anyio
async def test_perplexity_concurrent_generate_uses_own_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = PerplexityAPI(model_name="perplexity/sonar", api_key="sk-test")
    completions = {"a": _search_completion("a", 1), "b": _search_completion("b", 2)}

    # call "a" receives its response first, then waits before post-processing
    # it until call "b" has received its own response
    a_received = anyio.Event()
    b_received = anyio.Event()

    async def fake_create(**kwargs: Any) -> ChatCompletion:
        name = kwargs["messages"][0]["content"]
        if name == "b":
            await a_received.wait()
        return completions[name]

    monkeypatch.setattr(provider.client.chat.completions, "create", fake_create)

    base_generate = OpenAICompatibleAPI.generate

    async def ordered_generate(
        self: OpenAICompatibleAPI,
        input: list[Any],
        tools: list[ToolInfo],
        tool_choice: Any,
        config: GenerateConfig,
    ) -> Any:
        result = await base_generate(self, input, tools, tool_choice, config)
        if input[0].text == "a":
            a_received.set()
            await b_received.wait()
        else:
            b_received.set()
        return result

    monkeypatch.setattr(OpenAICompatibleAPI, "generate", ordered_generate)

    async def generate(name: str) -> ModelOutput:
        output, _ = await provider.generate(
            [ChatMessageUser(content=name)], [], "none", GenerateConfig()
        )
        assert isinstance(output, ModelOutput)
        return output

    try:
        output_a, output_b = await tg_collect(
            [lambda: generate("a"), lambda: generate("b")]
        )
    finally:
        await provider.aclose()

    for output, name, tokens in [(output_a, "a", 1), (output_b, "b", 2)]:
        assert output.completion == f"answer {name}"
        assert _citation_urls(output) == [f"https://example.com/{name}"]
        assert output.usage is not None
        assert output.usage.input_tokens == tokens
        assert output.usage.reasoning_tokens == tokens
        assert output.metadata is not None
        assert output.metadata["num_search_queries"] == tokens
        assert output.metadata["search_results"][0]["title"] == name


@pytest.mark.anyio
async def test_perplexity_failed_generate_ignores_earlier_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = PerplexityAPI(model_name="perplexity/sonar", api_key="sk-test")
    request = httpx2.Request("POST", "https://api.perplexity.ai/chat/completions")
    responses: list[ChatCompletion | Exception] = [
        _search_completion("a", 1),
        BadRequestError(
            "Error code: 400 - input length exceeds the context window",
            response=httpx2.Response(400, request=request),
            body=None,
        ),
    ]

    async def fake_create(**kwargs: Any) -> ChatCompletion:
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(provider.client.chat.completions, "create", fake_create)

    try:
        first, _ = await provider.generate(
            [ChatMessageUser(content="a")], [], "none", GenerateConfig()
        )
        assert isinstance(first, ModelOutput)
        assert _citation_urls(first) == ["https://example.com/a"]

        failed, call = await provider.generate(
            [ChatMessageUser(content="b")], [], "none", GenerateConfig()
        )
    finally:
        await provider.aclose()

    assert call.error is True
    assert isinstance(failed, ModelOutput)
    assert failed.stop_reason == "model_length"
    assert _citation_urls(failed) == []
    assert failed.usage is None
    assert not failed.metadata


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_perplexity_escaped_failure_restores_response(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    provider = PerplexityAPI(model_name="perplexity/sonar", api_key="sk-test")
    failed_response = _search_completion("failed", 1).model_dump()
    enclosing_response = _search_completion("enclosing", 2).model_dump()
    fail_generate = True

    async def fake_generate(
        self: OpenAICompatibleAPI,
        input: list[Any],
        tools: list[ToolInfo],
        tool_choice: Any,
        config: GenerateConfig,
    ) -> Any:
        if not fail_generate:
            return (
                ModelOutput.from_content("perplexity/sonar", "later"),
                ModelCall.create({}, {}),
            )
        self.on_response(failed_response)
        if failure == "cancel":
            scope.cancel()
            await anyio.sleep_forever()
        await anyio.lowlevel.checkpoint()
        raise RuntimeError("request failed")

    monkeypatch.setattr(OpenAICompatibleAPI, "generate", fake_generate)

    token = _response.set(enclosing_response)
    try:
        with anyio.CancelScope() as scope:
            with pytest.raises(RuntimeError) if failure == "error" else nullcontext():
                await provider.generate([], [], "none", GenerateConfig())
        assert scope.cancelled_caught == (failure == "cancel")
        assert _response.get() is enclosing_response

        fail_generate = False
        later, _ = await provider.generate([], [], "none", GenerateConfig())
    finally:
        _response.reset(token)
        await provider.aclose()

    assert isinstance(later, ModelOutput)
    assert _citation_urls(later) == []
    assert later.usage is None
    assert not later.metadata
