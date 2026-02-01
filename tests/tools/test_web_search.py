from unittest.mock import patch

import pytest
from pydantic import ValidationError

from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._web_search._web_search import (
    EXTERNAL_PROVIDERS,
    WebSearchProviders,
    _create_external_provider,
    _has_external_provider,
    _normalize_config,
    _NormalizedProviders,
    web_search,
)

# All internal providers enabled with default options
ALL_INTERNAL_PROVIDERS: _NormalizedProviders = {
    "openai": {},
    "anthropic": {},
    "grok": {},
    "gemini": {},
    "mistral": {},
    "perplexity": {},
}


class TestNormalizeConfig:
    """Tests for the _normalize_config function in _web_search.py."""

    @pytest.mark.parametrize(
        "providers,expected_result",
        [
            # External providers only - returns only what's specified
            ("google", {"google": {}}),
            ("tavily", {"tavily": {}}),
            ("exa", {"exa": {}}),
            (["google"], {"google": {}}),
            (["tavily"], {"tavily": {}}),
            (["google", "tavily"], {"google": {}, "tavily": {}}),
            # External provider with options
            ({"tavily": True}, {"tavily": {}}),
            ({"tavily": {"max_results": 5}}, {"tavily": {"max_results": 5}}),
            ({"tavily": None}, {"tavily": {}}),
            ([{"tavily": None}], {"tavily": {}}),
            ([{"tavily": {"max_results": 5}}], {"tavily": {"max_results": 5}}),
            # Multiple external providers
            (
                [{"tavily": {"max_results": 5}}, {"google": {}}],
                {"tavily": {"max_results": 5}, "google": {}},
            ),
            (
                ["google", {"tavily": {"max_results": 5}}],
                {"google": {}, "tavily": {"max_results": 5}},
            ),
            # Mixed external and internal - only specified providers returned
            (
                ["google", {"tavily": None}, {"openai": {"model": "gpt-4o"}}],
                {"google": {}, "tavily": {}, "openai": {"model": "gpt-4o"}},
            ),
            (
                ["openai", "tavily"],
                {"openai": {}, "tavily": {}},
            ),
        ],
    )
    def test_normalize_config_with_external_providers(
        self, providers, expected_result
    ) -> None:
        """Test _normalize_config when external providers are specified.

        When at least one external provider is specified, internal providers
        are disabled by default and only specified providers are returned.
        """
        result = _normalize_config(providers)
        assert result == expected_result

    @pytest.mark.parametrize(
        "providers,expected_result",
        [
            # Internal provider only - all internal providers enabled by default
            ("openai", ALL_INTERNAL_PROVIDERS),
            ("anthropic", ALL_INTERNAL_PROVIDERS),
            (["openai"], ALL_INTERNAL_PROVIDERS),
            (["openai", "anthropic"], ALL_INTERNAL_PROVIDERS),
            # Internal provider with options - merges with defaults
            (
                {"openai": {"model": "gpt-4o"}},
                {**ALL_INTERNAL_PROVIDERS, "openai": {"model": "gpt-4o"}},
            ),
            (
                [{"openai": {"model": "gpt-4o"}}, "anthropic"],
                {**ALL_INTERNAL_PROVIDERS, "openai": {"model": "gpt-4o"}},
            ),
        ],
    )
    def test_normalize_config_with_internal_only(
        self, providers, expected_result
    ) -> None:
        """Test _normalize_config when only internal providers are specified.

        When no external provider is specified, all internal providers are
        enabled by default. Specifying an internal provider allows setting
        options for it while keeping all others enabled.
        """
        result = _normalize_config(providers)
        assert result == expected_result

    def test_normalize_config_no_providers(self) -> None:
        """Test _normalize_config with no providers specified.

        When no providers are specified, all internal providers are enabled.
        """
        result = _normalize_config(None)
        assert result == ALL_INTERNAL_PROVIDERS

    def test_normalize_config_disable_with_false(self) -> None:
        """Test using False to disable specific internal providers."""
        # Disable one internal provider
        result = _normalize_config({"openai": False})
        expected = {k: v for k, v in ALL_INTERNAL_PROVIDERS.items() if k != "openai"}
        assert result == expected

        # Disable multiple internal providers
        result = _normalize_config([{"openai": False}, {"anthropic": False}])
        expected = {
            k: v
            for k, v in ALL_INTERNAL_PROVIDERS.items()
            if k not in ("openai", "anthropic")
        }
        assert result == expected

    def test_normalize_config_false_with_external_provider(self) -> None:
        """Test using False with external providers."""
        # External provider with False for another - False has no effect since
        # internal providers are already disabled by default
        result = _normalize_config(["tavily", {"openai": False}])
        assert result == {"tavily": {}}

        # Explicitly enable one internal, disable another (with external)
        result = _normalize_config(["tavily", "openai", {"anthropic": False}])
        assert result == {"tavily": {}, "openai": {}}

    @pytest.mark.parametrize(
        "deprecated_provider,deprecated_args,expected_result",
        [
            # Basic deprecated providers
            ("google", {}, {"google": {}}),
            ("tavily", {}, {"tavily": {}}),
            # Google with various deprecated args
            ("google", {"num_results": 5}, {"google": {"num_results": 5}}),
            (
                "google",
                {"max_provider_calls": 3},
                {"google": {"max_provider_calls": 3}},
            ),
            ("google", {"max_connections": 10}, {"google": {"max_connections": 10}}),
            ("google", {"model": "gpt-4o"}, {"google": {"model": "gpt-4o"}}),
            # Google with multiple deprecated args
            (
                "google",
                {"num_results": 5, "max_provider_calls": 3, "model": "gpt-4o"},
                {
                    "google": {
                        "num_results": 5,
                        "max_provider_calls": 3,
                        "model": "gpt-4o",
                    }
                },
            ),
            # Tavily with various deprecated args
            ("tavily", {"num_results": 5}, {"tavily": {"max_results": 5}}),
            ("tavily", {"max_connections": 10}, {"tavily": {"max_connections": 10}}),
            # Tavily with multiple deprecated args
            (
                "tavily",
                {"num_results": 5, "max_connections": 10},
                {"tavily": {"max_results": 5, "max_connections": 10}},
            ),
        ],
    )
    def test_normalize_config_deprecated_args(
        self, deprecated_provider, deprecated_args, expected_result
    ) -> None:
        """Test _normalize_config with deprecated arguments."""
        all_args = {"provider": deprecated_provider, **deprecated_args}

        # Mock the deprecation warning to avoid cluttering test output
        with patch(
            "inspect_ai.tool._tools._web_search._web_search.deprecation_warning"
        ):
            result = _normalize_config(None, **all_args)
            assert result == expected_result

    def test_both_provider_and_providers_error(self) -> None:
        """Test that using both provider and providers raises an error."""
        with pytest.raises(ValueError, match=r"`provider` is deprecated"):
            _normalize_config(["google"], provider="tavily")

    def test_invalid_provider_in_list(self) -> None:
        """Test handling of invalid provider names."""
        with pytest.raises(ValueError, match=r"Invalid provider: 'invalid_provider'"):
            _normalize_config(["invalid_provider"])  # type: ignore

    def test_direct_providers_dict(self) -> None:
        """Test passing a Providers dict directly."""
        # Copy the dict to avoid modification
        providers_dict: WebSearchProviders = {"google": {}}
        result = _normalize_config(providers_dict)
        assert result == providers_dict

    @patch("inspect_ai.tool._tools._web_search._web_search._get_config_via_back_compat")
    def test_google_options_creation(self, mock_get_config_via_back_compat) -> None:
        """Test that the deprecated provider flow calls _get_config_via_back_compat."""
        # Set up the mock to return a predictable value
        mock_get_config_via_back_compat.return_value = {"google": {"num_results": 5}}

        result = _normalize_config(None, provider="google", num_results=5)

        # Check _get_config_via_back_compat was called with correct parameters
        mock_get_config_via_back_compat.assert_called_once_with(
            "google",
            num_results=5,
            max_provider_calls=None,
            max_connections=None,
            model=None,
        )
        assert result == {"google": {"num_results": 5}}


class TestHasExternalProvider:
    """Tests for the _has_external_provider helper function."""

    def test_external_providers_constant(self) -> None:
        """Verify the EXTERNAL_PROVIDERS constant contains expected values."""
        assert set(EXTERNAL_PROVIDERS) == {"tavily", "google", "exa"}

    @pytest.mark.parametrize(
        "providers,expected",
        [
            # Empty list - no external providers
            ([], False),
            # Internal providers only
            (["openai"], False),
            (["anthropic"], False),
            (["openai", "anthropic", "gemini"], False),
            # External providers
            (["tavily"], True),
            (["google"], True),
            (["exa"], True),
            # Mixed
            (["openai", "tavily"], True),
            (["anthropic", "google", "gemini"], True),
            # Dict format - external
            ([{"tavily": {}}], True),
            ([{"google": {"num_results": 5}}], True),
            # Dict format - internal
            ([{"openai": {}}], False),
            ([{"anthropic": {"model": "claude"}}], False),
            # Dict format - False should not count as external
            ([{"tavily": False}], False),
            ([{"google": False}], False),
            # Mixed dict and string
            (["openai", {"tavily": {}}], True),
            ([{"openai": {}}, "google"], True),
            # External set to False with internal - still no external
            ([{"tavily": False}, "openai"], False),
        ],
    )
    def test_has_external_provider(self, providers, expected) -> None:
        """Test _has_external_provider with various inputs."""
        assert _has_external_provider(providers) == expected


class TestCreateExternalProvider:
    @patch(
        "os.environ.get",
        side_effect=lambda key, default=None: "fake-key"
        if key == "TAVILY_API_KEY"
        else default,
    )
    def test_tavily_provider_with_normal_config(self, mock_environ_get) -> None:
        assert callable(_create_external_provider({"tavily": {"max_results": 5}}))

    @patch(
        "os.environ.get",
        side_effect=lambda key, default=None: "fake-key"
        if key == "TAVILY_API_KEY"
        else default,
    )
    def test_tavily_provider_with_none(self, mock_environ_get) -> None:
        assert callable(_create_external_provider({"tavily": {}}))

    @patch(
        "os.environ.get",
        side_effect=lambda key, default=None: "fake-key"
        if key == "TAVILY_API_KEY"
        else default,
    )
    def test_tavily_provider_with_bogus_config(self, mock_environ_get) -> None:
        with pytest.raises(ValidationError):
            _create_external_provider({"tavily": {"max_results": "bogus"}})

    @patch(
        "inspect_ai.tool._tools._web_search._google.maybe_get_google_api_keys",
        return_value=("fake-key", "fake-cse-id"),
    )
    def test_google_provider_with_normal_config(self, mock_google_api_keys) -> None:
        assert callable(_create_external_provider({"google": {"max_results": 5}}))

    @patch(
        "inspect_ai.tool._tools._web_search._google.maybe_get_google_api_keys",
        return_value=("fake-key", "fake-cse-id"),
    )
    def test_google_provider_with_none(self, mock_google_api_keys) -> None:
        assert callable(_create_external_provider({"google": {}}))

    @patch(
        "os.environ.get",
        side_effect=lambda key, default=None: "fake-key"
        if key == "EXA_API_KEY"
        else default,
    )
    def test_exa_provider_with_normal_config(self, mock_environ_get) -> None:
        assert callable(_create_external_provider({"exa": {"text": True}}))

    @patch(
        "os.environ.get",
        side_effect=lambda key, default=None: "fake-key"
        if key == "EXA_API_KEY"
        else default,
    )
    def test_exa_provider_with_none(self, mock_environ_get) -> None:
        assert callable(_create_external_provider({"exa": {}}))

    @patch(
        "os.environ.get",
        side_effect=lambda key, default=None: "fake-key"
        if key == "EXA_API_KEY"
        else default,
    )
    def test_exa_provider_with_bogus_config(self, mock_environ_get) -> None:
        with pytest.raises(ValidationError):
            _create_external_provider({"exa": {"text": "bogus"}})


class TestOldSignatureVariants:
    """Tests for the old signature variants of web_search function.

    These tests verify backwards compatibility for the deprecated web_search
    signature that used `provider`, `num_results`, etc. parameters.

    When deprecated parameters are used without an explicit provider, the code
    falls back to Google CSE only if the Google environment variables are set.
    """

    @patch(
        "inspect_ai.tool._tools._web_search._web_search.maybe_get_google_api_keys",
        return_value=("fake-key", "fake-cse-id"),
    )
    @patch("inspect_ai.tool._tools._web_search._web_search.deprecation_warning")
    def test_bug_report_cse(self, mock_warning, mock_google_keys):
        """Test deprecated params without provider falls back to Google when env vars set."""
        assert ToolDef(web_search(model="NA", num_results=1)).options == {
            "google": {"model": "NA", "num_results": 1}
        }

    def test_no_parameters(self):
        """Test web_search() with no parameters returns all internal providers."""
        assert ToolDef(web_search()).options == ALL_INTERNAL_PROVIDERS

    @patch("inspect_ai.tool._tools._web_search._web_search.deprecation_warning")
    def test_only_provider_parameter(self, mock_warning):
        """Test deprecated provider parameter works."""
        assert ToolDef(web_search(provider="google")).options == {"google": {}}
        assert ToolDef(web_search(provider="tavily")).options == {"tavily": {}}

    @patch("inspect_ai.tool._tools._web_search._web_search.deprecation_warning")
    def test_provider_with_num_results(self, mock_warning):
        """Test deprecated provider + num_results parameters."""
        assert ToolDef(web_search(provider="google", num_results=10)).options == {
            "google": {"num_results": 10}
        }
        assert ToolDef(web_search(provider="tavily", num_results=10)).options == {
            "tavily": {"max_results": 10}
        }

    @patch(
        "inspect_ai.tool._tools._web_search._web_search.maybe_get_google_api_keys",
        return_value=("fake-key", "fake-cse-id"),
    )
    @patch("inspect_ai.tool._tools._web_search._web_search.deprecation_warning")
    def test_num_results_only(self, mock_warning, mock_google_keys):
        """Test deprecated num_results without provider falls back to Google when env vars set."""
        assert ToolDef(web_search(num_results=10)).options == {
            "google": {"num_results": 10}
        }

    def test_deprecated_params_without_google_env_vars(self):
        """Test deprecated params without provider and without Google env vars.

        When deprecated parameters like num_results are used without a provider,
        and Google CSE environment variables are not set, the deprecated params
        are ignored and all internal providers are returned.
        """
        # Ensure Google env vars are not set for this test
        with patch(
            "inspect_ai.tool._tools._web_search._web_search.maybe_get_google_api_keys",
            return_value=None,
        ):
            # num_results is ignored, returns all internal providers
            assert ToolDef(web_search(num_results=10)).options == ALL_INTERNAL_PROVIDERS

    @patch("inspect_ai.tool._tools._web_search._web_search.deprecation_warning")
    def test_provider_with_multiple_parameters(self, mock_warning):
        """Test deprecated provider with multiple deprecated parameters."""
        assert ToolDef(
            web_search(
                provider="google",
                num_results=10,
                max_provider_calls=5,
                max_connections=15,
                model="gpt-4o",
            )
        ).options == {
            "google": {
                "num_results": 10,
                "max_provider_calls": 5,
                "max_connections": 15,
                "model": "gpt-4o",
            }
        }

        assert ToolDef(
            web_search(provider="tavily", num_results=10, max_connections=15)
        ).options == {"tavily": {"max_results": 10, "max_connections": 15}}

    def test_conflict_between_old_and_new_signatures(self):
        """Test that using both provider and providers raises an error."""
        with pytest.raises(ValueError, match=r"`provider` is deprecated"):
            web_search(["google"], provider="tavily")
