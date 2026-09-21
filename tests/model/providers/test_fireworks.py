from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_helpers.utils import skip_if_no_fireworks

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@skip_if_no_fireworks
async def test_fireworks_compatible() -> None:
    model = get_model(
        # Fireworks retires models from serverless over time; this must be one
        # of the ids listed by GET /inference/v1/models
        "fireworks/accounts/fireworks/models/kimi-k3",
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
    message = ChatMessageUser(content="Hello Fireworks!")
    res = await model.generate(input=[message])
    assert len(res.completion) >= 1


# -- Prompt cache replica affinity (x-session-affinity) ------------------------


def _mock_completion() -> Any:
    """A minimal successful completion the provider can map to ModelOutput."""
    from openai.types.chat import ChatCompletion, ChatCompletionMessage
    from openai.types.chat.chat_completion import Choice

    return ChatCompletion.model_construct(
        id="chatcmpl-test",
        created=0,
        model="accounts/fireworks/models/kimi-k3",
        object="chat.completion",
        choices=[
            Choice.model_construct(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage.model_construct(
                    role="assistant", content="hello"
                ),
            )
        ],
    )


def _stub_fireworks(
    monkeypatch: pytest.MonkeyPatch, sample_uuid: str | None
) -> tuple[Any, MagicMock]:
    """A Fireworks API with a stubbed client and a stubbed active sample."""
    import inspect_ai.model._providers.fireworks as fireworks_module

    monkeypatch.setattr(
        fireworks_module, "sample_cache_affinity_key", lambda: sample_uuid
    )

    api = fireworks_module.FireworksAIAPI(
        model_name="accounts/fireworks/models/kimi-k3", api_key="test-key"
    )
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_mock_completion())
    api.client = client
    return api, client


async def _generate_once(api: Any, config: GenerateConfig | None = None) -> Any:
    return await api.generate(
        input=[ChatMessageUser(content="hello")],
        tools=[],
        tool_choice="none",
        config=config or GenerateConfig(),
    )


async def test_fireworks_session_affinity_sent_for_active_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sample's uuid pins its turns to one replica so the cache hits."""
    from inspect_ai.model._providers.fireworks import SESSION_AFFINITY_HEADER
    from inspect_ai.model._providers.util.hooks import HttpxHooks

    api, client = _stub_fireworks(monkeypatch, "sample-uuid-1")
    _output, model_call = await _generate_once(api)

    headers = client.chat.completions.create.await_args.kwargs["extra_headers"]
    assert headers[SESSION_AFFINITY_HEADER] == "sample-uuid-1"
    # the request id header the model call relies on survives the merge
    assert HttpxHooks.REQUEST_ID_HEADER in headers
    # and the session id is visible in the logged request for debugging
    assert model_call.request["extra_headers"][SESSION_AFFINITY_HEADER] == (
        "sample-uuid-1"
    )


async def test_fireworks_session_affinity_omitted_without_active_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outside a sample there is no conversation to key on, so no header."""
    from inspect_ai.model._providers.fireworks import SESSION_AFFINITY_HEADER

    api, client = _stub_fireworks(monkeypatch, None)
    await _generate_once(api)

    headers = client.chat.completions.create.await_args.kwargs["extra_headers"]
    assert SESSION_AFFINITY_HEADER not in headers


async def test_fireworks_session_affinity_overridable_by_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit extra_headers value wins over the provider default."""
    from inspect_ai.model._providers.fireworks import SESSION_AFFINITY_HEADER

    api, client = _stub_fireworks(monkeypatch, "sample-uuid-1")
    await _generate_once(
        api,
        GenerateConfig(extra_headers={SESSION_AFFINITY_HEADER: "caller-session"}),
    )

    headers = client.chat.completions.create.await_args.kwargs["extra_headers"]
    assert headers[SESSION_AFFINITY_HEADER] == "caller-session"


@skip_if_no_fireworks
def test_fireworks_prompt_cache_across_turns_live() -> None:
    """Concurrent samples' second turns read from the cache their first filled.

    Fireworks' cache lives on a single replica and serverless load balances, so
    without the affinity header a second turn almost never lands where its
    prefix is cached (measured: ~95% of prompt tokens uncached across 16
    concurrent conversations). Each sample gets a unique prefix, so a hit can
    only come from that sample's own first turn.
    """
    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.event import ModelEvent
    from inspect_ai.model._providers.fireworks import SESSION_AFFINITY_HEADER
    from inspect_ai.solver import Generate, TaskState, generate, solver

    @solver
    def second_turn():
        async def solve(state: TaskState, _generate: Generate) -> TaskState:
            state.messages.append(ChatMessageUser(content="Now reply with 'bye'."))
            return await _generate(state)

        return solve

    padding = "The quick brown fox jumps over the lazy dog. " * 400
    log = eval(
        Task(
            dataset=[
                Sample(input=f"[{i}] {padding}\nReply with 'hi'.") for i in range(4)
            ],
            solver=[generate(), second_turn()],
        ),
        model="fireworks/accounts/fireworks/models/kimi-k3",
        max_tokens=16,
    )[0]

    assert log.status == "success"
    assert log.samples is not None
    assert len(log.samples) == 4

    cache_hits = 0
    for sample in log.samples:
        model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
        assert len(model_events) == 2

        # both turns went out under this one sample's session id
        session_ids = set()
        for event in model_events:
            assert event.call is not None
            headers = cast(dict[str, str], event.call.request["extra_headers"])
            session_ids.add(headers[SESSION_AFFINITY_HEADER])
        assert session_ids == {sample.uuid}

        second = model_events[1].output.usage
        assert second is not None
        if second.input_tokens_cache_read:
            cache_hits += 1

    # the header makes this near-certain; allow slack for replica churn
    assert cache_hits >= 2
