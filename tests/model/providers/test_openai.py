import base64
import json

import pytest
from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.model._chat_message import ChatMessageSystem
from inspect_ai.model._openai import _parse_content_with_internal


@pytest.mark.anyio
@skip_if_no_openai
async def test_openai_api() -> None:
    model = get_model(
        "openai/gpt-3.5-turbo",
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=50,
            presence_penalty=0.0,
            logit_bias=dict([(42, 10), (43, -10)]),
            seed=None,
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


@pytest.mark.anyio
@skip_if_no_openai
async def test_openai_o_series_developer_messages() -> None:
    async def check_developer_messages(model_name: str):
        model = get_model(
            model_name,
            config=GenerateConfig(reasoning_effort="medium", parallel_tool_calls=True),
        )
        await model.generate(
            [
                ChatMessageSystem(content="I am a helpful assistant."),
                ChatMessageUser(content="What are you?"),
            ]
        )

    await check_developer_messages("openai/o1")
    await check_developer_messages("openai/o1-mini")
    await check_developer_messages("openai/o3-mini")


@pytest.mark.anyio
@skip_if_no_openai
async def test_openai_o_series_reasoning_effort() -> None:
    async def check_reasoning_effort(model_name: str, effort: str = "medium"):
        model = get_model(
            model_name,
            config=GenerateConfig(reasoning_effort=effort, parallel_tool_calls=True),  # type: ignore
        )
        message = ChatMessageUser(content="This is a test string. What are you?")
        response = await model.generate(input=[message])
        assert len(response.completion) >= 1

    await check_reasoning_effort("openai/o1")
    await check_reasoning_effort("openai/o1-mini")
    await check_reasoning_effort("openai/o3-mini")
    await check_reasoning_effort("openai/gpt-5-mini", "minimal")


@pytest.mark.anyio
@skip_if_no_openai
async def test_openai_o_series_max_tokens() -> None:
    async def check_max_tokens(model_name: str):
        model = get_model(
            model_name,
            config=GenerateConfig(max_tokens=4096, reasoning_effort="low"),
        )
        message = ChatMessageUser(content="This is a test string. What are you?")
        response = await model.generate(input=[message])
        assert len(response.completion) >= 1

    await check_max_tokens("openai/o1")
    await check_max_tokens("openai/o1-mini")
    await check_max_tokens("openai/o3-mini")


@skip_if_no_openai
def test_openai_flex_requests():
    log = eval(
        Task(),
        model="openai/o4-mini",
        model_args=dict(service_tier="flex", client_timeout=1200),
    )[0]
    assert log.status == "success"


@skip_if_no_openai
def test_openai_flex_requests_not_available():
    log = eval(
        Task(),
        model="openai/gpt-4o",
        model_args=dict(service_tier="flex", client_timeout=1200),
    )[0]
    assert log.status == "error"
    assert "Invalid service_tier argument" in str(log.error)


def encode_internal(obj):
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("utf-8")


# Valid cases
@pytest.mark.parametrize(
    "s,exp_content,exp_internal",
    [
        # Tag at start
        (
            f"<internal>{encode_internal({'foo': 1})}</internal>rest of content.",
            "rest of content.",
            {"foo": 1},
        ),
        # Tag in middle
        (
            f"before <internal>{encode_internal([1, 2, 3])}</internal> after",
            "before  after",
            [1, 2, 3],
        ),
        # Tag at end
        (
            f"content <internal>{encode_internal('bar')}</internal>",
            "content",
            "bar",
        ),
        # No tag
        ("no internal tag here", "no internal tag here", None),
        # Malformed tag (no close)
        ("<internal>notclosed", "<internal>notclosed", None),
    ],
)
def test_parse_content_with_internal_valid(s, exp_content, exp_internal):
    content, internal = _parse_content_with_internal(s)
    assert content == exp_content
    assert internal == exp_internal


invalid_utf8_bytes = b"\xff\xfe\xfd"
invalid_utf8_b64 = base64.b64encode(invalid_utf8_bytes).decode("utf-8")


@pytest.mark.parametrize(
    "s,expected_exception",
    [
        # Valid base64 that decodes to invalid UTF-8 (e.g., bytes that are not valid UTF-8)
        ("<internal>" + invalid_utf8_b64 + "</internal>content", UnicodeDecodeError),
        # Invalid JSON after base64 decoding
        (
            f"<internal>{base64.b64encode(b'invalid json').decode('utf-8')}</internal>content",
            json.JSONDecodeError,
        ),
    ],
)
def test_parse_content_with_internal_invalid_encoding(s, expected_exception):
    with pytest.raises(expected_exception):
        _parse_content_with_internal(s)
