"""Live check that OpenRouter caches conversation history for anthropic/* models.

Gated behind --runapi and OPENROUTER_API_KEY. The unit tests in
test_openrouter.py only verify where cache_control markers are placed; this
file verifies that the markers produce cache hits on the wire, which is what
#5873 was about: before the fix, the system prompt and tools were cached but
the growing history was re-sent uncached on every call.

Run with:
    pytest --runapi tests/model/providers/test_openrouter_cache_live.py -v
"""

import random
import string

import pytest
from test_helpers.utils import skip_if_no_openrouter

from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.model._providers.openrouter import SESSION_ID_HEADER

MODEL = "openrouter/anthropic/claude-haiku-4-5"
TURNS = 4
# Anthropic only caches prefixes above a per-model minimum (2048 tokens for
# Haiku), so the system prompt and each user turn are padded well past it.
SYSTEM_WORDS = 3000
USER_WORDS = 800
# tokens that may legitimately miss the cache on each call: the new user
# turn's trailing text plus any per-request framing
MAX_UNCACHED = 300


def _unique_text(n_words: int) -> str:
    """Large text that is unique per call so runs never share cache entries."""
    salt = "".join(random.choices(string.ascii_letters, k=24))
    rng = random.Random(salt)
    words = ["".join(rng.choices(string.ascii_lowercase, k=6)) for _ in range(n_words)]
    return salt + " " + " ".join(words)


async def _run_conversation(thinking: bool) -> list[tuple[int, int, int]]:
    """Return (input, cache_read, cache_write) per call of a multi-turn chat."""
    # Outside a running sample the provider sends no x-session-id, and without
    # one OpenRouter only routes sticky after a cache hit is observed, so the
    # second call could land on a backend with a cold cache. Pin the
    # conversation to one backend the way a sample would.
    session_id = "".join(random.choices(string.ascii_letters, k=24))
    config = GenerateConfig(
        extra_headers={SESSION_ID_HEADER: session_id},
        reasoning_tokens=1024 if thinking else None,
    )
    model = get_model(MODEL, config=config)
    messages: list[ChatMessage] = [
        ChatMessageSystem(
            content="Answer in one short sentence. Reference notes:\n"
            + _unique_text(SYSTEM_WORDS)
        ),
        ChatMessageUser(
            content=_unique_text(USER_WORDS) + "\nQuestion 0: what colour is the sky?"
        ),
    ]
    usage: list[tuple[int, int, int]] = []
    for turn in range(TURNS):
        output = await model.generate(messages)
        assert output.usage is not None
        usage.append(
            (
                output.usage.input_tokens,
                output.usage.input_tokens_cache_read or 0,
                output.usage.input_tokens_cache_write or 0,
            )
        )
        messages.append(output.message)
        messages.append(
            ChatMessageUser(
                content=_unique_text(USER_WORDS)
                + f"\nQuestion {turn + 1}: name a planet."
            )
        )
    return usage


@pytest.mark.anyio
@pytest.mark.parametrize("thinking", [False, True], ids=["plain", "thinking"])
@skip_if_no_openrouter
async def test_openrouter_anthropic_caches_conversation_history(
    thinking: bool,
) -> None:
    usage = await _run_conversation(thinking)

    # first call writes the system prompt (and first user turn) to the cache
    first_input, first_read, first_write = usage[0]
    assert first_write > 0, f"call 0 wrote nothing to the cache: {usage}"

    # every later call reads the whole prior conversation back from the cache,
    # so the cached prefix grows and only the new turn is sent uncached
    previous_read = first_read
    for call, (input_tokens, cache_read, cache_write) in enumerate(usage[1:], 1):
        uncached = input_tokens - cache_read - cache_write
        assert cache_read > previous_read, (
            f"call {call}: cache read did not grow ({previous_read} -> {cache_read}): {usage}"
        )
        assert uncached < MAX_UNCACHED, (
            f"call {call}: {uncached} uncached input tokens, history is not cached: {usage}"
        )
        previous_read = cache_read
