from typing import Any, Literal
from unittest.mock import patch

import pytest
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai._util.content import ContentToolUse
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._providers.anthropic import (
    AnthropicAPI,
    _supports_web_search,
    _web_search_tool_params,
)
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo


class TestAnthropicWebSearch:
    def test_web_search_tool_param_returns_tool_param_for_empty_options(self):
        assert _web_search_tool_params({}) == [
            {"name": "web_fetch", "type": "web_fetch_20250910"},
            {
                "name": "web_search",
                "type": "web_search_20250305",
            },
        ]

    def test_web_search_tool_param_returns_tool_param_for_none_options(self):
        assert _web_search_tool_params(None) == [
            {"name": "web_fetch", "type": "web_fetch_20250910"},
            {
                "name": "web_search",
                "type": "web_search_20250305",
            },
        ]

    def test_web_search_tool_raises_type_error(self):
        with pytest.raises(TypeError):
            _web_search_tool_params("not a dict")

    def test_web_search_tool_with_options(self):
        options = {"max_uses": 666}

        result = _web_search_tool_params(options)

        assert result == [
            {"name": "web_fetch", "type": "web_fetch_20250910", "max_uses": 666},
            {"name": "web_search", "type": "web_search_20250305", "max_uses": 666},
        ]

    def test_web_search_tool_with_filtering(self):
        # no allowed_callers, so Anthropic's own default applies
        assert _web_search_tool_params({}, web_search_filtering=True) == [
            {"name": "web_fetch", "type": "web_fetch_20260209"},
            {"name": "web_search", "type": "web_search_20260209"},
        ]

    def test_web_search_tool_with_filtering_and_options(self):
        options = {"max_uses": 666, "allowed_domains": ["nhl.com"]}

        result = _web_search_tool_params(options, web_search_filtering=True)

        assert result == [
            {
                "name": "web_fetch",
                "type": "web_fetch_20260209",
                "max_uses": 666,
                "allowed_domains": ["nhl.com"],
            },
            {
                "name": "web_search",
                "type": "web_search_20260209",
                "max_uses": 666,
                "allowed_domains": ["nhl.com"],
            },
        ]

    def test_web_search_tool_allowed_callers_passthrough(self):
        # an explicit caller list is sent on both versions
        options = {"allowed_callers": ["direct"]}

        assert _web_search_tool_params(options, web_search_filtering=True) == [
            {
                "name": "web_fetch",
                "type": "web_fetch_20260209",
                "allowed_callers": ["direct"],
            },
            {
                "name": "web_search",
                "type": "web_search_20260209",
                "allowed_callers": ["direct"],
            },
        ]
        assert _web_search_tool_params(options) == [
            {
                "name": "web_fetch",
                "type": "web_fetch_20250910",
                "allowed_callers": ["direct"],
            },
            {
                "name": "web_search",
                "type": "web_search_20250305",
                "allowed_callers": ["direct"],
            },
        ]

    @pytest.mark.parametrize("web_search_filtering", [False, True])
    def test_web_search_tool_explicit_legacy_type(self, web_search_filtering: bool):
        options = {"type": "web_search_20250305", "max_uses": 8}

        assert _web_search_tool_params(options, web_search_filtering) == [
            {"name": "web_fetch", "type": "web_fetch_20250910", "max_uses": 8},
            {"name": "web_search", "type": "web_search_20250305", "max_uses": 8},
        ]

    @pytest.mark.parametrize("web_search_filtering", [False, True])
    def test_web_search_tool_explicit_filtering_type(self, web_search_filtering: bool):
        options = {"type": "web_search_20260209"}

        assert _web_search_tool_params(options, web_search_filtering) == [
            {"name": "web_fetch", "type": "web_fetch_20260209"},
            {"name": "web_search", "type": "web_search_20260209"},
        ]

    def test_web_search_tool_unsupported_type_raises(self):
        with pytest.raises(ValueError, match="web_search_20990101"):
            _web_search_tool_params({"type": "web_search_20990101"})


class TestForcedWebSearch:
    """A forced tool choice naming web_search must be callable directly."""

    @staticmethod
    async def _request_tools(
        model_name: str,
        tool_choice: ToolChoice,
        anthropic_options: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        api = AnthropicAPI(model_name=model_name, api_key="test-key")
        captured: dict[str, Any] = {}

        async def fake_perform(
            request: dict[str, Any], *args: Any, **kwargs: Any
        ) -> tuple[dict[str, Any], ModelOutput]:
            captured.update(request)
            return {}, ModelOutput.from_content(
                model=api.service_model_name(), content="ok"
            )

        with patch.object(api, "_perform_request_and_continuations", fake_perform):
            await api.generate(
                input=[ChatMessageUser(content="Search for the news.")],
                tools=[
                    ToolInfo(
                        name="web_search",
                        description="Search the web",
                        options={"anthropic": anthropic_options or {}},
                    )
                ],
                tool_choice=tool_choice,
                config=GenerateConfig(max_tokens=64),
            )
        return list(captured["tools"])

    @staticmethod
    def _by_name(tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {tool["name"]: tool for tool in tools}

    @pytest.mark.anyio
    @pytest.mark.parametrize("model_name", ["claude-sonnet-4-6", "claude-opus-5"])
    async def test_forced_search_allows_direct_calls(self, model_name: str):
        tools = self._by_name(
            await self._request_tools(model_name, ToolFunction(name="web_search"))
        )
        assert tools["web_search"]["type"] == "web_search_20260209"
        assert tools["web_search"]["allowed_callers"] == [
            "direct",
            "code_execution_20260120",
        ]
        # only the forced tool needs a direct caller
        assert "allowed_callers" not in tools["web_fetch"]

    @pytest.mark.anyio
    @pytest.mark.parametrize("tool_choice", ["auto", "any"])
    async def test_unforced_search_keeps_anthropic_default(
        self, tool_choice: ToolChoice
    ):
        tools = await self._request_tools("claude-sonnet-4-6", tool_choice)
        assert [tool["type"] for tool in tools] == [
            "web_fetch_20260209",
            "web_search_20260209",
        ]
        assert all("allowed_callers" not in tool for tool in tools)

    @pytest.mark.anyio
    async def test_forced_search_honors_explicit_callers(self):
        tools = self._by_name(
            await self._request_tools(
                "claude-sonnet-4-6",
                ToolFunction(name="web_search"),
                {"allowed_callers": ["code_execution_20260120"]},
            )
        )
        assert tools["web_search"]["allowed_callers"] == ["code_execution_20260120"]

    @pytest.mark.anyio
    async def test_forced_legacy_search_unchanged(self):
        # web_search_20250305 already allows direct calls by default
        tools = await self._request_tools(
            "claude-sonnet-4-5", ToolFunction(name="web_search")
        )
        assert all("allowed_callers" not in tool for tool in tools)

    @pytest.mark.anyio
    async def test_degraded_forced_choice_keeps_anthropic_default(self):
        # forced tool choice is sent as auto on Opus 5.5, so no direct caller is
        # needed
        tools = await self._request_tools(
            "claude-opus-5-5", ToolFunction(name="web_search")
        )
        assert all("allowed_callers" not in tool for tool in tools)


class TestWebSearchFilteringGate:
    """Gating for web search dynamic filtering.

    Dynamic filtering is enabled for frontier models (Claude 4.6 and later)
    but not on Vertex or Bedrock.
    """

    WEB_SEARCH_TOOL = ToolInfo(
        name="web_search", description="Search the web", options={"anthropic": {}}
    )

    def _api(self, model_name: str, service: str | None = None) -> AnthropicAPI:
        api = AnthropicAPI(model_name=model_name, api_key="test-key")
        if service is not None:
            api.service = service
        return api

    def _tool_types(self, api: AnthropicAPI) -> list[str] | None:
        params = api.web_search_tool_params(self.WEB_SEARCH_TOOL)
        return [str(p["type"]) for p in params] if params is not None else None

    @pytest.mark.parametrize(
        "model_name",
        [
            "claude-sonnet-4-6",
            "claude-opus-4-7",
            "claude-opus-4-8",
            "claude-fable-5",
        ],
    )
    def test_filtering_enabled_for_frontier_models(self, model_name: str):
        assert self._tool_types(self._api(model_name)) == [
            "web_fetch_20260209",
            "web_search_20260209",
        ]

    @pytest.mark.parametrize(
        "model_name",
        ["claude-sonnet-4-5", "claude-opus-4-1"],
    )
    def test_filtering_disabled_for_non_frontier_models(self, model_name: str):
        assert self._tool_types(self._api(model_name)) == [
            "web_fetch_20250910",
            "web_search_20250305",
        ]

    @pytest.mark.parametrize("service", ["vertex", "bedrock"])
    def test_filtering_disabled_on_vertex_and_bedrock(self, service: str):
        assert self._tool_types(self._api("claude-opus-4-8", service)) == [
            "web_fetch_20250910",
            "web_search_20250305",
        ]

    def test_no_params_without_anthropic_option(self):
        tool = ToolInfo(name="web_search", description="Search the web")
        assert self._api("claude-opus-4-8").web_search_tool_params(tool) is None


class TestSupportsWebSearch:
    """Test the _supports_web_search function to ensure it correctly identifies models that support web search."""

    # Table of test cases: (model_name, expected_result, description)
    test_cases = [
        # Supported Claude Opus 4 models
        ("claude-opus-4", True, "base claude-opus-4"),
        ("claude-opus-4-latest", True, "claude-opus-4 latest"),
        ("claude-opus-4-20250120", True, "claude-opus-4 dated"),
        ("claude-opus-4-beta", True, "claude-opus-4 beta"),
        ("claude-opus-4-experimental", True, "claude-opus-4 experimental"),
        # Supported Claude Sonnet 4 models
        ("claude-sonnet-4", True, "base claude-sonnet-4"),
        ("claude-sonnet-4-latest", True, "claude-sonnet-4 latest"),
        ("claude-sonnet-4-20250120", True, "claude-sonnet-4 dated"),
        ("claude-sonnet-4-beta", True, "claude-sonnet-4 beta"),
        ("claude-sonnet-4-experimental", True, "claude-sonnet-4 experimental"),
        # Supported Claude 3.7 Sonnet models
        ("claude-3-7-sonnet", True, "base claude-3-7-sonnet"),
        ("claude-3-7-sonnet-latest", True, "claude-3-7-sonnet latest"),
        ("claude-3-7-sonnet-20241022", True, "claude-3-7-sonnet dated"),
        ("claude-3-7-sonnet-beta", True, "claude-3-7-sonnet beta"),
        ("claude-3-7-sonnet-experimental", True, "claude-3-7-sonnet experimental"),
        # Supported specific latest models
        ("claude-3-5-sonnet-latest", True, "claude-3-5-sonnet-latest"),
        ("claude-3-5-haiku-latest", True, "claude-3-5-haiku-latest"),
        # Unsupported older Claude 3 models
        ("claude-3-opus", False, "claude-3-opus"),
        ("claude-3-sonnet", False, "claude-3-sonnet"),
        ("claude-3-haiku", False, "claude-3-haiku"),
        ("claude-3-opus-20240229", False, "claude-3-opus dated"),
        ("claude-3-sonnet-20240229", False, "claude-3-sonnet dated"),
        ("claude-3-haiku-20240307", False, "claude-3-haiku dated"),
        ("claude-3-5-sonnet", False, "claude-3-5-sonnet (not latest)"),
        ("claude-3-5-sonnet-20240620", False, "claude-3-5-sonnet dated"),
        ("claude-3-5-sonnet-20241022", False, "claude-3-5-sonnet another date"),
        ("claude-3-5-haiku", False, "claude-3-5-haiku (not latest)"),
        ("claude-3-5-haiku-20241022", False, "claude-3-5-haiku dated"),
        # Unsupported Claude 2 models
        ("claude-2", False, "claude-2"),
        ("claude-2.0", False, "claude-2.0"),
        ("claude-2.1", False, "claude-2.1"),
        ("claude-instant-1.2", False, "claude-instant-1.2"),
        # Unsupported invalid/unrecognized models
        ("", False, "empty string"),
        ("gpt-4", False, "gpt-4"),
        ("claude", False, "claude only"),
        ("claude-invalid", False, "claude-invalid"),
        ("claude-3", False, "claude-3 only"),
        ("claude-4", False, "claude-4 without variant"),
        ("claude-5-sonnet", False, "non-existent claude-5"),
        ("not-a-model", False, "random string"),
        ("claude-3-6-sonnet", False, "non-existent claude-3-6"),
        # Case sensitivity tests
        ("Claude-opus-4", False, "Claude-opus-4 (wrong case)"),
        ("CLAUDE-OPUS-4", False, "CLAUDE-OPUS-4 (all caps)"),
        ("Claude-3-7-Sonnet", False, "Claude-3-7-Sonnet (mixed case)"),
        ("CLAUDE-3-5-SONNET-LATEST", False, "CLAUDE-3-5-SONNET-LATEST (all caps)"),
        # Edge cases that should not be supported
        (" claude-3-sonnet ", False, "claude-3-sonnet with spaces (unsupported base)"),
        ("claude-3-5-sonnet ", False, "claude-3-5-sonnet with space (not latest)"),
        ("   ", False, "only whitespace"),
    ]

    @pytest.mark.parametrize("model_name,expected,description", test_cases)
    def test_supports_web_search(
        self, model_name: str, expected: bool, description: str
    ):
        """Table-driven test for _supports_web_search function."""
        result = _supports_web_search(model_name)
        assert result == expected, (
            f"Model '{model_name}' ({description}): expected {expected}, got {result}"
        )


async def _live_web_search(
    model_name: str,
    tool_choice: ToolChoice,
    anthropic_options: dict[str, Any] | None = None,
    config: GenerateConfig = GenerateConfig(),
) -> tuple[ModelOutput, dict[str, Any]]:
    """Generate against the live API, returning the output and the request."""
    api = AnthropicAPI(model_name=model_name)
    output, model_call = await api.generate(
        input=[
            ChatMessageUser(
                content="What movie won best picture at the 2025 Oscars? "
                "Search the web, then answer in one sentence."
            )
        ],
        tools=[
            ToolInfo(
                name="web_search",
                description="Search the web",
                options={"anthropic": anthropic_options or {}},
            )
        ],
        tool_choice=tool_choice,
        config=config.merge(GenerateConfig(max_tokens=4096)),
    )
    assert isinstance(output, ModelOutput)
    assert output.error is None
    return output, model_call.request


def _server_tool_types(output: ModelOutput) -> set[str]:
    content = output.message.content
    return {
        c.tool_type
        for c in (content if isinstance(content, list) else [])
        if isinstance(c, ContentToolUse)
    }


@pytest.mark.anyio
@skip_if_no_anthropic
@pytest.mark.parametrize("model_name", ["claude-sonnet-4-6", "claude-opus-5"])
@pytest.mark.parametrize("reasoning_effort", [None, "high"])
async def test_forced_web_search_live(
    model_name: str, reasoning_effort: Literal["high"] | None
) -> None:
    output, request = await _live_web_search(
        model_name,
        ToolFunction(name="web_search"),
        config=GenerateConfig(reasoning_effort=reasoning_effort),
    )
    # reasoning_effort selects adaptive thinking, which keeps the forced choice
    if reasoning_effort is not None:
        assert request["thinking"]["type"] == "adaptive"
    assert request["tool_choice"] == {"type": "tool", "name": "web_search"}
    search = next(t for t in request["tools"] if t["name"] == "web_search")
    assert search["type"] == "web_search_20260209"
    assert "direct" in search["allowed_callers"]
    assert "web_search" in _server_tool_types(output)


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_automatic_web_search_filtering_live() -> None:
    output, request = await _live_web_search("claude-sonnet-4-6", "auto")
    assert all("allowed_callers" not in t for t in request["tools"])
    assert _server_tool_types(output)


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_explicit_allowed_callers_live() -> None:
    output, request = await _live_web_search(
        "claude-sonnet-4-6", "auto", {"allowed_callers": ["direct"]}
    )
    assert all(t["allowed_callers"] == ["direct"] for t in request["tools"])
    assert "web_search" in _server_tool_types(output)
