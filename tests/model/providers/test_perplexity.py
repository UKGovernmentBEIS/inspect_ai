from typing import Any

import anyio
import pytest
from openai._models import construct_type
from openai.types.responses import Response
from test_helpers.utils import skip_if_no_perplexity

from inspect_ai._util._async import tg_collect
from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentText
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.model._providers.perplexity import PerplexityAPI
from inspect_ai.tool import web_search
from inspect_ai.tool._tool_info import ToolInfo


@pytest.mark.anyio
@skip_if_no_perplexity
async def test_perplexity_api() -> None:
    model = get_model(
        "perplexity/sonar",
        config=GenerateConfig(max_tokens=300, temperature=0.0),
    )

    message = ChatMessageUser(
        content="What was NVIDIA's closing stock price on October 2, 2026? Answer in one sentence."
    )
    response = await model.generate(
        input=[message],
        tools=[web_search({"perplexity": {"search_context_size": "low"}})],
    )

    assert len(response.completion) >= 1
    assert response.model == "perplexity/sonar"

    assert response.usage is not None
    assert response.usage.input_tokens > 0
    assert response.usage.output_tokens > 0
    assert response.usage.total_tokens > 0

    # the search results are kept and attached as citations
    assert response.metadata is not None
    assert len(response.metadata["search_results"]) > 0
    content = response.choices[0].message.content
    assert isinstance(content, list)
    citations = [
        citation
        for part in content
        if isinstance(part, ContentText)
        for citation in part.citations or []
    ]
    assert len(citations) > 0
    for citation in citations:
        assert isinstance(citation, UrlCitation)
        assert citation.url.startswith(("http://", "https://"))


def _agent_response(name: str, tokens: int, cache_creation: int = 0) -> Response:
    """An Agent API response, parsed as the OpenAI SDK parses it."""
    response = construct_type(
        type_=Response,
        value={
            "id": f"resp_{name}",
            "created_at": 1791230228,
            "model": "perplexity/sonar",
            "object": "response",
            "status": "completed",
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [{"type": "web_search"}],
            "output": [
                {
                    "type": "search_results",
                    "queries": [f"query {name}"],
                    "results": [
                        {
                            "id": 1,
                            "title": name,
                            "url": f"https://example.com/{name}",
                            "snippet": "snippet",
                            "date": "2026-10-02",
                            "source": "web",
                        }
                    ],
                },
                {
                    "type": "message",
                    "id": f"msg_{name}",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": f"answer {name}",
                            "annotations": [],
                        }
                    ],
                },
            ],
            "usage": {
                "input_tokens": tokens + cache_creation,
                "input_tokens_details": {
                    "cached_tokens": 0,
                    "cache_creation_input_tokens": cache_creation,
                    "cache_read_input_tokens": 0,
                },
                "output_tokens": tokens,
                "output_tokens_details": {"reasoning_tokens": 1},
                "total_tokens": 2 * tokens + cache_creation,
                "cost": {"currency": "USD", "total_cost": 0.001},
            },
        },
    )
    assert isinstance(response, Response)
    return response


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


def _provider(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, Response],
    requests: list[dict[str, Any]] | None = None,
    model_name: str = "sonar",
) -> PerplexityAPI:
    provider = PerplexityAPI(model_name=model_name, api_key="sk-test")

    async def fake_create(**kwargs: Any) -> Response:
        if requests is not None:
            requests.append(kwargs)
        # deep copy so that each call gets a response of its own
        return responses[kwargs["input"][0]["content"][0]["text"]].model_copy(deep=True)

    monkeypatch.setattr(provider.client.responses, "create", fake_create)
    return provider


@pytest.mark.anyio
async def test_perplexity_agent_api_response(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, Any]] = []
    provider = _provider(
        monkeypatch, {"a": _agent_response("a", 2, cache_creation=5)}, requests
    )

    try:
        output, call = await provider.generate(
            [ChatMessageUser(content="a")], [], "none", GenerateConfig()
        )
    finally:
        await provider.aclose()

    assert provider.base_url == "https://api.perplexity.ai/v1"
    assert requests[0]["model"] == "perplexity/sonar"
    assert requests[0]["extra_body"] == {"tools": [{"type": "web_search"}]}

    assert isinstance(output, ModelOutput)
    assert output.completion == "answer a"
    assert _citation_urls(output) == ["https://example.com/a"]
    assert output.metadata is not None
    assert output.metadata["search_results"][0]["title"] == "a"

    # cache writes are counted apart from uncached input tokens
    assert output.usage is not None
    assert output.usage.input_tokens == 2
    assert output.usage.input_tokens_cache_write == 5
    assert output.usage.output_tokens == 2
    assert output.usage.reasoning_tokens == 1

    # the logged response keeps the search results
    assert call.response is not None
    logged_output = call.response["output"]
    assert isinstance(logged_output, list)
    search_item = logged_output[0]
    assert isinstance(search_item, dict)
    assert search_item["type"] == "search_results"
    assert search_item["queries"] == ["query a"]


@pytest.mark.anyio
async def test_perplexity_web_search_options_and_extra_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []
    provider = _provider(monkeypatch, {"a": _agent_response("a", 1)}, requests)

    tool = ToolInfo(
        name="web_search",
        description="",
        options={
            "perplexity": {
                "search_context_size": "low",
                "filters": {"search_domain_filter": ["example.com"]},
            }
        },
    )
    try:
        await provider.generate(
            [ChatMessageUser(content="a")],
            [tool],
            "none",
            GenerateConfig(extra_body={"max_steps": 3, "store": True}),
        )
    finally:
        await provider.aclose()

    request = requests[0]
    # Agent API fields pass through; Responses fields are set on the request
    assert request["extra_body"] == {
        "max_steps": 3,
        "tools": [
            {
                "type": "web_search",
                "search_context_size": "low",
                "filters": {"search_domain_filter": ["example.com"]},
            }
        ],
    }
    assert request["store"] is True


@pytest.mark.anyio
async def test_perplexity_rejects_unsupported_tools_and_options() -> None:
    provider = PerplexityAPI(model_name="sonar", api_key="sk-test")
    try:
        with pytest.raises(ValueError, match="web_search"):
            await provider.generate(
                [ChatMessageUser(content="a")],
                [ToolInfo(name="other", description="")],
                "auto",
                GenerateConfig(),
            )
        with pytest.raises(ValueError, match="search_mode"):
            await provider.generate(
                [ChatMessageUser(content="a")],
                [
                    ToolInfo(
                        name="web_search",
                        description="",
                        options={"perplexity": {"search_mode": "academic"}},
                    )
                ],
                "auto",
                GenerateConfig(),
            )
        with pytest.raises(TypeError, match="perplexity_options"):
            await provider.generate(
                [ChatMessageUser(content="a")],
                [
                    ToolInfo(
                        name="web_search",
                        description="",
                        options={"perplexity": "low"},
                    )
                ],
                "auto",
                GenerateConfig(),
            )
    finally:
        await provider.aclose()


@pytest.mark.parametrize(
    "model_name,expected",
    [
        ("sonar", "perplexity/sonar"),
        ("perplexity/sonar", "perplexity/sonar"),
        ("openai/gpt-5.6-luna", "openai/gpt-5.6-luna"),
    ],
)
def test_perplexity_agent_model_name(model_name: str, expected: str) -> None:
    provider = PerplexityAPI(model_name=model_name, api_key="sk-test")
    assert provider.service_model_name() == expected


@pytest.mark.parametrize(
    "model_name", ["sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"]
)
def test_perplexity_retired_sonar_model(model_name: str) -> None:
    with pytest.raises(ValueError, match="retired"):
        PerplexityAPI(model_name=model_name, api_key="sk-test")


@pytest.mark.anyio
async def test_perplexity_concurrent_generate_uses_own_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = PerplexityAPI(model_name="sonar", api_key="sk-test")
    responses = {"a": _agent_response("a", 1), "b": _agent_response("b", 2)}

    # call "a" waits for its response until call "b" has received its own
    b_received = anyio.Event()

    async def fake_create(**kwargs: Any) -> Response:
        name = kwargs["input"][0]["content"][0]["text"]
        if name == "a":
            await b_received.wait()
        else:
            b_received.set()
        return responses[name]

    monkeypatch.setattr(provider.client.responses, "create", fake_create)

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
        assert output.metadata is not None
        assert output.metadata["search_results"][0]["title"] == name
