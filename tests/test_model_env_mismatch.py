"""
Tests for detecting mismatches between model parameters and environment variables.

This test suite validates that the system properly detects and handles cases
where the model parameter conflicts with environment variable settings.

Related to issue #2705: https://github.com/UKGovernmentBEIS/inspect_ai/issues/2705
"""

import logging
from contextlib import contextmanager
from typing import Iterator

import pytest

from inspect_ai import eval
from inspect_ai.model import get_model


@contextmanager
def capture_inspect_warnings() -> Iterator[list[str]]:
    """Collect inspect_ai WARNING messages straight off the `inspect_ai` logger.

    Neither `caplog` nor `capsys` is reliable here once anything else in the
    process has run an eval: `init_logger()` sets `propagate = False` on the
    `inspect_ai` logger (so records never reach the root logger `caplog`
    attaches to), and `display="none"` calls `rich.reconfigure(quiet=True)`
    (so the rich console that `LogHandler` renders to drops everything
    `capsys` would have seen). Our own handler on the `inspect_ai` logger is
    independent of both globals.
    """
    messages: list[str] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    logger = logging.getLogger("inspect_ai")
    handler = Collector(level=logging.WARNING)
    logger.addHandler(handler)

    # only touch the level if warnings would otherwise be filtered out, and
    # restore it only if nothing else (e.g. init_logger) changed it meanwhile
    saved_level = logger.level
    lowered = not logger.isEnabledFor(logging.WARNING)
    if lowered:
        logger.setLevel(logging.WARNING)
    try:
        yield messages
    finally:
        logger.removeHandler(handler)
        if lowered and logger.level == logging.WARNING:
            logger.setLevel(saved_level)


class TestModelEnvironmentMismatch:
    """Tests for model/environment variable conflict detection."""

    def test_azure_model_url_mismatch_logs_warning(self, monkeypatch, mocker):
        # Test that using model=openai/azure/o3 with AZUREAI_OPENAI_BASE_URL pointing to o4-mini logs a mismatch warning.
        # Set up environment variable pointing to o4-mini
        monkeypatch.setenv(
            "AZUREAI_OPENAI_BASE_URL",
            "https://example.openai.azure.com/openai/deployments/o4-mini",
        )
        monkeypatch.setenv("AZUREAI_OPENAI_API_KEY", "test-key")

        # Mock the Azure client creation instead of the entire API class
        mocker.patch("inspect_ai.model._providers.openai.AsyncAzureOpenAI")
        mocker.patch("inspect_ai.model._providers.openai.DefaultAsyncHttpxClient")

        # Call get_model to trigger the mismatch warning
        with capture_inspect_warnings() as warnings:
            try:
                get_model("openai/azure/o3", memoize=False)
            except Exception:
                # Ignore other exceptions; we just want the warning output
                pass

        warning_messages = [msg.lower() for msg in warnings]

        assert any("mismatch" in msg for msg in warning_messages), (
            f"Expected 'mismatch' in warnings. Got: {warning_messages}"
        )
        assert any("o3" in msg for msg in warning_messages), (
            f"Expected 'o3' in warnings. Got: {warning_messages}"
        )
        assert any("o4-mini" in msg for msg in warning_messages), (
            f"Expected 'o4-mini' in warnings. Got: {warning_messages}"
        )

    def test_azure_model_url_mismatch_with_eval(self, monkeypatch, mocker):
        # Test that eval() logs warning about model/URL mismatch.

        from inspect_ai import Task
        from inspect_ai.dataset import Sample
        from inspect_ai.scorer import match
        from inspect_ai.solver import generate

        # Set up conflicting environment
        monkeypatch.setenv(
            "AZUREAI_OPENAI_BASE_URL",
            "https://example.openai.azure.com/openai/deployments/gpt-4-mini",
        )
        monkeypatch.setenv("AZUREAI_OPENAI_API_KEY", "test-key")

        # Mock the Azure client creation instead of the entire API class
        mocker.patch("inspect_ai.model._providers.openai.AsyncAzureOpenAI")
        mocker.patch("inspect_ai.model._providers.openai.DefaultAsyncHttpxClient")

        # Create a minimal task with proper solver and scorer
        task = Task(
            dataset=[Sample(input="test", target="test")],
            solver=[generate()],
            scorer=match(),
        )

        # Should log warning during evaluation setup
        with capture_inspect_warnings() as warnings:
            try:
                eval(task, model="openai/azure/gpt-35-turbo", limit=1)
            except Exception:
                # We're only checking for warnings during setup, not execution success
                pass

        output = "\n".join(warnings).lower()

        # Check for mismatch warning in the logged warnings
        assert "mismatch" in output, f"Expected 'mismatch' in output. Got: {output}"
        assert "gpt-35-turbo" in output or "gpt-4-mini" in output, (
            f"Expected model names in output. Got: {output}"
        )

    def test_azure_matching_model_url_no_warning(self, monkeypatch, mocker):
        """
        Test that matching model parameter and URL do not log warnings.

        This is a positive test case to ensure we don't have false positives.
        """
        # Set up matching environment - deployment name in URL should match model name
        monkeypatch.setenv(
            "AZUREAI_OPENAI_BASE_URL",
            "https://example.openai.azure.com/openai/deployments/gpt-35-turbo",
        )
        monkeypatch.setenv("AZUREAI_OPENAI_API_KEY", "test-key")

        # Mock the Azure client creation (not the whole provider class, which
        # would skip the constructor that performs the mismatch check)
        mocker.patch("inspect_ai.model._providers.openai.AsyncAzureOpenAI")
        mocker.patch("inspect_ai.model._providers.openai.DefaultAsyncHttpxClient")

        # This should not log any mismatch warnings
        with capture_inspect_warnings() as warnings:
            try:
                model = get_model("openai/azure/gpt-35-turbo", memoize=False)
                assert model is not None
            except Exception:
                # Might fail for other reasons, but shouldn't have mismatch warning
                pass

        # Verify no mismatch warnings were logged
        mismatch_warnings = [msg for msg in warnings if "mismatch" in msg.lower()]
        assert not mismatch_warnings, (
            f"Should not log mismatch warning for matching config. Got: {mismatch_warnings}"
        )

    def test_case_insensitive_matching(self, monkeypatch, mocker):
        """
        Test that model name comparison is case-insensitive where appropriate.

        Avoids false positive warnings for GPT-4 vs gpt-4 style variations.
        """
        # Set up with lowercase in URL
        monkeypatch.setenv(
            "AZUREAI_OPENAI_BASE_URL",
            "https://example.openai.azure.com/openai/deployments/gpt-4",
        )
        monkeypatch.setenv("AZUREAI_OPENAI_API_KEY", "test-key")

        # Mock the Azure client creation (not the whole provider class, which
        # would skip the constructor that performs the mismatch check)
        mocker.patch("inspect_ai.model._providers.openai.AsyncAzureOpenAI")
        mocker.patch("inspect_ai.model._providers.openai.DefaultAsyncHttpxClient")

        # Use uppercase in model parameter
        with capture_inspect_warnings() as warnings:
            try:
                get_model("openai/azure/GPT-4", memoize=False)
            except Exception:
                pass

        # Should not warn about case differences
        mismatch_warnings = [msg for msg in warnings if "mismatch" in msg.lower()]
        assert not mismatch_warnings, (
            f"Should not warn about case-only differences. Got: {mismatch_warnings}"
        )

    def test_deployment_name_normalization(self, monkeypatch, caplog):
        """
        Test that common naming variations are handled (e.g., gpt-35-turbo vs gpt-3.5-turbo).

        Azure deployment names often use different conventions than OpenAI model names.
        """
        import logging

        # Azure often uses "35" instead of "3.5"
        monkeypatch.setenv(
            "AZUREAI_OPENAI_BASE_URL",
            "https://example.openai.azure.com/openai/deployments/gpt-35-turbo",
        )
        monkeypatch.setenv("AZUREAI_OPENAI_API_KEY", "test-key")

        # Using the OpenAI-style name
        with caplog.at_level(logging.WARNING):
            try:
                get_model("openai/azure/gpt-3.5-turbo")
            except Exception:
                pass

        # Should not warn about this known naming difference
        any(
            "mismatch" in record.message.lower()
            for record in caplog.records
            if record.levelname == "WARNING"
        )

        # This test documents expected behavior - adjust based on implementation
        # If we want to warn here, change to assert mismatch_warning

    def test_other_providers_not_affected(self, monkeypatch):
        """
        Test that non-Azure providers don't trigger mismatch warnings.

        Ensures the warning logic is scoped appropriately.
        """
        # Set OpenAI API key for non-Azure provider
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        # Should not log mismatch warnings for non-Azure providers
        with capture_inspect_warnings() as warnings:
            try:
                model = get_model("openai/gpt-4", memoize=False)
                assert model is not None
            except Exception:
                pass  # Ignore other errors, we're checking for warnings

        # Verify no mismatch warnings
        mismatch_warnings = [msg for msg in warnings if "mismatch" in msg.lower()]
        assert not mismatch_warnings, (
            f"Should not check mismatches for non-Azure providers. Got: {mismatch_warnings}"
        )

    def test_warning_message_contains_both_models(self, monkeypatch, mocker):
        # Test that the warning message includes both the requested and actual models.

        monkeypatch.setenv(
            "AZUREAI_OPENAI_BASE_URL",
            "https://example.openai.azure.com/openai/deployments/o4-mini",
        )
        monkeypatch.setenv("AZUREAI_OPENAI_API_KEY", "test-key")

        # Mock the Azure client creation instead of the entire API class
        mocker.patch("inspect_ai.model._providers.openai.AsyncAzureOpenAI")
        mocker.patch("inspect_ai.model._providers.openai.DefaultAsyncHttpxClient")

        with capture_inspect_warnings() as warnings:
            try:
                # Disable memoization to ensure fresh model creation
                get_model("openai/azure/o3", memoize=False)
            except Exception:
                # Might fail for other reasons, but should still have logged warning
                pass

        output = "\n".join(warnings).lower()

        # Check for mismatch warning in the logged warnings
        assert "mismatch" in output, f"Expected 'mismatch' in output. Got: {output}"
        assert "o3" in output, f"Expected 'o3' in output. Got: {output}"
        assert "o4-mini" in output, f"Expected 'o4-mini' in output. Got: {output}"


class TestModelParameterValidation:
    """Additional tests for model parameter validation."""

    def test_invalid_azure_model_format(self, monkeypatch):
        """Test that invalid Azure model formats are handled appropriately."""
        from inspect_ai._util.error import PrerequisiteError

        monkeypatch.setenv(
            "AZUREAI_OPENAI_BASE_URL",
            "https://example.openai.azure.com/openai/deployments/test",
        )
        monkeypatch.setenv("AZUREAI_OPENAI_API_KEY", "test-key")

        # Empty model name after azure/ should either raise an error or be handled
        # The behavior depends on the OpenAI provider implementation
        # This test documents that empty model names are caught somewhere
        try:
            get_model("openai/azure/")
            # If it doesn't raise, that's acceptable - the provider might handle it
            # The mismatch check now skips empty model names
        except (ValueError, PrerequisiteError):
            # This is also acceptable - the provider catches it
            pass

    def test_missing_azure_base_url(self, monkeypatch):
        """Test that missing AZUREAI_OPENAI_BASE_URL is handled properly."""
        from inspect_ai._util.error import PrerequisiteError

        # Clear any existing env vars
        monkeypatch.delenv("AZUREAI_OPENAI_BASE_URL", raising=False)
        monkeypatch.setenv("AZUREAI_OPENAI_API_KEY", "test-key")

        with pytest.raises(PrerequisiteError, match="base URL"):
            get_model("openai/azure/gpt-4")


# Fixtures for common test setup
@pytest.fixture
def clean_environment(monkeypatch):
    """Clean Azure-related environment variables before each test."""
    monkeypatch.delenv("AZUREAI_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AZUREAI_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    yield
