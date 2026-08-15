"""Tests for the bridged-generation discriminator (`in_bridge_model_generate`).

The ACP transport synthesizes tool-call cards for agent-bridge agents (which
emit no `ToolEvent`). It distinguishes bridged `ModelEvent`s from ordinary
react-style ones via `in_bridge_model_generate()`, read inside the synchronous
transcript subscriber callback. These tests pin both the context-var semantics
and the live guarantee that `bridge_generate` activates the flag for the
duration of the `ModelEvent` emission a subscriber observes.
"""

from inspect_ai.agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import (
    bridge_generate,
    bridge_model_generate,
    in_bridge_model_generate,
)
from inspect_ai.event import Event, ModelEvent
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    get_model,
)


def test_in_bridge_model_generate_default_false() -> None:
    assert in_bridge_model_generate() is False


def test_bridge_model_generate_sets_and_resets() -> None:
    assert in_bridge_model_generate() is False
    with bridge_model_generate():
        assert in_bridge_model_generate() is True
    assert in_bridge_model_generate() is False


def test_bridge_model_generate_nested() -> None:
    with bridge_model_generate():
        assert in_bridge_model_generate() is True
        with bridge_model_generate():
            assert in_bridge_model_generate() is True
        # inner exit must not clear the outer activation
        assert in_bridge_model_generate() is True
    assert in_bridge_model_generate() is False


def test_synchronous_callback_observes_flag() -> None:
    """A synchronously-invoked callback observes the flag (mirrors subscribers).

    The context var must be visible to a callback called inside the context and
    not outside it — exactly how the transcript subscriber observes it.
    """
    observed: list[bool] = []

    def callback() -> None:
        observed.append(in_bridge_model_generate())

    callback()
    with bridge_model_generate():
        callback()
    callback()

    assert observed == [False, True, False]


async def test_bridge_generate_flag_live_for_subscriber() -> None:
    """`bridge_generate` activates the flag for the ModelEvent a subscriber sees."""
    init_transcript(Transcript())
    observed: list[bool] = []

    def on_event(event: Event) -> None:
        if isinstance(event, ModelEvent):
            observed.append(in_bridge_model_generate())

    unsubscribe = transcript()._subscribe(on_event)
    try:
        model = get_model(
            "mockllm/model",
            custom_outputs=[ModelOutput.from_content("mockllm/model", "hi")],
        )
        bridge = AgentBridge(AgentState(messages=[]))
        await bridge_generate(
            bridge,
            model,
            [ChatMessageUser(content="hello")],
            [],
            None,
            GenerateConfig(),
        )
    finally:
        unsubscribe()

    assert observed, "expected at least one ModelEvent to reach the subscriber"
    assert all(observed), (
        f"expected the flag True for every bridged ModelEvent, got {observed}"
    )


async def test_direct_generate_flag_false_for_subscriber() -> None:
    """Control: a plain `model.generate()` (no bridge) leaves the flag False."""
    init_transcript(Transcript())
    observed: list[bool] = []

    def on_event(event: Event) -> None:
        if isinstance(event, ModelEvent):
            observed.append(in_bridge_model_generate())

    unsubscribe = transcript()._subscribe(on_event)
    try:
        model = get_model(
            "mockllm/model",
            custom_outputs=[ModelOutput.from_content("mockllm/model", "hi")],
        )
        await model.generate("hello")
    finally:
        unsubscribe()

    assert observed, "expected at least one ModelEvent to reach the subscriber"
    assert not any(observed), (
        f"expected the flag False for non-bridged ModelEvents, got {observed}"
    )
