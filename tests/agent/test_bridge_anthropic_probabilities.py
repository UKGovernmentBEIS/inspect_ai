"""Unit tests for Anthropic `probabilities` passthrough in the agent bridge.

An Anthropic client using the `probabilities-2024-07-31` beta sends a
`probabilities` request field alongside the beta header. The header survived
bridge filtering, but `generate_config_from_anthropic` copied only the fields in
`anthropic_extra_body_fields()`, so the directive was dropped before the host
model call; and the bridge rebuilt the reply with a fixed set of fields, so a
returned `probabilities` never reached the client either (#5210).

`probabilities` is not an Anthropic SDK keyword argument, so it travels in the
request's `extra_body` (like `context_management`) rather than in the typed
params. It is Anthropic-only, so it is not handed to a model from another
provider.
"""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import Message as AnthropicMessage
from test_helpers.utils import skip_if_no_anthropic_package

from inspect_ai import Task, eval
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.agent._bridge.anthropic_api_impl import generate_config_from_anthropic
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.model._providers.anthropic import AnthropicAPI
from inspect_ai.tool import ToolChoice, ToolInfo

ANSWER = "A"
PROBABILITIES_REQUEST: dict[str, Any] = {"type": "choices", "choices": ["A", "B"]}
PROBABILITIES_RESPONSE: dict[str, Any] = {"choices": [{"A": 0.9}, {"B": 0.1}]}


def anthropic_request(**extra: Any) -> dict[str, Any]:
    return {"model": "inspect", "messages": [], "max_tokens": 1, **extra}


# request extraction


def test_probabilities_extracted_into_extra_body() -> None:
    config = generate_config_from_anthropic(
        anthropic_request(probabilities=PROBABILITIES_REQUEST)
    )

    assert config.extra_body is not None
    assert config.extra_body["probabilities"] == PROBABILITIES_REQUEST


def test_no_probabilities_leaves_extra_body_unset() -> None:
    config = generate_config_from_anthropic(anthropic_request())

    assert config.extra_body is None


def test_probabilities_joins_existing_extra_body_fields() -> None:
    config = generate_config_from_anthropic(
        anthropic_request(
            probabilities=PROBABILITIES_REQUEST,
            metadata={"user_id": "u1"},
            service_tier="auto",
        )
    )

    assert config.extra_body == {
        "metadata": {"user_id": "u1"},
        "service_tier": "auto",
        "probabilities": PROBABILITIES_REQUEST,
    }


def test_probabilities_not_extracted_for_another_provider() -> None:
    config = generate_config_from_anthropic(
        anthropic_request(probabilities=PROBABILITIES_REQUEST), "openai"
    )

    assert config.extra_body is None


def test_other_extra_body_fields_survive_for_another_provider() -> None:
    config = generate_config_from_anthropic(
        anthropic_request(probabilities=PROBABILITIES_REQUEST, service_tier="auto"),
        "openai",
    )

    assert config.extra_body == {"service_tier": "auto"}


# provider forwarding: `probabilities` is not an SDK kwarg, so it must ride in
# extra_body or client.messages.create() would reject it


@skip_if_no_anthropic_package
def test_provider_routes_probabilities_to_extra_body_not_params() -> None:
    api = AnthropicAPI(model_name="claude-sonnet-4-5", api_key="test-key")

    params, extra_body, _headers, _betas = api.completion_config(
        GenerateConfig(extra_body={"probabilities": PROBABILITIES_REQUEST})
    )

    assert extra_body["probabilities"] == PROBABILITIES_REQUEST
    assert "probabilities" not in params


@skip_if_no_anthropic_package
def test_provider_still_routes_declared_fields_to_params() -> None:
    api = AnthropicAPI(model_name="claude-sonnet-4-5", api_key="test-key")

    params, extra_body, _headers, _betas = api.completion_config(
        GenerateConfig(extra_body={"service_tier": "auto"})
    )

    assert params["service_tier"] == "auto"
    assert "service_tier" not in extra_body


# bridge round trips


def run_bridge_test(solver: Agent, model_output: ModelOutput) -> None:
    task = Task(
        dataset=[Sample(input="hello", target="done")],
        solver=solver,
        scorer=None,
    )
    log = eval(task, model=get_model("mockllm/model", custom_outputs=[model_output]))[0]
    assert log.status == "success", (
        log.error.message if log.error else "eval did not succeed"
    )


async def bridge_message(extra_body: dict[str, Any] | None = None) -> AnthropicMessage:
    """Call the bridged Anthropic endpoint the way a probabilities client would.

    `probabilities` is not an SDK keyword argument, so a real client sends it in
    `extra_body`, which the SDK merges into the request JSON body.
    """
    async with AsyncAnthropic(api_key="test") as client:
        return await client.messages.create(
            model="inspect",
            max_tokens=1024,
            messages=[{"role": "user", "content": "hello"}],
            extra_body=extra_body,
            extra_headers={"anthropic-beta": "probabilities-2024-07-31"},
        )


@agent
def probabilities_response_agent() -> Agent:
    """Asserts the provider's probabilities field reaches the Anthropic client."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            message = await bridge_message()
            assert message.model_extra is not None
            assert message.model_extra["probabilities"] == PROBABILITIES_RESPONSE
            # only the probability field is copied out of the output metadata
            assert "trace_id" not in message.model_extra
            return bridge.state

    return execute


@agent
def no_probabilities_agent() -> Agent:
    """Asserts a reply without probabilities is unchanged."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            message = await bridge_message()
            assert not (message.model_extra or {}).get("probabilities")
            return bridge.state

    return execute


@skip_if_no_anthropic_package
def test_response_returns_only_probabilities_to_client() -> None:
    model_output = ModelOutput.from_content("mockllm/model", ANSWER)
    model_output.metadata = {
        "extra_body": {
            "probabilities": PROBABILITIES_RESPONSE,
            "trace_id": "should-not-be-copied",
        }
    }

    run_bridge_test(probabilities_response_agent(), model_output)


@skip_if_no_anthropic_package
def test_response_without_probabilities_is_unchanged() -> None:
    run_bridge_test(
        no_probabilities_agent(),
        ModelOutput.from_content("mockllm/model", ANSWER),
    )


# cross-provider gating


@skip_if_no_anthropic_package
def test_probabilities_not_forwarded_to_non_anthropic_model() -> None:
    seen: list[GenerateConfig] = []

    def capture(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        seen.append(config)
        return ModelOutput.from_content("mockllm/model", ANSWER)

    @agent
    def gate_agent() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state) as bridge:
                await bridge_message({"probabilities": PROBABILITIES_REQUEST})
                return bridge.state

        return execute

    task = Task(
        dataset=[Sample(input="hello", target="done")],
        solver=gate_agent(),
        scorer=None,
    )
    log = eval(task, model=get_model("mockllm/model", custom_outputs=capture))[0]
    assert log.status == "success", (
        log.error.message if log.error else "eval did not succeed"
    )

    assert seen, "model was never called"
    assert not (seen[0].extra_body or {}).get("probabilities")
