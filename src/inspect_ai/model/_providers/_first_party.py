"""First-party provider definitions.

This module defines which providers are considered "first-party" providers -
those whose models have their own unique naming in the model_info database
(e.g., "anthropic/claude-sonnet-4" rather than HuggingFace-style names).
"""

# Known first-party providers whose models have org/model format in database
FIRST_PARTY_PROVIDERS = frozenset(
    {
        "anthropic",
        "openai",
        "google",
        "mistral",
        "grok",
        "deepseek",
        "cohere",
    }
)
