# xAI's prompt cache is per-server, and requests are otherwise load balanced
# across servers. This header pins a conversation to one server so its turns
# hit the cache the earlier turns populated.
# https://docs.x.ai/developers/advanced-api-usage/prompt-caching/maximizing-cache-hits
GROK_CONV_ID_HEADER = "x-grok-conv-id"
