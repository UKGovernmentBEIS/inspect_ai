"""Tests for code_execution tool."""

import pytest

from inspect_ai.tool._tools._code_execution import _normalize_config


def test_normalize_config_default_all_providers_enabled() -> None:
    """Test that None input enables all providers with empty dicts."""
    result = _normalize_config(None)

    assert "openai" in result
    assert "anthropic" in result
    assert "google" in result
    assert "grok" in result
    assert "bash" in result

    assert result["openai"] == {}
    assert result["anthropic"] == {}
    assert result["google"] == {}
    assert result["grok"] == {}
    assert result["bash"] == {}


def test_normalize_config_empty_dict_same_as_none() -> None:
    """Test that empty dict input is equivalent to None."""
    result = _normalize_config({})
    assert result == _normalize_config(None)


def test_normalize_config_disable_single_provider() -> None:
    """Test that False removes a provider from the result."""
    result = _normalize_config({"bash": False})

    assert "bash" not in result
    assert "openai" in result
    assert "anthropic" in result
    assert "google" in result
    assert "grok" in result


def test_normalize_config_disable_multiple_providers() -> None:
    """Test disabling multiple providers."""
    result = _normalize_config({"grok": False, "openai": False})

    assert "grok" not in result
    assert "openai" not in result
    assert "anthropic" in result
    assert "google" in result
    assert "bash" in result


def test_normalize_config_disable_all_providers() -> None:
    """Test disabling all providers results in empty dict."""
    result = _normalize_config(
        {
            "openai": False,
            "anthropic": False,
            "google": False,
            "grok": False,
            "bash": False,
        }
    )
    assert result == {}


def test_normalize_config_dict_options_for_openai() -> None:
    """Test providing dict options for openai."""
    options = {"memory_limit": "4g", "timeout": 300}
    result = _normalize_config({"openai": options})

    assert result["openai"] == options
    assert result["anthropic"] == {}
    assert result["google"] == {}
    assert result["grok"] == {}
    assert result["bash"] == {}


def test_normalize_config_dict_options_for_bash() -> None:
    """Test providing dict options for bash."""
    options = {"timeout": 60, "user": "sandbox"}
    result = _normalize_config({"bash": options})

    assert result["bash"] == options
    assert result["openai"] == {}


def test_normalize_config_true_leaves_provider_enabled() -> None:
    """Test that True keeps the provider enabled with empty dict."""
    result = _normalize_config({"openai": True, "anthropic": True})

    assert result["openai"] == {}
    assert result["anthropic"] == {}


def test_normalize_config_mixed_configuration() -> None:
    """Test mixed configuration with dict, True, and False values."""
    result = _normalize_config(
        {
            "openai": {"memory_limit": "8g"},
            "anthropic": True,
            "grok": False,
            "bash": {"timeout": 120},
        }
    )

    assert result["openai"] == {"memory_limit": "8g"}
    assert result["anthropic"] == {}
    assert "grok" not in result
    assert result["google"] == {}
    assert result["bash"] == {"timeout": 120}


def test_normalize_config_empty_dict_options() -> None:
    """Test that providing an empty dict keeps provider enabled."""
    result = _normalize_config({"openai": {}})

    assert result["openai"] == {}
    assert "openai" in result


@pytest.mark.parametrize("provider", ["openai", "anthropic", "google", "grok", "bash"])
def test_normalize_config_disable_each_provider(provider: str) -> None:
    """Test that each provider can be individually disabled."""
    result = _normalize_config({provider: False})  # type: ignore[arg-type, misc]

    assert provider not in result
    all_providers = {"openai", "anthropic", "google", "grok", "bash"}
    for other in all_providers - {provider}:
        assert other in result
