"""Common Amazon Bedrock utilities for model providers."""

import os
from logging import getLogger
from typing import Callable

from inspect_ai._util.error import PrerequisiteError

from .util import model_base_url

logger = getLogger(__name__)

# OpenAI models on Bedrock are currently only available in us-east-2, so we
# default to it when no region is otherwise specified (revisit when more
# regions become available).
DEFAULT_BEDROCK_REGION = "us-east-2"


def resolve_bedrock_base_url(
    base_url: str | None, base_url_vars: list[str], region: str, path: str = "v1"
) -> str:
    """Resolve the Bedrock Mantle (OpenAI-compatible) endpoint base URL.

    Uses an explicit `base_url` or one of `base_url_vars` if provided, otherwise
    derives the region-specific Mantle endpoint. We derive the endpoint ourselves
    (rather than relying on the OpenAI SDK) because the correct path is
    model-dependent: frontier OpenAI models (gpt-5.x, codex) are served at
    `/openai/v1`, while open-weight models (e.g. gpt-oss) and others are served
    at `/v1` (the OpenAI SDK always derives `/openai/v1`).

    Args:
        base_url: Explicitly provided base URL (or None).
        base_url_vars: Environment variable names to check for a base URL.
        region: The resolved AWS region.
        path: API path for the Mantle endpoint (`"v1"` or `"openai/v1"`).

    Returns:
        The resolved base URL.
    """
    return (
        model_base_url(base_url, base_url_vars)
        or f"https://bedrock-mantle.{region}.api.aws/{path}"
    )


def resolve_bedrock_region(region: str | None) -> str:
    """Resolve the AWS region for Bedrock.

    Precedence: explicit `region` arg, then `AWS_REGION`, then
    `AWS_DEFAULT_REGION`, then the `DEFAULT_BEDROCK_REGION` fallback. Always
    returns a region (never raises).

    Args:
        region: Explicitly provided region (or None).

    Returns:
        The resolved AWS region.
    """
    return (
        region
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or DEFAULT_BEDROCK_REGION
    )


def resolve_bedrock_token_provider(region: str | None) -> Callable[[], str]:
    """Resolve a Bedrock bearer-token provider from the AWS credential chain.

    Generates short-lived Bedrock bearer tokens from standard AWS credentials
    (IAM roles, instance profiles, SSO, AssumeRole, env credentials, profiles)
    via the `aws-bedrock-token-generator` package.

    Args:
        region: AWS region the generated token should be scoped to.

    Returns:
        A callable token provider function.

    Raises:
        PrerequisiteError: If the `aws-bedrock-token-generator` package is not
            installed.
    """
    try:
        from aws_bedrock_token_generator import (  # type: ignore[import-untyped]
            provide_token,
        )
    except ImportError:
        raise PrerequisiteError(
            "ERROR: Using OpenAI on Bedrock with AWS credentials requires the "
            "`aws-bedrock-token-generator` package.\n\n"
            "Install it with: pip install aws-bedrock-token-generator\n\n"
            "Alternatively, provide a Bedrock API key via the BEDROCK_OPENAI_API_KEY "
            "or AWS_BEARER_TOKEN_BEDROCK environment variable."
        )

    return lambda: provide_token(region=region)
