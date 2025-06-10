from unittest.mock import patch

import pytest
from pydantic import ValidationError

from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._web_search._web_search import (
    Providers,
    _create_external_provider,
    _normalize_config,
    web_search,
)


class TestNormalizeConfig:
    """Tests for the _normalize_config function in _web_search.py."""

    @pytest.mark.parametrize(
        "providers,expected_result",
        [
            # Single str
            ("google", {"google": {}}),
            ("tavily", {"tavily": {}}),
            ("openai", {"openai": {}}),
            # Single str[]
            (["google"], {"google": {}}),
            (["tavily"], {"tavily": {}}),
            (["openai"], {"openai": {}}),
            # Multiple str[]
            (["google", "tavily"], {"google": {}, "tavily": {}}),
            # Single dict
            ({"tavily": True}, {"tavily": {}}),
            ({"tavily": {"max_results": 5}}, {"tavily": {"max_results": 5}}),
            ({"tavily": None}, {"tavily": {}}),
            ({"tavily": {"max_results": 5}}, {"tavily": {"max_results": 5}}),
            # Single dict[]
            ([{"tavily": None}], {"tavily": {}}),
            ([{"tavily": {"max_results": 5}}], {"tavily": {"max_results": 5}}),
            # Multi dict[]
            (
                [{"tavily": {"max_results": 5}}, {"google": {}}],
                {"tavily": {"max_results": 5}, "google": {}},
            ),
            # Mixed string and dict[]
            (
                ["google", {"tavily": {"max_results": 5}}],
                {"google": {}, "tavily": {"max_results": 5}},
            ),
            # Complex combination
            (
                ["google", {"tavily": None}, {"openai": {"model": "gpt-4o"}}],
                {"google": {}, "tavily": {}, "openai": {"model": "gpt-4o"}},
            ),
        ],
    )
    def test_normalize_config_providers(self, providers, expected_result) -> None:
        """Test _normalize_config with various provider configurations."""
        result = _normalize_config(providers)
        assert result == expected_result

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
        providers_dict: Providers = {"google": {}}
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
    """Tests for the old signature variants of web_search function."""

    # web_search(model=web_search_model, num_results=1)
    @patch("inspect_ai.tool._tools._web_search._web_search.deprecation_warning")
    def test_bug_report_cse(self, mock_warning):
        assert ToolDef(web_search(model="NA", num_results=1)).options == {
            "google": {"model": "NA", "num_results": 1}
        }

    @patch("inspect_ai.tool._tools._web_search._web_search.deprecation_warning")
    def test_no_parameters(self, mock_warning):
        assert ToolDef(web_search()).options == {"google": {}}

    @patch("inspect_ai.tool._tools._web_search._web_search.deprecation_warning")
    def test_only_provider_parameter(self, mock_warning):
        assert ToolDef(web_search(provider="google")).options == {"google": {}}
        assert ToolDef(web_search(provider="tavily")).options == {"tavily": {}}

    @patch("inspect_ai.tool._tools._web_search._web_search.deprecation_warning")
    def test_provider_with_num_results(self, mock_warning):
        assert ToolDef(web_search(provider="google", num_results=10)).options == {
            "google": {"num_results": 10}
        }
        assert ToolDef(web_search(provider="tavily", num_results=10)).options == {
            "tavily": {"max_results": 10}
        }

    @patch("inspect_ai.tool._tools._web_search._web_search.deprecation_warning")
    def test_num_results_only(self, mock_warning):
        assert ToolDef(web_search(num_results=10)).options == {
            "google": {"num_results": 10}
        }

    @patch("inspect_ai.tool._tools._web_search._web_search.deprecation_warning")
    def test_provider_with_multiple_parameters(self, mock_warning):
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
        with pytest.raises(ValueError, match=r"`provider` is deprecated"):
            web_search(["google"], provider="tavily")
