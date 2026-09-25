"""Unit tests for OpenAI explicit prompt-cache breakpoints (ContentText.cache_breakpoint).

These exercise `generate_completions` / `generate_responses` directly with a
mocked client — no API calls. gpt-5.6+ is the only model family that accepts
`prompt_cache_options`/`prompt_cache_breakpoint`; earlier models, and a mark
in an unsupported position, must silently keep the provider's normal
implicit caching rather than sending the (rejected) explicit fields. OpenAI
documents no cap on the number of supplied markers, unlike Anthropic's
genuine 4-breakpoint request limit.
"""

import random
import string
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.responses import Response, ResponseOutputMessage, ResponseOutputText
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)
from test_helpers.utils import skip_if_no_openai, skip_if_no_openai_model

from inspect_ai._util.content import Content, ContentText
from inspect_ai.model import get_model
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._openai_responses import ResponsesModelInfo
from inspect_ai.model._providers.openai import OpenAIAPI
from inspect_ai.model._providers.openai_completions import generate_completions
from inspect_ai.model._providers.openai_responses import generate_responses
from inspect_ai.model._providers.util.hooks import HttpxHooks

# an internal gpt-5.6 codename (analogous to gpt-6-astra); not all accounts
# have access, hence skip_if_no_openai_model rather than assuming a fixed name
_GPT_5_6_MODEL = "gpt-5.6-terra"


def _unique_rubric(n_words: int = 900) -> str:
    """A large, unique-per-call text block so live cache tests never collide."""
    salt = "".join(random.choices(string.ascii_letters, k=24))
    rng = random.Random(salt)
    words = ["".join(rng.choices(string.ascii_lowercase, k=6)) for _ in range(n_words)]
    return salt + " " + " ".join(words)


def _rubric_then_item(*, breakpoint: bool) -> list[ChatMessage]:
    content: list[Content] = [ContentText(text="rubric", cache_breakpoint=breakpoint)]
    content.append(ContentText(text="item"))
    return [ChatMessageUser(content=content)]


def _mock_completions_client(mock_completion: ChatCompletion) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=mock_completion)
    return client


def _mock_http_hooks() -> MagicMock:
    http_hooks = MagicMock(spec=HttpxHooks)
    http_hooks.start_request = MagicMock(return_value="req_1")
    http_hooks.end_request = MagicMock(return_value=None)
    return http_hooks


def _mock_openai_api(model: str) -> MagicMock:
    openai_api = MagicMock()
    openai_api.api_model_name.return_value = model
    openai_api.service_tier = None
    openai_api.is_o_series.return_value = False
    openai_api.is_gpt.return_value = True
    openai_api.is_gpt_5.return_value = True
    openai_api.model_family.return_value = model
    return openai_api


_MOCK_COMPLETION = ChatCompletion.model_construct(
    id="chatcmpl-test",
    created=0,
    model="gpt-5.6",
    object="chat.completion",
    choices=[
        Choice.model_construct(
            finish_reason="stop",
            index=0,
            message=ChatCompletionMessage.model_construct(
                role="assistant", content="ok"
            ),
        )
    ],
)


async def _completions_request(
    model: str, input: list[ChatMessage], config: GenerateConfig | None = None
) -> dict[str, Any]:
    client = _mock_completions_client(_MOCK_COMPLETION)
    await generate_completions(
        client=client,
        http_hooks=_mock_http_hooks(),
        model_name=model,
        input=input,
        tools=[],
        tool_choice="auto",
        config=config or GenerateConfig(),
        prompt_cache_key=NOT_GIVEN,
        prompt_cache_retention=NOT_GIVEN,
        safety_identifier=NOT_GIVEN,
        openai_api=_mock_openai_api(model),
        batcher=None,
        # stands in for the direct OpenAI provider, which passes True
        supports_explicit_prompt_cache=True,
    )
    return dict(client.chat.completions.create.call_args.kwargs)


def _tagged_text_parts(messages: list[dict[str, Any]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for mi, m in enumerate(messages):
        content = m.get("content")
        if isinstance(content, list):
            for bi, b in enumerate(content):
                if isinstance(b, dict) and "prompt_cache_breakpoint" in b:
                    out.append((mi, bi))
    return out


@pytest.mark.anyio
async def test_completions_unmarked_stays_implicit() -> None:
    request = await _completions_request("gpt-5.6", _rubric_then_item(breakpoint=False))
    assert "prompt_cache_options" not in request
    assert _tagged_text_parts(request["messages"]) == []


@pytest.mark.anyio
async def test_completions_marked_gpt_5_6_sets_explicit() -> None:
    request = await _completions_request("gpt-5.6", _rubric_then_item(breakpoint=True))
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    assert _tagged_text_parts(request["messages"]) == [(0, 0)]
    assert request["messages"][0]["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit"
    }


@pytest.mark.anyio
async def test_completions_marked_pre_5_6_falls_back_to_implicit() -> None:
    # gpt-5.5 predates explicit prompt caching; the mark must not be sent
    request = await _completions_request("gpt-5.5", _rubric_then_item(breakpoint=True))
    assert "prompt_cache_options" not in request
    assert _tagged_text_parts(request["messages"]) == []


@pytest.mark.anyio
async def test_completions_five_marks_remain_explicit() -> None:
    # OpenAI's guide distinguishes a 4-write-per-request budget from a much
    # larger lookup history; it documents no cap on the number of
    # `prompt_cache_breakpoint` marks a request may supply, so a 5th
    # supported mark must not force the whole request back to implicit mode
    # (unlike Anthropic's genuine 4-breakpoint request limit).
    content: list[Content] = [
        ContentText(text=f"doc-{i}", cache_breakpoint=True) for i in range(5)
    ]
    input: list[ChatMessage] = [ChatMessageUser(content=content)]
    request = await _completions_request("gpt-5.6", input)
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    assert len(_tagged_text_parts(request["messages"])) == 5


@pytest.mark.anyio
async def test_completions_at_budget_sets_explicit() -> None:
    content: list[Content] = [
        ContentText(text=f"doc-{i}", cache_breakpoint=True) for i in range(4)
    ]
    input: list[ChatMessage] = [ChatMessageUser(content=content)]
    request = await _completions_request("gpt-5.6", input)
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    assert len(_tagged_text_parts(request["messages"])) == 4


@pytest.mark.anyio
async def test_completions_marked_but_cache_prompt_false_stays_implicit() -> None:
    # cache_prompt=False must disable explicit caching just like it disables
    # every other caching hint
    request = await _completions_request(
        "gpt-5.6",
        _rubric_then_item(breakpoint=True),
        GenerateConfig(cache_prompt=False),
    )
    assert "prompt_cache_options" not in request
    assert _tagged_text_parts(request["messages"]) == []


@pytest.mark.anyio
async def test_completions_marks_on_system_and_user_both_honored() -> None:
    # system content is rendered per-block (not flattened) for the
    # system/developer role, so a mark there is a supported position, same
    # as a user-message mark — both are honored in the same request
    input: list[ChatMessage] = [
        ChatMessageSystem(
            content=[
                ContentText(text="system rubric", cache_breakpoint=True),
                ContentText(text="system varying tail"),
            ]
        ),
        ChatMessageUser(
            content=[
                ContentText(text="user rubric", cache_breakpoint=True),
                ContentText(text="item"),
            ]
        ),
    ]
    request = await _completions_request("gpt-5.6", input)
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    messages = request["messages"]
    # the developer/system message content is now a block list (not a flat
    # string), with only the marked block carrying the breakpoint
    system_content = messages[0]["content"]
    assert [b["text"] for b in system_content] == [
        "system rubric",
        "system varying tail",
    ]
    assert system_content[0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert "prompt_cache_breakpoint" not in system_content[1]
    assert _tagged_text_parts(messages) == [(0, 0), (1, 0)]


@pytest.mark.anyio
async def test_completions_mark_on_assistant_message_falls_back_whole_request() -> None:
    # this provider doesn't thread a `cache_breakpoints` flag for assistant
    # content; a mark there is a position it can't honor, so the WHOLE
    # request must fall back to implicit — the user-message mark must not be
    # silently promoted to explicit while the assistant mark is dropped
    input: list[ChatMessage] = [
        ChatMessageUser(
            content=[
                ContentText(text="user rubric", cache_breakpoint=True),
                ContentText(text="item"),
            ]
        ),
        ChatMessageAssistant(
            content=[ContentText(text="prior answer", cache_breakpoint=True)]
        ),
    ]
    request = await _completions_request("gpt-5.6", input)
    assert "prompt_cache_options" not in request
    assert _tagged_text_parts(request["messages"]) == []


@pytest.mark.anyio
async def test_completions_unmarked_multi_block_system_stays_flattened() -> None:
    # an unmarked multi-block system message must keep its prior flattened
    # wire shape (a single joined string), not become one part per block
    input: list[ChatMessage] = [
        ChatMessageSystem(content=[ContentText(text="a"), ContentText(text="b")]),
        ChatMessageUser(content="hi"),
    ]
    request = await _completions_request("gpt-5.6", input)
    assert "prompt_cache_options" not in request
    assert request["messages"][0]["content"] == "a\nb"


@pytest.mark.anyio
async def test_completions_empty_marked_system_block_falls_back_to_implicit() -> None:
    # an empty text block can't itself carry a `prompt_cache_breakpoint`
    # (empty text content parts are rejected); a mark placed there is
    # unrepresentable, so the whole request must fall back to implicit
    # rather than silently dropping just that mark
    input: list[ChatMessage] = [
        ChatMessageSystem(
            content=[
                ContentText(text="", cache_breakpoint=True),
                ContentText(text="body"),
            ]
        ),
        ChatMessageUser(content="hi"),
    ]
    request = await _completions_request("gpt-5.6", input)
    assert "prompt_cache_options" not in request
    assert _tagged_text_parts(request["messages"]) == []


@pytest.mark.anyio
async def test_completions_initial_system_gets_automatic_checkpoint() -> None:
    # R5: an otherwise-supported explicit request with an unmarked leading
    # system/developer block retains a checkpoint at its end, so the
    # cumulative prefix (tools + that block) has a boundary to reuse when
    # the marked user prefix changes.
    input: list[ChatMessage] = [
        ChatMessageSystem(content="stable instructions"),
        ChatMessageUser(
            content=[
                ContentText(text="rubric", cache_breakpoint=True),
                ContentText(text="item"),
            ]
        ),
    ]
    request = await _completions_request("gpt-5.6", input)
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    system_content = request["messages"][0]["content"]
    assert system_content == [
        {
            "type": "text",
            "text": "stable instructions",
            "prompt_cache_breakpoint": {"mode": "explicit"},
        }
    ]
    assert _tagged_text_parts(request["messages"]) == [(0, 0), (1, 0)]


@pytest.mark.anyio
async def test_completions_callers_own_initial_system_mark_wins() -> None:
    # a caller's own mark on the initial system block must be authoritative
    # over its varying suffix — no later automatic system boundary is added
    input: list[ChatMessage] = [
        ChatMessageSystem(
            content=[
                ContentText(text="stable", cache_breakpoint=True),
                ContentText(text="varying"),
            ]
        ),
        ChatMessageUser(content="hi"),
    ]
    request = await _completions_request("gpt-5.6", input)
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    system_content = request["messages"][0]["content"]
    assert [b["text"] for b in system_content] == ["stable", "varying"]
    assert system_content[0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert "prompt_cache_breakpoint" not in system_content[1]


@pytest.mark.anyio
async def test_completions_initial_system_preserves_empty_separator() -> None:
    # the automatic initial-system checkpoint must not lose a blank-line
    # separator: ["a", "", "b"] flattens to "a\n\nb" when unmarked, and
    # adding the checkpoint (on the last non-empty block) must join the
    # blocks back into that same single string, not "a\nb"
    input: list[ChatMessage] = [
        ChatMessageSystem(
            content=[ContentText(text="a"), ContentText(text=""), ContentText(text="b")]
        ),
        ChatMessageUser(
            content=[
                ContentText(text="rubric", cache_breakpoint=True),
                ContentText(text="item"),
            ]
        ),
    ]
    request = await _completions_request("gpt-5.6", input)
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    system_content = request["messages"][0]["content"]
    assert system_content == [
        {
            "type": "text",
            "text": "a\n\nb",
            "prompt_cache_breakpoint": {"mode": "explicit"},
        }
    ]


@pytest.mark.anyio
async def test_completions_trailing_empty_block_after_caller_mark_preserves_separator() -> (
    None
):
    # R3: system content ["a"(marked), ""] flattens to "a\n" when unmarked.
    # Marking "a" (either by the caller directly, or via the automatic
    # initial-system checkpoint landing on the last non-empty block) must
    # not drop the trailing empty block's separator and shorten the prompt
    # to just "a".
    input: list[ChatMessage] = [
        ChatMessageSystem(
            content=[
                ContentText(text="a", cache_breakpoint=True),
                ContentText(text=""),
            ]
        ),
        ChatMessageUser(content="hi"),
    ]
    request = await _completions_request("gpt-5.6", input)
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    assert request["messages"][0]["content"] == [
        {
            "type": "text",
            "text": "a\n",
            "prompt_cache_breakpoint": {"mode": "explicit"},
        }
    ]


@pytest.mark.anyio
async def test_completions_tools_only_no_initial_checkpoint_added() -> None:
    # no leading system/developer block exists (a tools-only prompt); there
    # is no representable boundary to mark, so nothing is added
    input: list[ChatMessage] = [
        ChatMessageUser(
            content=[
                ContentText(text="rubric", cache_breakpoint=True),
                ContentText(text="item"),
            ]
        ),
    ]
    request = await _completions_request("gpt-5.6", input)
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    assert _tagged_text_parts(request["messages"]) == [(0, 0)]


def _legacy_content_text(text: str) -> ContentText:
    """A `ContentText` with `cache_breakpoint` genuinely absent from `__dict__`.

    Reproduces what unpickling an object persisted (by Inspect's local
    response cache) before the field existed actually produces: pickle's
    default `__setstate__` restores `__dict__` verbatim and skips
    pydantic's validators/default-filling, so the attribute is missing
    outright, not merely `None`.
    """
    block = ContentText(text=text)
    del block.__dict__["cache_breakpoint"]
    assert "cache_breakpoint" not in block.__dict__
    return block


@pytest.mark.anyio
async def test_legacy_pickled_content_text_without_cache_breakpoint_attribute() -> None:
    # R2: a ContentText predating this field must not raise AttributeError
    # when replayed through a later (even uncached) model call
    input: list[ChatMessage] = [
        ChatMessageSystem(content=[_legacy_content_text("rubric")]),
        ChatMessageUser(content="task"),
        ChatMessageAssistant(content=[_legacy_content_text("prior answer")]),
        ChatMessageUser(content="follow-up"),
    ]
    request = await _completions_request("gpt-5.6", input)
    assert "prompt_cache_options" not in request


# ---------------------------------------------------------------------------
# Responses API
# ---------------------------------------------------------------------------


_MOCK_RESPONSE = Response.model_construct(
    id="resp-test",
    created_at=0,
    model="gpt-5.6",
    object="response",
    output=[
        ResponseOutputMessage.model_construct(
            id="msg-1",
            type="message",
            role="assistant",
            status="completed",
            content=[
                ResponseOutputText.model_construct(
                    type="output_text", text="ok", annotations=[]
                )
            ],
        )
    ],
    parallel_tool_calls=True,
    tool_choice="auto",
    tools=[],
    usage=ResponseUsage.model_construct(
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        input_tokens_details=InputTokensDetails.model_construct(cached_tokens=0),
        output_tokens_details=OutputTokensDetails.model_construct(reasoning_tokens=0),
    ),
    error=None,
)


async def _responses_request(
    model: str, input: list[ChatMessage], config: GenerateConfig | None = None
) -> dict[str, Any]:
    client = MagicMock()
    client.responses.create = AsyncMock(return_value=_MOCK_RESPONSE)
    http_hooks = _mock_http_hooks()
    model_info = MagicMock(spec=ResponsesModelInfo)
    model_info.is_latest.return_value = False
    await generate_responses(
        client=client,
        http_hooks=http_hooks,
        model_name=model,
        input=input,
        tools=[],
        tool_choice="auto",
        config=config or GenerateConfig(),
        background=None,
        service_tier=None,
        prompt_cache_key=NOT_GIVEN,
        prompt_cache_retention=NOT_GIVEN,
        safety_identifier=NOT_GIVEN,
        responses_store=None,
        synthesize_phase=False,
        model_info=model_info,
        batcher=None,
        # stands in for the direct OpenAI provider, which passes True; see
        # test_openrouter.py for the OpenAI-compatible (default False) case
        supports_explicit_prompt_cache=True,
    )
    return dict(client.responses.create.call_args.kwargs)


def _tagged_input_texts(input_items: list[dict[str, Any]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for mi, item in enumerate(input_items):
        content = item.get("content")
        if isinstance(content, list):
            for bi, b in enumerate(content):
                if isinstance(b, dict) and "prompt_cache_breakpoint" in b:
                    out.append((mi, bi))
    return out


@pytest.mark.anyio
async def test_responses_unmarked_stays_implicit() -> None:
    request = await _responses_request("gpt-5.6", _rubric_then_item(breakpoint=False))
    assert "prompt_cache_options" not in request
    assert _tagged_input_texts(request["input"]) == []


@pytest.mark.anyio
async def test_responses_marked_gpt_5_6_sets_explicit() -> None:
    request = await _responses_request("gpt-5.6", _rubric_then_item(breakpoint=True))
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    assert _tagged_input_texts(request["input"]) == [(0, 0)]


@pytest.mark.anyio
async def test_responses_marked_pre_5_6_falls_back_to_implicit() -> None:
    request = await _responses_request("gpt-5.5", _rubric_then_item(breakpoint=True))
    assert "prompt_cache_options" not in request
    assert _tagged_input_texts(request["input"]) == []


@pytest.mark.anyio
async def test_responses_five_marks_remain_explicit() -> None:
    # see test_completions_five_marks_remain_explicit: OpenAI documents no
    # cap on the number of supplied `prompt_cache_breakpoint` marks
    content: list[Content] = [
        ContentText(text=f"doc-{i}", cache_breakpoint=True) for i in range(5)
    ]
    input: list[ChatMessage] = [ChatMessageUser(content=content)]
    request = await _responses_request("gpt-5.6", input)
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    assert len(_tagged_input_texts(request["input"])) == 5


@pytest.mark.anyio
async def test_responses_marked_but_cache_prompt_false_stays_implicit() -> None:
    request = await _responses_request(
        "gpt-5.6",
        _rubric_then_item(breakpoint=True),
        GenerateConfig(cache_prompt=False),
    )
    assert "prompt_cache_options" not in request
    assert _tagged_input_texts(request["input"]) == []


@pytest.mark.anyio
async def test_responses_marks_on_system_and_user_both_honored() -> None:
    # the Responses developer role is rendered through the same per-block
    # content-list param as user messages, so a system mark is a supported
    # position there too
    input: list[ChatMessage] = [
        ChatMessageSystem(
            content=[
                ContentText(text="system rubric", cache_breakpoint=True),
                ContentText(text="system varying tail"),
            ]
        ),
        ChatMessageUser(
            content=[
                ContentText(text="user rubric", cache_breakpoint=True),
                ContentText(text="item"),
            ]
        ),
    ]
    request = await _responses_request("gpt-5.6", input)
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    assert _tagged_input_texts(request["input"]) == [(0, 0), (1, 0)]


@pytest.mark.anyio
async def test_responses_mark_on_assistant_message_falls_back_whole_request() -> None:
    # a mark in an unsupported position (assistant) must force the whole
    # request back to implicit, not just be dropped while the user-message
    # mark is still promoted to explicit
    input: list[ChatMessage] = [
        ChatMessageUser(
            content=[
                ContentText(text="user rubric", cache_breakpoint=True),
                ContentText(text="item"),
            ]
        ),
        ChatMessageAssistant(
            content=[ContentText(text="prior answer", cache_breakpoint=True)]
        ),
    ]
    request = await _responses_request("gpt-5.6", input)
    assert "prompt_cache_options" not in request
    assert _tagged_input_texts(request["input"]) == []


@pytest.mark.anyio
async def test_responses_mark_on_compaction_marker_falls_back_whole_request() -> None:
    # R4: a compaction marker message is replayed natively (as a
    # "compaction" item), bypassing the per-block content conversion that
    # actually emits prompt_cache_breakpoint. A mark on that message's
    # content — role="user", so the role-based eligibility check alone
    # would call it representable — must still force the whole request
    # back to implicit rather than being silently dropped while the other
    # user message's mark is promoted to explicit.
    from inspect_ai._util.content import ContentData

    compaction_message = ChatMessageUser(
        content=[
            ContentText(text="stale", cache_breakpoint=True),
            ContentData(
                data={
                    "compaction_metadata": {
                        "type": "openai_compact",
                        "id": "comp_1",
                        "encrypted_content": "enc",
                    }
                }
            ),
        ]
    )
    input: list[ChatMessage] = [
        compaction_message,
        ChatMessageUser(
            content=[
                ContentText(text="user rubric", cache_breakpoint=True),
                ContentText(text="item"),
            ]
        ),
    ]
    request = await _responses_request("gpt-5.6", input)
    assert "prompt_cache_options" not in request
    assert _tagged_input_texts(request["input"]) == []


@pytest.mark.anyio
async def test_responses_mark_on_agent_message_internal_falls_back_whole_request() -> (
    None
):
    # R4: a stashed Codex agent_message is replayed verbatim too, bypassing
    # the same conversion path
    agent_message_item: dict[str, Any] = {
        "type": "agent_message",
        "role": "assistant",
        "content": [{"type": "input_text", "text": "hi"}],
    }
    bridged_message = ChatMessageUser(
        content=[
            ContentText(
                text="stale",
                cache_breakpoint=True,
                internal={"agent_message": agent_message_item},
            )
        ]
    )
    input: list[ChatMessage] = [
        bridged_message,
        ChatMessageUser(
            content=[
                ContentText(text="user rubric", cache_breakpoint=True),
                ContentText(text="item"),
            ]
        ),
    ]
    request = await _responses_request("gpt-5.6", input)
    assert "prompt_cache_options" not in request
    assert _tagged_input_texts(request["input"]) == []


@pytest.mark.anyio
async def test_responses_initial_system_gets_automatic_checkpoint() -> None:
    # R5, Responses API: see test_completions_initial_system_gets_automatic_checkpoint
    input: list[ChatMessage] = [
        ChatMessageSystem(content="stable instructions"),
        ChatMessageUser(
            content=[
                ContentText(text="rubric", cache_breakpoint=True),
                ContentText(text="item"),
            ]
        ),
    ]
    request = await _responses_request("gpt-5.6", input)
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    developer_content = request["input"][0]["content"]
    assert developer_content == [
        {
            "type": "input_text",
            "text": "stable instructions",
            "prompt_cache_breakpoint": {"mode": "explicit"},
        }
    ]
    assert _tagged_input_texts(request["input"]) == [(0, 0), (1, 0)]


@pytest.mark.anyio
async def test_responses_callers_own_initial_system_mark_wins() -> None:
    # a caller's own mark on the initial system block must be authoritative
    # over its varying suffix — no later automatic system boundary is added
    input: list[ChatMessage] = [
        ChatMessageSystem(
            content=[
                ContentText(text="stable", cache_breakpoint=True),
                ContentText(text="varying"),
            ]
        ),
        ChatMessageUser(content="hi"),
    ]
    request = await _responses_request("gpt-5.6", input)
    assert request["prompt_cache_options"] == {"mode": "explicit"}
    developer_content = request["input"][0]["content"]
    assert [b["text"] for b in developer_content] == ["stable", "varying"]
    assert developer_content[0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert "prompt_cache_breakpoint" not in developer_content[1]


def _openai_api(model_name: str, **model_args: Any) -> OpenAIAPI:
    return OpenAIAPI(model_name=model_name, api_key="test-key", **model_args)


def _azure_api(model_name: str = "azure/gpt-5.6", **model_args: Any) -> OpenAIAPI:
    return OpenAIAPI(
        model_name=model_name,
        base_url="https://test.openai.azure.com",
        api_key="test-key",
        **model_args,
    )


async def _generate_and_capture_cache_flag(
    api: OpenAIAPI, monkeypatch: pytest.MonkeyPatch
) -> bool:
    """Call `api.generate()` and return the `supports_explicit_prompt_cache` it passed down."""
    captured: dict[str, bool] = {}

    async def fake_responses(*args: Any, **kwargs: Any) -> ModelOutput:
        captured["value"] = kwargs["supports_explicit_prompt_cache"]
        return ModelOutput.from_content(model=kwargs["model_name"], content="ok")

    async def fake_completions(*args: Any, **kwargs: Any) -> ModelOutput:
        captured["value"] = kwargs["supports_explicit_prompt_cache"]
        return ModelOutput.from_content(model=kwargs["model_name"], content="ok")

    monkeypatch.setattr(
        "inspect_ai.model._providers.openai.generate_responses", fake_responses
    )
    monkeypatch.setattr(
        "inspect_ai.model._providers.openai.generate_completions", fake_completions
    )
    await api.generate(
        input=[ChatMessageUser(content="hi")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
    )
    return captured["value"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "use_responses", [False, True], ids=["completions", "responses"]
)
async def test_direct_openai_endpoint_supports_explicit_cache(
    monkeypatch: pytest.MonkeyPatch, use_responses: bool
) -> None:
    api = _openai_api("gpt-5.6", responses_api=use_responses)
    assert await _generate_and_capture_cache_flag(api, monkeypatch) is True


@pytest.mark.anyio
@pytest.mark.parametrize(
    "use_responses", [False, True], ids=["completions", "responses"]
)
async def test_azure_endpoint_declines_explicit_cache(
    monkeypatch: pytest.MonkeyPatch, use_responses: bool
) -> None:
    # explicit caching is verified only against the direct OpenAI endpoint;
    # Azure's support for prompt_cache_options/prompt_cache_breakpoint is
    # unverified, so the capability must not be forwarded there even though
    # the model name matches the gpt-5.6+ pattern
    api = _azure_api("azure/gpt-5.6", responses_api=use_responses)
    assert await _generate_and_capture_cache_flag(api, monkeypatch) is False


@pytest.mark.anyio
async def test_bedrock_endpoint_declines_explicit_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # same rationale as Azure above; Bedrock is unverified
    api = _openai_api("bedrock/gpt-5.6", responses_api=True)
    assert await _generate_and_capture_cache_flag(api, monkeypatch) is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    "use_responses", [False, True], ids=["completions", "responses"]
)
async def test_custom_base_url_endpoint_declines_explicit_cache(
    monkeypatch: pytest.MonkeyPatch, use_responses: bool
) -> None:
    # a custom base_url points OpenAIAPI at some other (unverified) gateway
    # even though it isn't Azure or Bedrock and the model name still matches
    # the gpt-5.6+ pattern
    api = _openai_api(
        "gpt-5.6",
        base_url="https://gateway.example.com/v1",
        responses_api=use_responses,
    )
    assert await _generate_and_capture_cache_flag(api, monkeypatch) is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    "use_responses", [False, True], ids=["completions", "responses"]
)
async def test_openai_base_url_env_var_declines_explicit_cache(
    monkeypatch: pytest.MonkeyPatch, use_responses: bool
) -> None:
    # OPENAI_BASE_URL is the same kind of override as an explicit base_url
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example.com/v1")
    api = _openai_api("gpt-5.6", responses_api=use_responses)
    assert await _generate_and_capture_cache_flag(api, monkeypatch) is False


# ---------------------------------------------------------------------------
# Live tests (--runapi, need OPENAI_API_KEY and access to the gpt-5.6 model)
# ---------------------------------------------------------------------------


# deterministic instruction: the model is asked to echo exactly one token
# derived from the varying tail, so the *content* of the answer (not just
# usage counters) can be asserted to have tracked the tail change.
_ECHO_INSTRUCTION = (
    "This message ends with a line 'TAIL: <n>'. Reply with only the digit n "
    "and nothing else — no words, no punctuation."
)
_LIVE_CONFIG = GenerateConfig(max_tokens=32, temperature=0.0)


def _echo_content(rubric: str, tail_digit: str) -> list[Content]:
    return [
        ContentText(text=f"{_ECHO_INSTRUCTION}\n\n{rubric}", cache_breakpoint=True),
        ContentText(text=f"TAIL: {tail_digit}"),
    ]


def _assert_route(model: Any, expected_responses_api: bool) -> None:
    """Assert which API route `model` actually resolved to.

    gpt-5 family models default to the Responses API when num_choices is
    unset (see OpenAIAPI.responses_preferred); assert the actual route
    rather than assuming it from the model name or an explicit kwarg alone.
    """
    api = model.api
    assert isinstance(api, OpenAIAPI)
    assert api.responses_api is expected_responses_api


@pytest.mark.anyio
@skip_if_no_openai
@skip_if_no_openai_model(_GPT_5_6_MODEL)
async def test_openai_explicit_cache_breakpoint_reuses_marked_prefix_completions() -> (
    None
):
    """A marked stable rubric is read from cache on a second Chat Completions call."""
    # gpt-5 family models default to the Responses API when num_choices is
    # unset (see OpenAIAPI.responses_preferred); force Chat Completions
    # explicitly so this test doesn't silently exercise the same route as
    # the Responses test below.
    model = get_model(
        f"openai/{_GPT_5_6_MODEL}", responses_api=False, config=_LIVE_CONFIG
    )
    _assert_route(model, False)
    rubric = _unique_rubric()

    out1 = await model.generate(
        input=[ChatMessageUser(content=_echo_content(rubric, "4"))]
    )
    out2 = await model.generate(
        input=[ChatMessageUser(content=_echo_content(rubric, "5"))]
    )

    assert out1.usage is not None and out2.usage is not None
    assert (out1.usage.input_tokens_cache_write or 0) > 0
    assert (out2.usage.input_tokens_cache_read or 0) > 0
    # same rubric read back, not rewritten, on the second call
    assert out2.usage.input_tokens_cache_read == out1.usage.input_tokens_cache_write
    # the varying tail is not written into the cached (marked) prefix
    assert (out2.usage.input_tokens_cache_write or 0) == 0
    # the varying tail deterministically changed the answer content
    assert "4" in out1.completion
    assert "5" in out2.completion


@pytest.mark.anyio
@skip_if_no_openai
@skip_if_no_openai_model(_GPT_5_6_MODEL)
async def test_openai_explicit_cache_breakpoint_reuses_marked_prefix_responses() -> (
    None
):
    """Same as above, routed through the Responses API."""
    model = get_model(
        f"openai/{_GPT_5_6_MODEL}", responses_api=True, config=_LIVE_CONFIG
    )
    _assert_route(model, True)
    rubric = _unique_rubric()

    out1 = await model.generate(
        input=[ChatMessageUser(content=_echo_content(rubric, "4"))]
    )
    out2 = await model.generate(
        input=[ChatMessageUser(content=_echo_content(rubric, "5"))]
    )

    assert out1.usage is not None and out2.usage is not None
    assert (out1.usage.input_tokens_cache_write or 0) > 0
    assert (out2.usage.input_tokens_cache_read or 0) > 0
    assert out2.usage.input_tokens_cache_read == out1.usage.input_tokens_cache_write
    # the varying tail is not written into the cached (marked) prefix
    assert (out2.usage.input_tokens_cache_write or 0) == 0
    assert "4" in out1.completion
    assert "5" in out2.completion


@pytest.mark.anyio
@skip_if_no_openai
async def test_openai_unsupported_model_with_mark_falls_back_without_error() -> None:
    """A mark on a pre-5.6 model must not error — it's silently dropped."""
    model = get_model(
        "openai/gpt-5.5", config=GenerateConfig(max_tokens=32, temperature=0.0)
    )
    out = await model.generate(
        input=[ChatMessageUser(content=_echo_content(_unique_rubric(n_words=50), "7"))]
    )
    assert "7" in out.completion


@pytest.mark.anyio
@skip_if_no_openai
@skip_if_no_openai_model(_GPT_5_6_MODEL)
@pytest.mark.parametrize(
    "responses_api", [False, True], ids=["completions", "responses"]
)
async def test_openai_initial_system_checkpoint_reused_across_changing_marked_prefix(
    responses_api: bool,
) -> None:
    """R5: the automatic initial-system checkpoint is reused even as the caller's own mark changes.

    The leading system block is left unmarked (so it gets Inspect's
    automatic checkpoint) while the user rubric — a *different* mark each
    call — cannot itself be read back. The second call's cache read must
    still be positive and strictly smaller than the first call's cache
    write, showing the reused amount is attributable only to the stable
    system prefix, not to the (changed, unreusable) rubric. Parametrized
    over both API routes: gpt-5 family models default to Responses when
    num_choices is unset, so the route must be forced explicitly rather
    than assumed from the model name.
    """
    model = get_model(
        f"openai/{_GPT_5_6_MODEL}", responses_api=responses_api, config=_LIVE_CONFIG
    )
    _assert_route(model, responses_api)
    system = ChatMessageSystem(content=_unique_rubric())

    async def call(rubric: str, tail_digit: str) -> ModelOutput:
        return await model.generate(
            input=[system, ChatMessageUser(content=_echo_content(rubric, tail_digit))]
        )

    out1 = await call(_unique_rubric(), "4")
    out2 = await call(_unique_rubric(), "5")

    assert out1.usage is not None and out2.usage is not None
    assert (out1.usage.input_tokens_cache_write or 0) > 0
    cache_read_2 = out2.usage.input_tokens_cache_read or 0
    assert cache_read_2 > 0
    # the rubric mark changed and can't be reused, so only the automatic
    # system checkpoint contributes to the second call's cache read
    assert cache_read_2 < (out1.usage.input_tokens_cache_write or 0)
    assert "4" in out1.completion
    assert "5" in out2.completion
