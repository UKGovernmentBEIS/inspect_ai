from inspect_ai.agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model import ChatMessage, ChatMessageUser, ModelOutput


def conversation(prefix: str, count: int) -> list[ChatMessage]:
    return [ChatMessageUser(content=f"{prefix} {index}") for index in range(count)]


def output(model: str, content: str) -> ModelOutput:
    return ModelOutput.from_content(model, content)


async def test_track_state_does_not_replace_primary_with_longer_side_model() -> None:
    bridge = AgentBridge(AgentState(messages=[]))
    primary_input = conversation("primary", 2)
    primary_output = output("openai/agent", "primary response")

    await bridge._track_state(primary_input, primary_output, "openai/agent")

    side_input = conversation("reviewer", 8)
    side_output = output("openai/codex-auto-review", "reviewer verdict")
    await bridge._track_state(side_input, side_output, "openai/codex-auto-review")

    assert bridge.state.messages == primary_input + [primary_output.message]
    assert bridge.state.output is primary_output


async def test_track_state_adopts_growing_primary_model_conversation() -> None:
    bridge = AgentBridge(AgentState(messages=[]))
    initial_input = conversation("primary", 1)
    initial_output = output("openai/agent", "initial response")
    await bridge._track_state(initial_input, initial_output, "openai/agent")

    growing_input = conversation("primary", 2)
    growing_output = output("openai/agent", "growing response")
    await bridge._track_state(growing_input, growing_output, "openai/agent")

    assert bridge.state.messages == growing_input + [growing_output.message]
    assert bridge.state.output is growing_output


async def test_track_state_recovers_compacted_primary_model_conversation() -> None:
    bridge = AgentBridge(AgentState(messages=[]))
    original_input = conversation("primary", 4)
    original_output = output("openai/agent", "original response")
    await bridge._track_state(original_input, original_output, "openai/agent")

    compacted_input = conversation("primary", 1)
    compacted_output = output("openai/agent", "compacted response")
    await bridge._track_state(compacted_input, compacted_output, "openai/agent")

    recovered_input = conversation("primary", 2)
    recovered_output = output("openai/agent", "recovered response")
    await bridge._track_state(recovered_input, recovered_output, "openai/agent")

    assert bridge.state.messages == recovered_input + [recovered_output.message]
    assert bridge.state.output is recovered_output


async def test_track_state_preserves_legacy_behavior_without_model_identifier() -> None:
    bridge = AgentBridge(AgentState(messages=[]))
    initial_input = conversation("first", 1)
    initial_output = output("openai/first", "first response")
    await bridge._track_state(initial_input, initial_output)

    longer_input = conversation("second", 2)
    longer_output = output("openai/second", "second response")
    await bridge._track_state(longer_input, longer_output)

    assert bridge.state.messages == longer_input + [longer_output.message]
    assert bridge.state.output is longer_output
