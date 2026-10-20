import uuid
from typing import Any, AsyncIterator

import anyio
import pytest
from openai._models import construct_type
from openai._types import NOT_GIVEN
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseStreamEvent,
)
from test_helpers.utils import skip_if_no_perplexity

from inspect_ai._util._async import tg_collect
from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentText
from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.model._providers.perplexity import PerplexityAPI
from inspect_ai.model._stream import ModelStreamObserver, model_stream_observer
from inspect_ai.tool import ToolChoice, ToolFunction, web_search
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
        tools=[
            web_search(
                {
                    "perplexity": {
                        "search_type": "fast",
                        "max_tokens": 2000,
                        "max_tokens_per_page": 500,
                    }
                }
            )
        ],
        tool_choice="any",
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
    assert response.metadata["num_search_queries"] >= 1
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


def _snippet_lengths(output: ModelOutput) -> list[int]:
    assert output.metadata is not None
    return [len(r.get("snippet", "")) for r in output.metadata["search_results"]]


@pytest.mark.anyio
@skip_if_no_perplexity
async def test_perplexity_search_token_budgets() -> None:
    model = get_model("perplexity/sonar", config=GenerateConfig(max_tokens=150))
    message = ChatMessageUser(
        content="What are the main provisions of the EU AI Act? Answer in one sentence."
    )

    async def search(max_tokens: int, max_tokens_per_page: int) -> list[int]:
        output = await model.generate(
            input=[message],
            tools=[
                web_search(
                    {
                        "perplexity": {
                            "max_tokens": max_tokens,
                            "max_tokens_per_page": max_tokens_per_page,
                        }
                    }
                )
            ],
            tool_choice="any",
        )
        return _snippet_lengths(output)

    small = await search(500, 100)
    large = await search(8000, 2000)

    # the budgets bound the search content returned
    assert len(small) > 0 and len(large) > 0
    assert max(small) < 1000
    assert sum(small) < sum(large)


@pytest.mark.anyio
@skip_if_no_perplexity
async def test_perplexity_api_without_web_search() -> None:
    model = get_model("perplexity/sonar", config=GenerateConfig(max_tokens=50))

    response = await model.generate(
        input=[ChatMessageUser(content="Reply with the single word OK.")]
    )

    assert len(response.completion) >= 1
    assert response.usage is not None
    assert response.usage.output_tokens > 0
    # no web_search() tool, so no search
    assert "search_results" not in (response.metadata or {})
    assert "num_search_queries" not in (response.metadata or {})


@pytest.mark.anyio
@skip_if_no_perplexity
@pytest.mark.parametrize("tool_choice", ["any", ToolFunction(name="web_search")])
@pytest.mark.parametrize("extra_body", [None, {"tools": [{"type": "fetch_url"}]}])
async def test_perplexity_forced_web_search(
    tool_choice: ToolChoice, extra_body: dict[str, Any] | None
) -> None:
    model = get_model(
        "perplexity/sonar",
        config=GenerateConfig(max_tokens=50, extra_body=extra_body),
    )

    # a prompt the model answers without searching unless forced to; with
    # fetch_url attached too, the forced choice must still be search
    response = await model.generate(
        input=[ChatMessageUser(content="Reply with the single word OK.")],
        tools=[web_search({"perplexity": True})],
        tool_choice=tool_choice,
    )

    assert response.metadata is not None
    assert response.metadata["search_results"]


@pytest.mark.anyio
@skip_if_no_perplexity
async def test_perplexity_prompt_cache() -> None:
    model = get_model("perplexity/sonar", config=GenerateConfig(max_tokens=50))

    # a long prefix unique to this run, so that the first call writes the
    # cache and the second reads it
    run_id = uuid.uuid4().hex
    prefix = " ".join(
        f"Rule {i}: the orchard at site {i} grows apples for run {run_id}."
        for i in range(300)
    )
    input: list[ChatMessage] = [
        ChatMessageSystem(content=prefix),
        ChatMessageUser(content="Reply with the single word OK."),
    ]
    config = GenerateConfig(extra_body={"prompt_cache_key": f"inspect-{run_id}"})

    write = await model.generate(input, config=config)
    read = await model.generate(input, config=config)

    assert write.usage is not None
    assert write.usage.input_tokens_cache_write is not None
    assert write.usage.input_tokens_cache_write > 0
    assert write.usage.input_tokens_cache_read is None

    assert read.usage is not None
    assert read.usage.input_tokens_cache_read is not None
    assert read.usage.input_tokens_cache_read > 0
    assert read.usage.input_tokens_cache_write is None

    # both calls send the same input, split differently
    for usage in [write.usage, read.usage]:
        assert usage.input_tokens < 100
    assert write.usage.input_tokens + write.usage.input_tokens_cache_write == (
        read.usage.input_tokens + read.usage.input_tokens_cache_read
    )


@pytest.mark.anyio
@skip_if_no_perplexity
async def test_perplexity_fetch_url() -> None:
    model = get_model(
        "perplexity/sonar",
        config=GenerateConfig(
            max_tokens=200,
            extra_body={
                "tools": [{"type": "fetch_url"}],
                "tool_choice": {"type": "fetch_url"},
            },
        ),
    )

    response = await model.generate(
        input=[
            ChatMessageUser(
                content="Use the fetch_url tool to retrieve https://example.com "
                "and describe that page in one sentence. Do not use web_search."
            )
        ],
        tools=[web_search({"perplexity": True})],
    )

    assert len(response.completion) >= 1
    assert response.metadata is not None
    fetched = [r["url"] for r in response.metadata["fetch_url_results"]]
    assert any("example.com" in url for url in fetched)
    assert any("example.com" in url for url in _citation_urls(response))


def _agent_response_value(
    name: str,
    tokens: int,
    cache_creation: int = 0,
    cache_read: int = 0,
    annotations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """An Agent API response body."""
    return {
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
                        "annotations": annotations or [],
                    }
                ],
            },
        ],
        "usage": {
            "input_tokens": tokens + cache_creation + cache_read,
            "input_tokens_details": {
                "cached_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            },
            "output_tokens": tokens,
            "output_tokens_details": {"reasoning_tokens": 1},
            "total_tokens": 2 * tokens + cache_creation + cache_read,
            "cost": {"currency": "USD", "total_cost": 0.001},
            "tool_calls_details": {"search_web": {"cost_usd": 0.0025, "invocation": 1}},
        },
    }


def _agent_response(
    name: str,
    tokens: int,
    cache_creation: int = 0,
    cache_read: int = 0,
    annotations: list[dict[str, Any]] | None = None,
) -> Response:
    """An Agent API response, parsed as the OpenAI SDK parses it."""
    response = construct_type(
        type_=Response,
        value=_agent_response_value(
            name, tokens, cache_creation, cache_read, annotations
        ),
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


def _web_search_tool(perplexity: dict[str, Any] | bool) -> ToolInfo:
    return ToolInfo(
        name="web_search", description="", options={"perplexity": perplexity}
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "model_name,agent_model",
    [("sonar", "perplexity/sonar"), ("openai/gpt-5.6-luna", "openai/gpt-5.6-luna")],
)
async def test_perplexity_web_search_only_when_requested(
    monkeypatch: pytest.MonkeyPatch, model_name: str, agent_model: str
) -> None:
    requests: list[dict[str, Any]] = []
    provider = _provider(
        monkeypatch, {"a": _agent_response("a", 1)}, requests, model_name=model_name
    )

    try:
        await provider.generate(
            [ChatMessageUser(content="a")], [], "none", GenerateConfig()
        )
        await provider.generate(
            [ChatMessageUser(content="a")],
            [_web_search_tool(True)],
            "auto",
            GenerateConfig(),
        )
    finally:
        await provider.aclose()

    without_search, with_search = requests
    assert without_search["model"] == agent_model
    assert without_search["tools"] is NOT_GIVEN
    assert "extra_body" not in without_search
    assert with_search["model"] == agent_model
    assert with_search["extra_body"] == {"tools": [{"type": "web_search"}]}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool_choice,expected",
    [
        ("auto", None),
        ("none", None),
        ("any", {"type": "web_search"}),
        (ToolFunction(name="web_search"), {"type": "web_search"}),
    ],
)
async def test_perplexity_tool_choice(
    monkeypatch: pytest.MonkeyPatch, tool_choice: ToolChoice, expected: Any
) -> None:
    model = get_model("perplexity/sonar", api_key="sk-test", memoize=False)
    requests: list[dict[str, Any]] = []

    async def fake_create(**kwargs: Any) -> Response:
        requests.append(kwargs)
        return _agent_response("a", 1)

    assert isinstance(model.api, PerplexityAPI)
    monkeypatch.setattr(model.api.client.responses, "create", fake_create)
    try:
        await model.generate(
            [ChatMessageUser(content="a")],
            tools=[web_search({"perplexity": True})],
            tool_choice=tool_choice,
        )
    finally:
        await model.api.aclose()

    extra_body = requests[0].get("extra_body", {})
    # the generate_responses helper sends no tool choice of its own
    assert requests[0]["tool_choice"] is NOT_GIVEN
    assert extra_body.get("tool_choice") == expected
    # "none" removes the web_search tool before the provider sees it
    assert ("tools" in extra_body) == (tool_choice != "none")


@pytest.mark.anyio
@pytest.mark.parametrize("tool_choice", ["auto", "none"])
async def test_perplexity_extra_body_tool_choice(
    monkeypatch: pytest.MonkeyPatch, tool_choice: ToolChoice
) -> None:
    # Inspect's tool_choice governs Inspect's tools; tools passed in
    # extra_body follow extra_body["tool_choice"] (decision: Ransom, 2026-10-15)
    model = get_model("perplexity/sonar", api_key="sk-test", memoize=False)
    requests: list[dict[str, Any]] = []

    async def fake_create(**kwargs: Any) -> Response:
        requests.append(kwargs)
        return _agent_response("a", 1)

    assert isinstance(model.api, PerplexityAPI)
    monkeypatch.setattr(model.api.client.responses, "create", fake_create)
    fetch_url = {"type": "fetch_url"}
    try:
        await model.generate(
            [ChatMessageUser(content="a")],
            tool_choice=tool_choice,
            config=GenerateConfig(
                extra_body={"tools": [fetch_url], "tool_choice": "none"}
            ),
        )
    finally:
        await model.api.aclose()

    assert requests[0]["tool_choice"] is NOT_GIVEN
    assert requests[0]["extra_body"] == {"tools": [fetch_url], "tool_choice": "none"}


@pytest.mark.anyio
@pytest.mark.parametrize("tool_choice", ["any", ToolFunction(name="web_search")])
async def test_perplexity_forced_search_conflicts_with_extra_body_tool_choice(
    monkeypatch: pytest.MonkeyPatch, tool_choice: ToolChoice
) -> None:
    model = get_model("perplexity/sonar", api_key="sk-test", memoize=False)
    requests: list[dict[str, Any]] = []

    async def fake_create(**kwargs: Any) -> Response:
        requests.append(kwargs)
        return _agent_response("a", 1)

    assert isinstance(model.api, PerplexityAPI)
    monkeypatch.setattr(model.api.client.responses, "create", fake_create)
    try:
        with pytest.raises(ValueError, match="conflicts with tool_choice 'none'"):
            await model.generate(
                [ChatMessageUser(content="a")],
                tools=[web_search({"perplexity": True})],
                tool_choice=tool_choice,
                config=GenerateConfig(
                    extra_body={"tools": [{"type": "fetch_url"}], "tool_choice": "none"}
                ),
            )
    finally:
        await model.api.aclose()

    assert requests == []


@pytest.mark.anyio
async def test_perplexity_agent_api_response(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, Any]] = []
    provider = _provider(
        monkeypatch, {"a": _agent_response("a", 2, cache_creation=5)}, requests
    )

    try:
        output, call = await provider.generate(
            [ChatMessageUser(content="a")],
            [_web_search_tool({})],
            "none",
            GenerateConfig(),
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
    assert output.metadata["num_search_queries"] == 1

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
async def test_perplexity_without_search_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a request without the web_search tool has no tool_calls_details
    value = _agent_response_value("a", 2)
    del value["usage"]["tool_calls_details"]
    response = construct_type(type_=Response, value=value)
    assert isinstance(response, Response)
    provider = _provider(monkeypatch, {"a": response})

    try:
        output, _ = await provider.generate(
            [ChatMessageUser(content="a")], [], "none", GenerateConfig()
        )
    finally:
        await provider.aclose()

    assert isinstance(output, ModelOutput)
    assert "num_search_queries" not in (output.metadata or {})


@pytest.mark.anyio
async def test_perplexity_cache_read_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch, {"a": _agent_response("a", 2, cache_read=7)})

    try:
        output, _ = await provider.generate(
            [ChatMessageUser(content="a")], [], "none", GenerateConfig()
        )
    finally:
        await provider.aclose()

    assert isinstance(output, ModelOutput)
    assert output.usage is not None
    assert output.usage.input_tokens == 2
    assert output.usage.input_tokens_cache_read == 7
    assert output.usage.input_tokens_cache_write is None


@pytest.mark.anyio
@pytest.mark.parametrize("search_type", ["fast", "web"])
async def test_perplexity_web_search_options_and_extra_body(
    monkeypatch: pytest.MonkeyPatch, search_type: str
) -> None:
    requests: list[dict[str, Any]] = []
    provider = _provider(monkeypatch, {"a": _agent_response("a", 1)}, requests)

    tool = ToolInfo(
        name="web_search",
        description="",
        options={
            "perplexity": {
                "max_tokens": 2000,
                "max_tokens_per_page": 500,
                "search_type": search_type,
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
                "max_tokens": 2000,
                "max_tokens_per_page": 500,
                "search_type": search_type,
                "filters": {"search_domain_filter": ["example.com"]},
            }
        ],
    }
    assert request["store"] is True


@pytest.mark.anyio
async def test_perplexity_extra_body_keeps_request_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []
    provider = _provider(monkeypatch, {"a": _agent_response("a", 1)}, requests)

    try:
        await provider.generate(
            [ChatMessageUser(content="a")],
            [],
            "none",
            GenerateConfig(
                reasoning_effort="high",
                reasoning_summary="detailed",
                verbosity="low",
                max_tokens=100,
                extra_body={
                    "reasoning": {"effort": "low", "context": "all"},
                    "text": {"format": {"type": "text"}},
                    "include": ["web_search_call.results"],
                    "max_output_tokens": 5,
                    "stream": True,
                    "max_steps": 3,
                },
            ),
        )
    finally:
        await provider.aclose()

    request = requests[0]
    # fields the request reads or sets are not sent again to replace it
    assert request["extra_body"] == {"max_steps": 3}
    assert request["reasoning"] == {
        "effort": "high",
        "summary": "detailed",
        "context": "all",
    }
    assert request["text"] == {"verbosity": "low"}
    assert request["include"] == ["reasoning.encrypted_content"]
    assert request["max_output_tokens"] == 100
    assert "stream" not in request


@pytest.mark.anyio
async def test_perplexity_forced_search_with_extra_body_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = get_model("perplexity/sonar", api_key="sk-test", memoize=False)
    requests: list[dict[str, Any]] = []

    async def fake_create(**kwargs: Any) -> Response:
        requests.append(kwargs)
        return _agent_response("a", 1)

    assert isinstance(model.api, PerplexityAPI)
    monkeypatch.setattr(model.api.client.responses, "create", fake_create)
    fetch_url = {"type": "fetch_url"}
    try:
        await model.generate(
            [ChatMessageUser(content="a")],
            tools=[web_search({"perplexity": True})],
            tool_choice="any",
            config=GenerateConfig(extra_body={"tools": [fetch_url]}),
        )
        # the one tool choice in extra_body applies to web_search() as well
        await model.generate(
            [ChatMessageUser(content="a")],
            tools=[web_search({"perplexity": True})],
            tool_choice="auto",
            config=GenerateConfig(
                extra_body={"tools": [fetch_url], "tool_choice": "none"}
            ),
        )
    finally:
        await model.api.aclose()

    forced, raw_none = (request["extra_body"] for request in requests)
    # "required" could be met by fetch_url alone
    assert forced["tool_choice"] == {"type": "web_search"}
    assert raw_none == {
        "tools": [fetch_url, {"type": "web_search"}],
        "tool_choice": "none",
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "option,hint",
    [
        ("search_language_filter", None),
        ("reasoning_effort", "reasoning_effort generation config"),
        ("return_images", "image_search"),
        ("num_images", "image_search"),
        ("image_domain_filter", "image_search"),
        ("image_format_filter", "image_search"),
        ("return_videos", None),
        ("num_videos", None),
        ("media_response", None),
        ("return_related_questions", None),
        ("stream_mode", None),
    ],
)
async def test_perplexity_rejects_sonar_options(option: str, hint: str | None) -> None:
    provider = PerplexityAPI(model_name="sonar", api_key="sk-test")
    try:
        with pytest.raises(ValueError, match="Sonar parameters") as exc:
            await provider.generate(
                [ChatMessageUser(content="a")],
                [_web_search_tool({option: "x"})],
                "auto",
                GenerateConfig(),
            )
    finally:
        await provider.aclose()

    assert option in str(exc.value)
    if hint is not None:
        assert hint in str(exc.value)


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
        with pytest.raises(ValueError, match="max_tokens_per_page"):
            await provider.generate(
                [ChatMessageUser(content="a")],
                [
                    ToolInfo(
                        name="web_search",
                        description="",
                        options={"perplexity": {"search_context_size": "low"}},
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
    "model_name",
    [
        "sonar-pro",
        "sonar-reasoning-pro",
        "sonar-deep-research",
        "perplexity/sonar-pro",
        "perplexity/sonar-reasoning-pro",
        "perplexity/sonar-deep-research",
    ],
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


@pytest.mark.anyio
async def test_perplexity_web_search_with_extra_body_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []
    provider = _provider(monkeypatch, {"a": _agent_response("a", 1)}, requests)
    fetch_url = {"type": "fetch_url"}

    async def generate(tools: list[ToolInfo], extra_body: dict[str, Any]) -> None:
        await provider.generate(
            [ChatMessageUser(content="a")],
            tools,
            "auto",
            GenerateConfig(extra_body=extra_body),
        )

    try:
        # web_search() is added to the Agent API tools passed in extra_body
        await generate([_web_search_tool(True)], {"tools": [fetch_url]})
        assert requests[-1]["extra_body"]["tools"] == [
            fetch_url,
            {"type": "web_search"},
        ]

        # without web_search(), extra_body's tools pass through
        await generate([], {"tools": [fetch_url]})
        assert requests[-1]["extra_body"]["tools"] == [fetch_url]

        with pytest.raises(ValueError, match="already has a web_search tool"):
            await generate(
                [_web_search_tool(True)], {"tools": [{"type": "web_search"}]}
            )
        with pytest.raises(TypeError, match="extra_body"):
            await generate([_web_search_tool(True)], {"tools": fetch_url})
    finally:
        await provider.aclose()

    assert len(requests) == 2


@pytest.mark.anyio
async def test_perplexity_search_results_merge_with_annotations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    annotations = [
        {
            "type": "url_citation",
            "start_index": 0,
            "end_index": 6,
            "title": "cited a",
            "url": "https://example.com/a",
        },
        {
            "type": "url_citation",
            "start_index": 7,
            "end_index": 8,
            "title": "other",
            "url": "https://example.com/other",
        },
    ]
    provider = _provider(
        monkeypatch, {"a": _agent_response("a", 1, annotations=annotations)}
    )

    try:
        output, _ = await provider.generate(
            [ChatMessageUser(content="a")],
            [_web_search_tool(True)],
            "auto",
            GenerateConfig(),
        )
    finally:
        await provider.aclose()

    assert isinstance(output, ModelOutput)
    content = output.choices[0].message.content
    assert isinstance(content, list)
    # one text part: no empty part is added for the search results
    texts = [part for part in content if isinstance(part, ContentText)]
    assert [part.text for part in texts] == ["answer a"]
    # the annotations are kept, and the search result already cited is not
    # added again
    assert _citation_urls(output) == [
        "https://example.com/a",
        "https://example.com/other",
    ]
    citations = texts[0].citations
    assert citations is not None
    assert isinstance(citations[0], UrlCitation)
    assert citations[0].cited_text == (0, 6)


@pytest.mark.anyio
async def test_perplexity_search_results_go_to_last_text_part(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _agent_response_value("a", 1)
    value["output"][0]["results"].append(
        {"id": 2, "title": "b", "url": "https://example.com/b"}
    )
    message = value["output"][1]
    message["content"].append(
        {"type": "output_text", "text": "more", "annotations": []}
    )
    # a duplicate search result is cited once
    value["output"][0]["results"].append(
        {"id": 3, "title": "a again", "url": "https://example.com/a"}
    )
    response = construct_type(type_=Response, value=value)
    assert isinstance(response, Response)
    provider = _provider(monkeypatch, {"a": response})

    try:
        output, _ = await provider.generate(
            [ChatMessageUser(content="a")],
            [_web_search_tool(True)],
            "auto",
            GenerateConfig(),
        )
    finally:
        await provider.aclose()

    assert isinstance(output, ModelOutput)
    content = output.choices[0].message.content
    assert isinstance(content, list)
    first, last = [part for part in content if isinstance(part, ContentText)]
    assert first.citations is None or len(first.citations) == 0
    assert last.citations is not None
    assert [c.url for c in last.citations if isinstance(c, UrlCitation)] == [
        "https://example.com/a",
        "https://example.com/b",
    ]


class _FakeStream:
    def __init__(self, events: list[Any]) -> None:
        self.events = events
        self.closed = False

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.closed = True

    def __aiter__(self) -> AsyncIterator[Any]:
        async def events() -> AsyncIterator[Any]:
            for event in self.events:
                yield event

        return events()


@pytest.mark.anyio
async def test_perplexity_streamed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """An on_stream callback streams the request (the default)."""
    response = _agent_response_value("a", 2, cache_creation=5)
    # stream events, parsed as the OpenAI SDK parses them
    events = [
        construct_type(type_=ResponseStreamEvent, value=event)
        for event in [
            {
                "type": "response.created",
                "sequence_number": 0,
                "response": {**response, "status": "in_progress", "output": []},
            },
            {
                "type": "response.completed",
                "sequence_number": 1,
                "response": response,
            },
        ]
    ]
    assert isinstance(events[-1], ResponseCompletedEvent)
    stream = _FakeStream(events)
    requests: list[dict[str, Any]] = []

    async def fake_create(**kwargs: Any) -> _FakeStream:
        requests.append(kwargs)
        return stream

    provider = PerplexityAPI(model_name="sonar", api_key="sk-test")
    monkeypatch.setattr(provider.client.responses, "create", fake_create)

    async def on_stream(event: Any) -> None:
        pass

    try:
        with model_stream_observer(ModelStreamObserver("test", on_stream)):
            output, _ = await provider.generate(
                [ChatMessageUser(content="a")],
                [_web_search_tool(True)],
                "auto",
                GenerateConfig(),
            )
    finally:
        await provider.aclose()

    assert requests[0]["stream"] is True
    assert stream.closed
    assert isinstance(output, ModelOutput)
    assert output.completion == "answer a"
    assert _citation_urls(output) == ["https://example.com/a"]
    assert output.metadata is not None
    assert output.metadata["search_results"][0]["title"] == "a"
    # the search count comes from the terminal event
    assert output.metadata["num_search_queries"] == 1
    assert output.usage is not None
    assert output.usage.input_tokens == 2
    assert output.usage.input_tokens_cache_write == 5


@pytest.mark.anyio
async def test_perplexity_fetch_url_results(monkeypatch: pytest.MonkeyPatch) -> None:
    value = _agent_response_value("a", 1)
    value["output"].insert(
        1,
        {
            "type": "fetch_url_results",
            "contents": [
                {
                    "url": "https://example.com/fetched",
                    "title": "fetched",
                    "snippet": "page text",
                }
            ],
        },
    )
    response = construct_type(type_=Response, value=value)
    assert isinstance(response, Response)
    requests: list[dict[str, Any]] = []
    provider = _provider(monkeypatch, {"a": response}, requests)

    try:
        output, call = await provider.generate(
            [ChatMessageUser(content="a")],
            [_web_search_tool(True)],
            "auto",
            GenerateConfig(extra_body={"tools": [{"type": "fetch_url"}]}),
        )
    finally:
        await provider.aclose()

    assert requests[0]["extra_body"]["tools"] == [
        {"type": "fetch_url"},
        {"type": "web_search"},
    ]
    assert isinstance(output, ModelOutput)
    assert output.completion == "answer a"
    assert _citation_urls(output) == [
        "https://example.com/a",
        "https://example.com/fetched",
    ]
    assert output.metadata is not None
    assert output.metadata["search_results"][0]["title"] == "a"
    assert output.metadata["fetch_url_results"][0]["snippet"] == "page text"

    # the logged response keeps the fetched results
    assert call.response is not None
    logged_output = call.response["output"]
    assert isinstance(logged_output, list)
    fetch_item = logged_output[1]
    assert isinstance(fetch_item, dict)
    assert fetch_item["type"] == "fetch_url_results"


@pytest.mark.anyio
async def test_perplexity_rejects_unsupported_tool_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _agent_response_value("a", 1)
    value["output"].insert(
        1, {"type": "image_search_results", "results": [{"url": "https://x.com"}]}
    )
    response = construct_type(type_=Response, value=value)
    assert isinstance(response, Response)
    provider = _provider(monkeypatch, {"a": response})

    try:
        with pytest.raises(ValueError, match="image_search_results"):
            await provider.generate(
                [ChatMessageUser(content="a")],
                [_web_search_tool(True)],
                "auto",
                GenerateConfig(extra_body={"tools": [{"type": "image_search"}]}),
            )
    finally:
        await provider.aclose()
