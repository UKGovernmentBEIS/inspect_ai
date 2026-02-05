import pytest
from test_helpers.utils import skip_if_no_perplexity

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
from inspect_ai.model._providers.perplexity import PerplexityAPI
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
        return output, call

    provider = PerplexityAPI(
        model_name="perplexity/sonar",
        api_key="sk-test",
        base_url="https://api.perplexity.ai",
    )

    monkeypatch.setattr(OpenAICompatibleAPI, "generate", fake_generate)

    provider.on_response(sample_response)

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
