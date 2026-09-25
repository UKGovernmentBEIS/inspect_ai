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

FRONTIER_MODELS = {
    "anthropic": "anthropic/claude-opus-5-5",
    "openai": "openai/gpt-6-astra",
    "google": "google/gemini-3.8-flash",
    "grok": "grok/grok-4.7",
}
"""Model info database key of each provider's current frontier model.

Providers look up a model they don't recognize (e.g. a predeployment codename)
under this name. Bump when a newer frontier ships.
"""
