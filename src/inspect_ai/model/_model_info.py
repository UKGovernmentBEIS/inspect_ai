"""Model information lookup functions.

This module provides functions to look up model metadata (context window,
output tokens, etc.) from a local database, as well as the ability to
register custom model information for models not in the database.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from inspect_ai.model._model_data.model_data import (
    ModelCost,
    ModelInfo,
    read_model_info,
)

if TYPE_CHECKING:
    from inspect_ai.model._model import Model  # noqa: F401

# Custom model registry (populated by set_model_info)
_custom_models: dict[str, ModelInfo] = {}

# Cached model info database
_model_info_cache: dict[str, ModelInfo] | None = None


def _get_model_info_db() -> dict[str, ModelInfo]:
    """Get the model info database, loading it on first access."""
    global _model_info_cache
    if _model_info_cache is None:
        _model_info_cache = read_model_info()
    return _model_info_cache


def _normalize_for_lookup(name: str) -> str:
    """Normalize a model name for case-insensitive lookup."""
    return name.lower().replace("_", "-")


def _build_lookup_index() -> dict[str, str]:
    """Build an index mapping normalized names to original keys."""
    db = _get_model_info_db()
    index: dict[str, str] = {}
    for key in db:
        normalized = _normalize_for_lookup(key)
        index[normalized] = key
    return index


# Cached lookup index for case-insensitive matching
_lookup_index: dict[str, str] | None = None


def _get_lookup_index() -> dict[str, str]:
    """Get the lookup index, building it on first access."""
    global _lookup_index
    if _lookup_index is None:
        _lookup_index = _build_lookup_index()
    return _lookup_index


# Known service prefixes that should be stripped for model info lookup.
# These are intermediate routing prefixes (e.g., "azure" in "openai/azure/gpt-4o")
# that indicate a hosting service but don't correspond to the model organization.
# Only stripped when in the "service slot" (middle position of 3-part paths).
SERVICE_PREFIXES = {"azure", "bedrock", "vertex"}

# Hosting providers that serve models from multiple organizations.
# For these providers, we need to detect the organization from the model name.
HOSTING_PROVIDERS = {"azureai", "bedrock", "vertex"}


def _detect_org_from_model_name(model_name: str) -> str | None:
    """Detect the organization from a model name pattern.

    Args:
        model_name: The model name (without provider prefix).

    Returns:
        The detected organization, or None if not detected.
    """
    name = model_name.lower()

    # OpenAI models: gpt-*, o1*, o3*, o4*
    if (
        name.startswith("gpt-")
        or name.startswith("o1")
        or name.startswith("o3")
        or name.startswith("o4")
    ):
        return "openai"

    # Anthropic models: claude-*
    if name.startswith("claude"):
        return "anthropic"

    # Mistral models: mistral-*, mixtral-*
    if name.startswith("mistral") or name.startswith("mixtral"):
        return "mistral"

    # Google models: gemini-*
    if name.startswith("gemini"):
        return "google"

    return None


def _extract_model_name(name: str) -> str:
    """Extract the model name component from a full path.

    For paths like org/model, returns both parts.
    For paths like provider/org/model, returns org/model.
    For paths like provider/service/model where service is a known hosting service
    (azure, bedrock, vertex), strips the service and returns provider/model.
    For hosting providers (azureai, bedrock, vertex), detects the organization
    from the model name.

    Examples:
        "openai/gpt-4o" → "openai/gpt-4o"
        "together/meta-llama/Llama-3" → "meta-llama/Llama-3"
        "openai/azure/gpt-4o" → "openai/gpt-4o" (service prefix stripped)
        "anthropic/bedrock/claude-3" → "anthropic/claude-3" (service prefix stripped)
        "google/vertex/gemini-2" → "google/gemini-2" (service prefix stripped)
        "azureai/gpt-4o" → "openai/gpt-4o" (org detection)
        "azureai/claude-3-sonnet" → "anthropic/claude-3-sonnet" (org detection)
        "bedrock/claude-3-sonnet" → "anthropic/claude-3-sonnet" (org detection)
        "vertex/gemini-2.0-flash" → "google/gemini-2.0-flash" (org detection)
    """
    parts = name.split("/")
    if len(parts) >= 3:
        # Check if the second-to-last part is a known service prefix
        # e.g., "openai/azure/gpt-4o" → parts[-2] is "azure"
        if parts[-2].lower() in SERVICE_PREFIXES:
            # Strip the service prefix: return provider/model
            return f"{parts[-3]}/{parts[-1]}"
    if len(parts) >= 2:
        # Check if this is a hosting provider that needs org detection
        provider = parts[-2].lower()
        if provider in HOSTING_PROVIDERS:
            model_name = parts[-1]
            detected_org = _detect_org_from_model_name(model_name)
            if detected_org:
                return f"{detected_org}/{model_name}"
        return "/".join(parts[-2:])
    return parts[-1] if parts else name


def _normalize_for_fuzzy(name: str) -> str:
    """Aggressive normalization for fuzzy matching.

    Normalizes case, underscores/hyphens, and strips version suffixes.
    """
    name = name.lower()
    name = name.replace("_", "-")
    # Strip version suffixes (-v1, -v2, :0, etc.)
    name = re.sub(r"-v\d+$", "", name)
    name = re.sub(r":\d+$", "", name)
    return name


def _compute_match_score(query: str, target: str) -> int:
    """Compute match score between query and target.

    Returns:
        Score from 0-100. Higher is better.
        - 100: Exact match
        - 50-99: Substring match (scored by overlap ratio)
        - 0: No match
    """
    if query == target:
        return 100  # Exact match

    if query in target or target in query:
        # Substring match - score by overlap ratio
        overlap = len(query) if query in target else len(target)
        max_len = max(len(query), len(target))
        return 50 + int(50 * overlap / max_len)

    return 0


def _fuzzy_match(name: str, db: dict[str, ModelInfo]) -> ModelInfo | None:
    """Try to fuzzy match a model name against the database.

    Extracts the model name component and tries to find the best match
    in the database using normalized comparison.

    Args:
        name: The canonical model name to look up.
        db: The model info database.

    Returns:
        The best matching ModelInfo, or None if no match found.
    """
    model_part = _extract_model_name(name)
    normalized_query = _normalize_for_fuzzy(model_part)

    best_match: tuple[int, str, ModelInfo] | None = None  # (score, key, info)

    for key, info in db.items():
        key_model = _extract_model_name(key)
        key_normalized = _normalize_for_fuzzy(key_model)

        score = _compute_match_score(normalized_query, key_normalized)
        if score > 0:
            if best_match is None:
                best_match = (score, key, info)
            elif score > best_match[0]:
                best_match = (score, key, info)

    # Only return matches with reasonable confidence
    if best_match and best_match[0] >= 60:
        return best_match[2]

    return None


def _lookup_in_db(name: str, db: dict[str, ModelInfo]) -> ModelInfo | None:
    """Try to find a model in the database using various matching strategies.

    Args:
        name: The model name to look up.
        db: The model info database.

    Returns:
        ModelInfo if found, None otherwise.
    """
    # Try exact match
    if name in db:
        return db[name]

    # Try case-insensitive match using the lookup index
    index = _get_lookup_index()
    normalized = _normalize_for_lookup(name)
    if normalized in index:
        return db[index[normalized]]

    # Try fuzzy matching
    return _fuzzy_match(name, db)


def get_model_info(model: str | Model) -> ModelInfo | None:
    """Get model information including context window, output tokens, etc.

    Looks up model information from a local database. Supports standard
    Inspect model strings and performs case-insensitive matching.

    This function first tries direct database lookup, which does not require
    provider SDKs to be installed. It only falls back to full provider
    instantiation if direct lookup fails.

    Args:
        model: Model name or Model instance. Standard Inspect model strings
            are supported (e.g., "together/meta-llama/Llama-3.1-8B-Instruct").
            The model is resolved and its canonical name is used for lookup.

    Returns:
        ModelInfo object with context_length, output_tokens, organization, etc.
        Returns None if the model is not found in the database.

    Examples:
        ```python
        from inspect_ai.model import get_model_info

        info = get_model_info("together/meta-llama/Llama-3.1-8B-Instruct")
        if info:
            print(f"Context window: {info.context_length}")
        ```
    """
    # Import here to avoid circular imports
    from inspect_ai.model._model import Model, get_model

    # Get the database
    db = _get_model_info_db()

    # If already a Model instance, use its canonical name directly
    if isinstance(model, Model):
        name = model.canonical_name()

        # Check custom registry first
        if name in _custom_models:
            return _custom_models[name]

        return _lookup_in_db(name, db)

    # For string model names, try direct lookup first (no SDK required)
    # The database includes aliases for common model name formats

    # Check custom registry with original name
    if model in _custom_models:
        return _custom_models[model]

    # Try direct database lookup
    result = _lookup_in_db(model, db)
    if result is not None:
        return result

    # Fall back to full provider instantiation (requires SDK)
    # This handles cases where the model name needs provider-specific canonicalization
    try:
        resolved = get_model(model, api_key="__model_info_lookup__")
        name = resolved.canonical_name()

        if name in _custom_models:
            return _custom_models[name]

        return _lookup_in_db(name, db)
    except (ValueError, Exception):
        # Provider not available or unknown - already tried direct lookup
        return None


def set_model_info(model: str, info: ModelInfo) -> None:
    """Set custom model information for models not in the database.

    Use this to register model information for custom or private models
    that are not included in the built-in database.

    Args:
        model: Model name to register (e.g., "my-provider/custom-model")
        info: ModelInfo object with context_length, output_tokens, etc.

    Examples:
        ```python
        from inspect_ai.model import set_model_info, ModelInfo

        set_model_info(
            "my-provider/custom-model",
            ModelInfo(
                context_length=32000,
                output_tokens=4096,
                organization="My Organization"
            )
        )
        ```
    """
    _custom_models[model] = info


def set_model_cost(model: str, cost: ModelCost) -> None:
    """Set cost data for a model already in the database.

    Looks up the model and updates its cost field. Raises if
    the model is not found in the database or custom registry.

    Args:
        model: Model name (e.g. "openai/gpt-4o")
        cost: ModelCost with pricing per million tokens.
    """
    info = get_model_info(model)
    if info is None:
        raise ValueError(f"Model '{model}' not found.")
    _custom_models[model] = info.model_copy(update={"cost": cost})


def clear_model_info_cache() -> None:
    """Clear the model info cache.

    This is primarily useful for testing. After calling this function,
    the next call to model_info() will reload the database from disk.
    """
    global _model_info_cache, _lookup_index
    _model_info_cache = None
    _lookup_index = None
    _custom_models.clear()
