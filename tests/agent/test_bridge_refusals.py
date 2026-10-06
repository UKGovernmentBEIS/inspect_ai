"""`fail_on_refusal` through the agent bridge.

`bridge_generate` is the bridge's retry loop: with `fail_on_refusal` set a
refusal raises out of `model.generate()` rather than returning, so the loop
catches it while `retry_refusals` attempts remain and re-raises the last one.
A refusal produced by a bridge `filter` never reaches `model.generate()`, so
the loop applies the option itself. For `sandbox_agent_bridge()` the raise
happens in the sandbox service task, where it cannot propagate, so it is
signalled to the bridge's monitor task instead.
"""

from __future__ import annotations

from typing import Any

import anyio
import pytest

from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.sandbox.bridge import _monitor_failure
from inspect_ai.agent._bridge.sandbox.service import _forward_provider_errors
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import bridge_generate
from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    GenerateConfig,
    GenerateFilter,
    Model,
    ModelOutput,
    ModelRefusalError,
    get_model,
)
from inspect_ai.util._anyio import inner_exception

REFUSAL = ModelOutput.from_content(
    model="mockllm/model", content="I cannot help.", stop_reason="content_filter"
)
ANSWER = ModelOutput.from_content(model="mockllm/model", content="Sure, here.")
FAIL = GenerateConfig(fail_on_refusal=True)


def _model(outputs: list[ModelOutput], generations: list[int]) -> Model:
    remaining = list(outputs)

    def custom_outputs(
        model_input: list[ChatMessage],
        tools: object,
        tool_choice: object,
        config: object,
    ) -> ModelOutput:
        generations.append(1)
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return get_model("mockllm/model", custom_outputs=custom_outputs)


async def _generate(
    outputs: list[ModelOutput],
    *,
    config: GenerateConfig = FAIL,
    retry_refusals: int | None = None,
    filter: GenerateFilter | None = None,
) -> tuple[ModelOutput, int]:
    """Drive `bridge_generate`; return the output and how many times the model ran."""
    generations: list[int] = []
    model = _model(outputs, generations)
    messages: list[ChatMessage] = [ChatMessageUser(content="hi")]
    bridge = AgentBridge(
        AgentState(messages=list(messages)),
        filter=filter,
        retry_refusals=retry_refusals,
    )
    output, _ = await bridge_generate(bridge, model, list(messages), [], None, config)
    return output, len(generations)


# ---------------------------------------------------------------------------
# bridge_generate
# ---------------------------------------------------------------------------


async def test_model_refusal_raises() -> None:
    with pytest.raises(ModelRefusalError, match="Model refusal"):
        await _generate([REFUSAL])


async def test_refusal_returned_when_option_off() -> None:
    output, generations = await _generate([REFUSAL], config=GenerateConfig())
    assert output.stop_reason == "content_filter"
    assert generations == 1


async def test_refusal_retries_then_succeeds() -> None:
    output, generations = await _generate([REFUSAL, ANSWER], retry_refusals=1)
    assert output.completion == "Sure, here."
    assert generations == 2


async def test_refusal_retries_exhausted_raises_last() -> None:
    with pytest.raises(ModelRefusalError):
        await _generate([REFUSAL, REFUSAL, ANSWER], retry_refusals=1)


async def test_filter_refusal_raises_without_calling_model() -> None:
    """A refusal produced by the filter bypasses model.generate(), so the loop raises."""

    async def refuse(
        model: str,
        input: list[ChatMessage],
        tools: Any,
        tool_choice: Any,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        return REFUSAL

    generations: list[int] = []
    model = _model([ANSWER], generations)
    bridge = AgentBridge(AgentState(messages=[]), filter=refuse)
    with pytest.raises(ModelRefusalError):
        await bridge_generate(
            bridge, model, [ChatMessageUser(content="hi")], [], None, FAIL
        )
    assert generations == []


async def test_filter_refusal_honours_model_config() -> None:
    """The filter path resolves fail_on_refusal from the model, like generate() does."""

    async def refuse(
        model: str,
        input: list[ChatMessage],
        tools: Any,
        tool_choice: Any,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        return REFUSAL

    model = get_model("mockllm/model", config=FAIL, memoize=False)
    bridge = AgentBridge(AgentState(messages=[]), filter=refuse)
    with pytest.raises(ModelRefusalError):
        await bridge_generate(
            bridge, model, [ChatMessageUser(content="hi")], [], None, GenerateConfig()
        )


async def test_filter_refusal_returned_when_option_off() -> None:
    async def refuse(
        model: str,
        input: list[ChatMessage],
        tools: Any,
        tool_choice: Any,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        return REFUSAL

    output, generations = await _generate(
        [ANSWER], config=GenerateConfig(), filter=refuse
    )
    assert output.stop_reason == "content_filter"
    assert generations == 0


async def test_filter_refusal_retries_then_model_answers() -> None:
    calls = 0

    async def refuse_once(
        model: str,
        input: list[ChatMessage],
        tools: Any,
        tool_choice: Any,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        nonlocal calls
        calls += 1
        return REFUSAL if calls == 1 else None

    output, generations = await _generate(
        [ANSWER], retry_refusals=1, filter=refuse_once
    )
    assert output.completion == "Sure, here."
    assert generations == 1


# ---------------------------------------------------------------------------
# sandbox bridge: the raise cannot propagate, so it is signalled to the monitor
# ---------------------------------------------------------------------------


def _sandbox_bridge() -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
    )


def test_request_fail_stores_first_error() -> None:
    bridge = _sandbox_bridge()
    first = ModelRefusalError(REFUSAL, "mockllm/model")
    bridge.request_fail(first)
    bridge.request_fail(RuntimeError("later"))
    assert bridge._failure_requested.is_set()
    assert bridge._failure is first


async def test_monitor_failure_raises_stored_error() -> None:
    bridge = _sandbox_bridge()
    bridge.request_fail(ModelRefusalError(REFUSAL, "mockllm/model", "grader"))
    with pytest.raises(ModelRefusalError, match="role grader"):
        await _monitor_failure(bridge)


async def test_sandbox_refusal_unwinds_the_bridge_task_group() -> None:
    """The shape `sandbox_agent_bridge` relies on.

    The model service wrapper answers the scaffold (an error payload, not a
    raise) and signals the bridge; the monitor task in the same task group then
    raises the refusal so the group unwinds with it, which is what reaches the
    sample runner.
    """
    bridge = _sandbox_bridge()

    async def refusing_generate(json_data: dict[str, Any]) -> dict[str, Any]:
        raise ModelRefusalError(REFUSAL, "mockllm/model")

    wrapped = _forward_provider_errors(refusing_generate, bridge)
    scaffold_replies: list[dict[str, Any]] = []

    async def scaffold() -> None:
        scaffold_replies.append(await wrapped({}))
        # the scaffold carries on regardless; the monitor tears the group down
        await anyio.sleep(30)

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(_monitor_failure, bridge)
            tg.start_soon(scaffold)
    except Exception as ex:
        error = inner_exception(ex)
    else:
        raise AssertionError("task group completed without the refusal")

    assert isinstance(error, ModelRefusalError)
    assert len(scaffold_replies) == 1
