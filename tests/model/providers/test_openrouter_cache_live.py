"""Live check that OpenRouter caches conversation history for anthropic/* models.

Gated behind --runapi and OPENROUTER_API_KEY. The unit tests in
test_openrouter.py only verify where cache_control markers are placed; this
file verifies that the markers produce cache hits on the wire, which is what
#5873 was about: before the fix, the system prompt and tools were cached but
the growing history was re-sent uncached on every call.

Run with:
    pytest --runapi --runslow tests/model/providers/test_openrouter_cache_live.py -v
"""

import random
import string
from typing import NamedTuple

import pytest
from test_helpers.utils import skip_if_no_openrouter

from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.model._providers.openrouter import SESSION_ID_HEADER
from inspect_ai.tool import ToolInfo, ToolParam, ToolParams

MODEL = "openrouter/anthropic/claude-haiku-4-5"
TURNS = 4
# Anthropic only caches prefixes above a per-model minimum (4096 tokens for
# Haiku 4.5), so the system prompt and each user turn are padded well past it.
SYSTEM_WORDS = 3000
USER_WORDS = 800
# ModelUsage.input_tokens is already net of cache reads and writes, so it is
# the uncached count. With a breakpoint on the last block only per-request
# framing should miss the cache.
MAX_UNCACHED = 300


class Usage(NamedTuple):
    """Input token counts of one call."""

    uncached: int
    cache_read: int
    cache_write: int


def _unique_text(n_words: int) -> str:
    """Large text that is unique per call so runs never share cache entries."""
    salt = "".join(random.choices(string.ascii_letters, k=24))
    rng = random.Random(salt)
    words = ["".join(rng.choices(string.ascii_lowercase, k=6)) for _ in range(n_words)]
    return salt + " " + " ".join(words)


def _config(thinking: bool) -> GenerateConfig:
    # Outside a running sample the provider sends no x-session-id, and without
    # one OpenRouter only routes sticky after a cache hit is observed, so the
    # second call could land on a backend with a cold cache. Pin the
    # conversation to one backend the way a sample would.
    session_id = "".join(random.choices(string.ascii_letters, k=24))
    return GenerateConfig(
        extra_headers={SESSION_ID_HEADER: session_id},
        reasoning_tokens=1024 if thinking else None,
    )


def _usage(output: ModelOutput) -> Usage:
    assert output.usage is not None
    return Usage(
        uncached=output.usage.input_tokens,
        cache_read=output.usage.input_tokens_cache_read or 0,
        cache_write=output.usage.input_tokens_cache_write or 0,
    )


def _assert_history_cached(usage: list[Usage], may_miss: int | None = None) -> None:
    """Assert the cached prefix grows on every call after the first.

    `may_miss` names one call that is allowed to read no more than the call
    before it (it must still not read less).
    """
    # first call writes the system prompt (and first user turn) to the cache
    assert usage[0].cache_write > 0, f"call 0 wrote nothing to the cache: {usage}"

    # every later call reads the whole prior conversation back from the cache,
    # so the cached prefix grows and only per-request framing is sent uncached
    previous_read = usage[0].cache_read
    for call, current in enumerate(usage[1:], 1):
        if call == may_miss:
            assert current.cache_read >= previous_read, (
                f"call {call}: cache read shrank ({previous_read} -> {current.cache_read}): {usage}"
            )
        else:
            assert current.cache_read > previous_read, (
                f"call {call}: cache read did not grow ({previous_read} -> {current.cache_read}): {usage}"
            )
        assert current.uncached < MAX_UNCACHED, (
            f"call {call}: {current.uncached} uncached input tokens, history is not cached: {usage}"
        )
        previous_read = current.cache_read


async def _run_conversation(thinking: bool) -> list[Usage]:
    """Return the usage of each call of a text chat."""
    model = get_model(MODEL, config=_config(thinking))
    messages: list[ChatMessage] = [
        ChatMessageSystem(
            content="Answer in one short sentence. Reference notes:\n"
            + _unique_text(SYSTEM_WORDS)
        ),
        ChatMessageUser(
            content=_unique_text(USER_WORDS) + "\nQuestion 0: what colour is the sky?"
        ),
    ]
    usage: list[Usage] = []
    for turn in range(TURNS):
        output = await model.generate(messages)
        usage.append(_usage(output))
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
    _assert_history_cached(await _run_conversation(thinking))


LOOKUP = ToolInfo(
    name="lookup",
    description="Look up a note by key.",
    parameters=ToolParams(
        properties={"key": ToolParam(type="string", description="Note key.")},
        required=["key"],
    ),
)


@pytest.mark.anyio
@pytest.mark.slow
@pytest.mark.parametrize("thinking", [False, True], ids=["plain", "thinking"])
@skip_if_no_openrouter
async def test_openrouter_anthropic_caches_tool_turn(thinking: bool) -> None:
    """The agent-loop shape: assistant with tool_calls, then a string tool result.

    The history markers convert the string tool result (and the assistant
    text beside the tool call) to list-form text parts carrying
    cache_control. Check that OpenRouter accepts both, that the model still
    reads the tool result, and that the tool turn is read back from the cache.
    """
    model = get_model(MODEL, config=_config(thinking))
    code = "".join(random.choices(string.ascii_uppercase, k=12))
    messages: list[ChatMessage] = [
        ChatMessageSystem(
            content="Answer in one short sentence. Reference notes:\n"
            + _unique_text(SYSTEM_WORDS)
        ),
        ChatMessageUser(
            content=_unique_text(USER_WORDS)
            + "\nSay 'Looking that up.' and then call the lookup tool with key"
            " 'code'. Do not answer before you have the tool result."
        ),
    ]
    usage: list[Usage] = []

    # call 0: the model makes a tool call
    output = await model.generate(messages, tools=[LOOKUP])
    usage.append(_usage(output))
    tool_calls = output.message.tool_calls
    assert tool_calls, f"expected a tool call, got: {output.message}"
    assistant = output.message
    # The assistant message only carries a marker when it has text beside the
    # tool call, and the model does not reliably write any, so supply it. A
    # thinking turn keeps its reasoning block as returned.
    if not assistant.text.strip():
        assistant = assistant.model_copy()
        assistant.text = "Looking that up."
    messages.append(assistant)
    for tool_call in tool_calls:
        messages.append(
            ChatMessageTool(
                content=_unique_text(USER_WORDS) + f"\nThe code is {code}.",
                tool_call_id=tool_call.id,
                function=tool_call.function,
            )
        )

    # call 1: string tool result last, assistant with tool_calls before it
    output = await model.generate(messages, tools=[LOOKUP])
    usage.append(_usage(output))
    assert code in output.completion, (
        f"model did not read the list-form tool result: {output.completion!r}"
    )

    # later calls read the tool turn back from the cache
    for turn in range(2, TURNS):
        messages.append(output.message)
        messages.append(
            ChatMessageUser(
                content=_unique_text(USER_WORDS) + f"\nQuestion {turn}: name a planet."
            )
        )
        output = await model.generate(messages, tools=[LOOKUP])
        usage.append(_usage(output))

    # Haiku 4.5 strips prior-turn thinking blocks (as do Sonnet 4.5 and earlier
    # models): the tool turn's thinking block stays in the prompt while the
    # tool loop is open (call 1) and is dropped once a plain user turn follows
    # (call 2). The prefix written at call 1 then no longer matches, so call 2
    # reads only up to the first user turn and re-writes the tool turn; call 3
    # reads all of it back. Models that keep prior-turn thinking (Opus 4.5,
    # 4.6 and later) would not miss at call 2, which also passes.
    _assert_history_cached(usage, may_miss=2 if thinking else None)
