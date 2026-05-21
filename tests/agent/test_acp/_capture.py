"""Test helper: a tool that captures the live ACP session for tests.

The factory pattern in Phase 4's plan: tests can't reach react()'s internal
``acp_session()`` from a sibling task (ContextVar task-inheritance issue).
We sidestep by running a tool *inside* react that captures
``current_acp_session()`` into a shared dict and signals a barrier event.
The producer task awaits the event and then drives the captured session
from outside.
"""

from typing import Any

import anyio

from inspect_ai.agent._acp import AcpSession, current_acp_session
from inspect_ai.dataset._dataset import Sample
from inspect_ai.log._samples import ActiveSample
from inspect_ai.log._transcript import Transcript
from inspect_ai.tool._tool import Tool, tool
from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer


def acp_test_active_sample(transcript: Transcript) -> ActiveSample:
    """Bare ``ActiveSample`` for tests that drive ``react()`` directly.

    ``react()`` opens ``checkpointer()``, which reads the active sample.
    Tests in this directory exercise react() outside the real eval
    harness, so they publish this bare ``ActiveSample`` (carrying a
    ``_NoopCheckpointer`` and the test's own transcript) on the
    ``_sample_active`` ContextVar.
    """
    return ActiveSample(
        task="t",
        log_location="mem://test",
        model="mockllm/model",
        sample=Sample(id=1, input="hi"),
        epoch=0,
        message_limit=None,
        token_limit=None,
        cost_limit=None,
        time_limit=None,
        working_limit=None,
        fails_on_error=False,
        transcript=transcript,
        sandboxes={},
        checkpointer=_NoopCheckpointer(),
        eval_id="eval-1",
    )


def capture_session_tool(captured: dict[str, AcpSession], ready: anyio.Event) -> Tool:
    """Return a tool that captures the live ``AcpSession`` on first call.

    Args:
        captured: shared dict the test reads after ``ready`` fires;
            captured["acp"] is set to the live session.
        ready: signal the test's producer awaits to know the session is
            captured and react has progressed past turn 1.
    """

    @tool
    def capture_session() -> Tool:
        async def execute() -> str:
            """Capture the active ACP session for the test producer."""
            captured["acp"] = current_acp_session()
            ready.set()
            return "captured"

        return execute

    return capture_session()


def slow_tool_with_event(release: anyio.Event) -> Tool:
    """Return a tool that awaits ``release`` before completing.

    Lets a test producer fire `cancel_current_turn` while the tool is
    mid-flight. ``release`` ensures the tool exits cleanly under
    normal completion paths too.
    """

    @tool
    def slow_tool() -> Tool:
        async def execute() -> str:
            """Block until released by the test, then return."""
            await release.wait()
            return "tool done"

        return execute

    return slow_tool()


async def slow_generate_factory(delay: float, then: Any) -> Any:
    """Return an async mockllm callable that sleeps `delay` then returns `then`."""

    async def _generate(input: Any, tools: Any, tool_choice: Any, config: Any) -> Any:
        await anyio.sleep(delay)
        return then

    return _generate
