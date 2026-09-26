"""Recognize the vendor of a LiteLLM proxy deployment's upstream model.

Request shaping for Claude (max_tokens, prompt caching, tool schemas) must
apply to names neither Inspect nor LiteLLM know (e.g. a predeployment
codename), so this reads the names themselves rather than model info.
"""

import re
from typing import Iterable, Literal
from urllib.parse import urlparse

from ._first_party import FRONTIER_MODELS

Vendor = Literal["anthropic", "openai", "google", "grok"]

# LiteLLM provider segments that serve a single vendor's models
_VENDOR_PROVIDERS: dict[str, Vendor] = {"anthropic": "anthropic", "xai": "grok"}

# LiteLLM provider for each vendor's own API, for `base_model` suggestions
_LITELLM_PROVIDERS: dict[Vendor, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "gemini",
    "grok": "xai",
}

VENDOR_NAMES: dict[Vendor, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    "grok": "xAI",
}
"""Display names, for messages."""

# gpt-oss is OpenAI's open-weights family, served by many providers; unlike
# the org rules for database matching (`_litellm_proxy_names.NAME_ORGS`), it
# is not the OpenAI vendor here (no OpenAI frontier suggestion for it)
_OPENAI_MODEL = re.compile(r"(^|[/.])(gpt-(?!oss)|o\d|chatgpt|codex)")


def upstream_vendor(names: Iterable[str | None]) -> Vendor | None:
    """The vendor of the first name that identifies one.

    Args:
        names: Model names to try in order, e.g. the upstream model string
            (`bedrock/us.anthropic.claude-...`), then the proxy alias.
    """
    for name in names:
        if name:
            vendor = _name_vendor(name.lower())
            if vendor is not None:
                return vendor
    return None


def _name_vendor(name: str) -> Vendor | None:
    provider = name.split("/", 1)[0] if "/" in name else None
    if provider in _VENDOR_PROVIDERS:
        return _VENDOR_PROVIDERS[provider]
    if "claude" in name:
        return "anthropic"
    if "gemini" in name:
        return "google"
    if "grok" in name:
        return "grok"
    if _OPENAI_MODEL.search(name):
        return "openai"
    return None


def deployment_route(model: str | None, custom_llm_provider: str | None) -> str | None:
    """The LiteLLM provider a deployment's requests are sent through.

    `custom_llm_provider` when set, else the first segment of the upstream
    model string (`litellm_params.model`). A bare name (e.g. `gpt-5`) has
    its provider inferred by LiteLLM; of those, only OpenAI names are
    recognized here. `model_info.base_model` never sets the route.
    """
    if custom_llm_provider:
        return custom_llm_provider.lower()
    if not model:
        return None
    if "/" in model:
        return model.split("/", 1)[0].lower()
    return "openai" if _OPENAI_MODEL.search(model.lower()) else None


def is_openai_api_base(api_base: str | None) -> bool:
    """Whether a deployment's `api_base` is OpenAI's own API (or unset).

    An `openai/` route with another `api_base` is usually an
    OpenAI-compatible server, which may not serve the Responses API.
    """
    if api_base is None:
        return True
    host = urlparse(api_base).hostname or ""
    return host == "api.openai.com" or host.endswith(".api.openai.com")


def frontier_base_model(vendor: Vendor) -> str:
    """The vendor's frontier model, named as LiteLLM's `base_model` takes it."""
    model = FRONTIER_MODELS[vendor].split("/", 1)[1]
    return f"{_LITELLM_PROVIDERS[vendor]}/{model}"
