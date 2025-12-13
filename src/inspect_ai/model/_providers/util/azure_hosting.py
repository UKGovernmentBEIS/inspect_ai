"""Common Azure utilities for model providers."""

import os
import re
from logging import getLogger
from typing import Callable

from inspect_ai._util.error import PrerequisiteError

from .util import model_base_url

logger = getLogger(__name__)

# Default Azure audience for managed identity
AZUREAI_AUDIENCE = "AZUREAI_AUDIENCE"
DEFAULT_AZURE_AUDIENCE = "https://cognitiveservices.azure.com/.default"


def check_azure_deployment_mismatch(
    model_name: str,
    base_url: str | None,
    base_url_env_vars: list[str],
    provider_name: str = "Azure",
) -> None:
    """
    Check for mismatches between specified model and Azure deployment URL.Logs a warning if the model name doesn't match the deployment in the URL.

    Args:
        model_name: The model name without service prefix.
        base_url: The explicitly provided base URL (or None).
        base_url_env_vars: List of environment variable names to check for base URL.
        provider_name: Name of the provider for log messages.
    """
    if not model_name or not model_name.strip():
        return

    # Get the Azure base URL from environment if not explicitly provided
    azure_base_url = base_url or model_base_url(None, base_url_env_vars)
    if not azure_base_url:
        return

    # Extract deployment name from URL
    url_deployment = _extract_deployment_from_azure_url(azure_base_url)
    if not url_deployment:
        return

    # Normalize both names for comparison
    normalized_model = _normalize_azure_model_name(model_name)
    normalized_deployment = _normalize_azure_model_name(url_deployment)

    # Check for mismatch
    if normalized_model != normalized_deployment:
        logger.warning(
            f"Model mismatch detected: model parameter specifies '{model_name}' "
            f"but {provider_name} base URL points to deployment '{url_deployment}'. "
            f"The deployment from the URL ('{url_deployment}') will be used for API calls."
        )


def resolve_azure_token_provider(provider_name: str) -> Callable[[], str]:
    """
    Resolve Azure managed identity token provider (Microsoft Entra ID).

    Args:
        provider_name: Name of the provider for error messages.

    Returns:
        A callable token provider function.

    Raises:
        PrerequisiteError: If azure-identity package is not installed.
    """
    try:
        from azure.identity import (
            DefaultAzureCredential,
            get_bearer_token_provider,
        )

        return get_bearer_token_provider(
            DefaultAzureCredential(),
            os.environ.get(AZUREAI_AUDIENCE, DEFAULT_AZURE_AUDIENCE),
        )
    except ImportError:
        raise PrerequisiteError(
            f"ERROR: The {provider_name} provider requires the "
            "`azure-identity` package for managed identity support."
        )


def require_azure_base_url(
    base_url: str | None,
    base_url_env_vars: list[str],
    provider_name: str,
) -> str:
    """
    Resolve and validate Azure base URL.

    Args:
        base_url: The explicitly provided base URL (or None).
        base_url_env_vars: List of environment variable names to check for base URL.
        provider_name: Name of the provider for error messages.

    Returns:
        The resolved base URL.

    Raises:
        PrerequisiteError: If no base URL is found.
    """
    resolved_url = model_base_url(base_url, base_url_env_vars)
    if not resolved_url:
        env_var_name = base_url_env_vars[0] if base_url_env_vars else "BASE_URL"
        raise PrerequisiteError(
            f"ERROR: You must provide a base URL when using {provider_name} on Azure. "
            f"Use the {env_var_name} environment variable or the --model-base-url CLI flag to set the base URL."
        )
    return resolved_url


def _extract_deployment_from_azure_url(url: str) -> str | None:
    """Extract deployment name from Azure URL."""
    pattern = r"/deployments/([^/]+)"
    match = re.search(pattern, url)
    return match.group(1) if match else None


def _normalize_azure_model_name(model_name: str) -> str:
    """Normalize model names for comparison."""
    if not model_name:
        return ""

    normalized = model_name.lower()
    # Normalize version format: gpt-3.5 <-> gpt-35
    normalized = normalized.replace("gpt-3.5", "gpt-35")
    return normalized
