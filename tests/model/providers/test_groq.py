from typing import Any, Literal

import pytest
from groq.types.chat import ChatCompletionChunk
from pydantic import BaseModel
from test_helpers.utils import skip_if_no_groq

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    ResponseSchema,
    get_model,
)
from inspect_ai.model._providers.groq import (
    GroqAPI,
    chat_tool_choice,
    groq_completion_from_stream,
)
from inspect_ai.model._stream import (
    ModelStreamObserver,
    StreamReasoningEvent,
    StreamTextEvent,
    StreamToolCallEvent,
    model_stream_observer,
)
from inspect_ai.tool import ToolFunction
from inspect_ai.util import json_schema


@skip_if_no_groq
async def test_core_groq_api() -> None:
    model = get_model(
        "groq/openai/gpt-oss-20b",
        config=GenerateConfig(
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


def test_chat_tool_choice_any_maps_to_required() -> None:
    # Inspect's tool_choice "any" means "use at least one tool" (force a tool call). Groq is
    # OpenAI-compatible, where the value that forces a call is "required" ("auto" lets the
    # model skip the tool), matching the openai/azureai/bedrock/mistral providers.
    assert chat_tool_choice("any") == "required"


def test_chat_tool_choice_other_values_pass_through() -> None:
    assert chat_tool_choice("auto") == "auto"
    assert chat_tool_choice("none") == "none"
    assert chat_tool_choice(ToolFunction(name="my_tool")) == {
        "type": "function",
        "function": {"name": "my_tool"},
    }


class NounPhrase(BaseModel):
    noun_phrase: str


@skip_if_no_groq
async def test_groq_api_with_response_schema() -> None:
    model = get_model(
        "groq/openai/gpt-oss-20b",
        config=GenerateConfig(
            response_schema=ResponseSchema(
                name="noun_phrase_schema",
                json_schema=json_schema(NounPhrase),
                description="Noun Phrase",
                strict=True,
            ),
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


# -- Streaming (on_stream) ------------------------------------------------------


class _StreamCollector:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def __call__(self, event: Any) -> None:
        self.events.append(event)


def _groq_api(streaming: bool | Literal["auto"] = "auto") -> GroqAPI:
    return GroqAPI(model_name="llama-3.3-70b", api_key="test", streaming=streaming)


def test_groq_resolve_streaming_honors_on_stream() -> None:
    """Unset streaming is "auto": stream iff the caller passed on_stream."""
    config = GenerateConfig()
    collector = _StreamCollector()

    api = _groq_api()
    assert api.streaming is None
    assert api.resolve_streaming(config) is False
    with model_stream_observer(ModelStreamObserver("test", collector)):
        assert api.resolve_streaming(config) is True

        # auto mode declines requests carrying a response_schema
        schema_config = GenerateConfig(
            response_schema=ResponseSchema(
                name="noun_phrase_schema", json_schema=json_schema(NounPhrase)
            )
        )
        assert api.resolve_streaming(schema_config) is False
        # ...but an explicit opt-in still streams them
        assert _groq_api(streaming=True).resolve_streaming(schema_config) is True

        # auto mode declines compound models (server-side executed_tools are
        # not carried by the stream accumulator)
        compound = GroqAPI(model_name="groq/compound", api_key="test")
        assert compound.resolve_streaming(config) is False

        # explicit opt-out wins over an on_stream callback
        assert _groq_api(streaming=False).resolve_streaming(config) is False

    # explicit opt-in streams without a callback
    assert _groq_api(streaming=True).resolve_streaming(config) is True

    # -M args are YAML-parsed so "auto" arrives as a string; a typo'd value
    # raises rather than silently forcing streaming on or off
    assert _groq_api(streaming="auto").streaming is None
    with pytest.raises(ValueError, match="streaming"):
        _groq_api(streaming="always")  # type: ignore[arg-type]


def _groq_chunk(payload: dict[str, Any]) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        dict(
            id="chatcmpl-1",
            object="chat.completion.chunk",
            created=123,
            model="llama-3.3-70b",
        )
        | payload
    )


async def _chunk_iter(chunks: list[ChatCompletionChunk]) -> Any:
    for chunk in chunks:
        yield chunk


async def test_groq_completion_from_stream() -> None:
    """The stream accumulator reconstructs the completion and reports deltas."""
    chunks = [
        _groq_chunk(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(role="assistant", reasoning="hmm"),
                        finish_reason=None,
                    )
                ]
            )
        ),
        _groq_chunk(
            dict(choices=[dict(index=0, delta=dict(content="hel"), finish_reason=None)])
        ),
        _groq_chunk(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(
                            tool_calls=[
                                dict(
                                    index=0,
                                    type="function",
                                    id="call_1",
                                    function=dict(name="bash", arguments="{"),
                                )
                            ]
                        ),
                        finish_reason=None,
                    )
                ]
            )
        ),
        # continuation fragment: id/name arrive only on a call's first fragment
        _groq_chunk(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(
                            tool_calls=[
                                dict(index=0, function=dict(arguments='"cmd": "ls"}'))
                            ]
                        ),
                        finish_reason="tool_calls",
                    )
                ]
            )
        ),
        # final chunk carries usage under x_groq
        _groq_chunk(
            dict(
                choices=[],
                x_groq=dict(
                    id="req_1",
                    usage=dict(prompt_tokens=3, completion_tokens=7, total_tokens=10),
                ),
            )
        ),
    ]

    collector = _StreamCollector()
    with model_stream_observer(ModelStreamObserver("test", collector)):
        completion = await groq_completion_from_stream(_chunk_iter(chunks))

    # final completion accumulated from the chunks
    choice = completion.choices[0]
    assert choice.message.reasoning == "hmm"
    assert choice.message.content == "hel"
    assert choice.finish_reason == "tool_calls"
    tool_calls = choice.message.tool_calls
    assert tool_calls is not None and tool_calls[0].id == "call_1"
    assert tool_calls[0].function.name == "bash"
    assert tool_calls[0].function.arguments == '{"cmd": "ls"}'
    assert completion.usage is not None and completion.usage.total_tokens == 10

    # deltas were reported to on_stream (with tool fragments attributed)
    assert [type(e) for e in collector.events] == [
        StreamReasoningEvent,
        StreamTextEvent,
        StreamToolCallEvent,
        StreamToolCallEvent,
    ]
    assert collector.events[0].reasoning == "hmm"
    assert collector.events[1].text == "hel"
    assert collector.events[2].arguments == "{"
    assert collector.events[3].id == "call_1"
    assert collector.events[3].function == "bash"
    assert collector.events[3].arguments == '"cmd": "ls"}'

    # the accumulated completion flows through existing response parsing
    api = _groq_api()
    choices = api._chat_choices_from_response(completion, [])
    assert choices[0].stop_reason == "tool_calls"


async def test_groq_completion_from_stream_empty() -> None:
    with pytest.raises(RuntimeError, match="without delivering any chunks"):
        await groq_completion_from_stream(_chunk_iter([]))


@skip_if_no_groq
async def test_groq_stream_end_to_end() -> None:
    """Passing on_stream alone enables streaming and reconstructs the output."""
    events: list[Any] = []

    async def collect(event: Any) -> None:
        events.append(event)

    model = get_model(
        "groq/openai/gpt-oss-20b",
        config=GenerateConfig(max_tokens=1024, temperature=0.0),
    )
    response = await model.generate(
        input=[ChatMessageUser(content="This is a test string. What are you?")],
        on_stream=collect,
    )
    assert len(response.completion) >= 1
    streamed = "".join(e.text for e in events if isinstance(e, StreamTextEvent))
    assert streamed == response.completion
