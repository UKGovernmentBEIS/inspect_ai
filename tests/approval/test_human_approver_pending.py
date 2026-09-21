"""The sample is marked as waiting on a person whichever surface asks.

The record is what the control channel reports as ``activity`` — and it is the
*only* thing that reports the wait, because ``call_tool`` records the tool's
own event only once the approval resolves. Kept around the dispatch in
``human_approver`` rather than inside the ACP shim, so an eval running without
``--acp-server`` (panel or console) is not reported as silently idle for as
long as somebody is looking at the prompt.
"""

import asyncio
from typing import Any

import pytest

from inspect_ai.approval._approval import Approval
from inspect_ai.approval._human.approver import human_approver
from inspect_ai.log._samples import ActiveSample, PendingInteraction
from inspect_ai.tool._tool_call import ToolCall, ToolCallView


class _PendingSample(ActiveSample):
    """A real `ActiveSample` with its (heavy, irrelevant) constructor skipped."""

    def __init__(self) -> None:
        self._pending_interactions: list[PendingInteraction] = []
        self.acp_transport: Any = None


@pytest.fixture
def sample(monkeypatch: pytest.MonkeyPatch) -> _PendingSample:
    active = _PendingSample()
    monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: active)
    return active


def _no_acp(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ACP clients, so routing falls through to the in-proc surfaces."""
    from inspect_ai.approval._human import approver as approver_module

    async def none(**kwargs: object) -> Approval | None:
        return None

    monkeypatch.setattr(approver_module, "request_human_approval_via_acp", none)


@pytest.mark.parametrize("surface", ["panel", "console"])
async def test_an_in_proc_approval_marks_the_sample_as_waiting(
    monkeypatch: pytest.MonkeyPatch, sample: _PendingSample, surface: str
) -> None:
    from inspect_ai.approval._human import approver as approver_module

    _no_acp(monkeypatch)
    seen: list[tuple[PendingInteraction, ...]] = []
    held = asyncio.Event()

    async def panel(*args: object, **kwargs: object) -> Approval:
        if surface == "console":
            raise NotImplementedError
        seen.append(sample.pending_interactions)
        await held.wait()
        return Approval(decision="approve")

    def console(*args: object, **kwargs: object) -> Approval:
        seen.append(sample.pending_interactions)
        return Approval(decision="approve")

    monkeypatch.setattr(approver_module, "panel_approval", panel)
    monkeypatch.setattr(approver_module, "console_approval", console)
    held.set()

    call = ToolCall(id="t1", function="bash", arguments={"cmd": "ls"})
    result = await human_approver()("run it?", call, ToolCallView(), [])

    assert result.decision == "approve"
    # marked for the duration of the wait, naming the tool being decided...
    ((pending,),) = seen
    assert (pending.kind, pending.subject) == ("approval", "bash")
    # ...and cleared once the answer is in
    assert sample.pending_interactions == ()


async def test_a_wait_is_cleared_when_the_surface_raises(
    monkeypatch: pytest.MonkeyPatch, sample: _PendingSample
) -> None:
    # a sample left looking parked forever is worse than one never marked: it
    # is a decision a person will go looking for and not find
    from inspect_ai.approval._human import approver as approver_module

    _no_acp(monkeypatch)

    async def panel(*args: object, **kwargs: object) -> Approval:
        raise RuntimeError("display went away")

    monkeypatch.setattr(approver_module, "panel_approval", panel)

    with pytest.raises(RuntimeError):
        await human_approver()(
            "run it?",
            ToolCall(id="t1", function="bash", arguments={}),
            ToolCallView(),
            [],
        )

    assert sample.pending_interactions == ()


async def test_an_approval_outside_a_sample_is_not_recorded_anywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `awaiting_human` is a no-op with no active sample, which is what lets the
    # approver wrap unconditionally rather than branching
    from inspect_ai.approval._human import approver as approver_module

    _no_acp(monkeypatch)
    monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: None)

    async def panel(*args: object, **kwargs: object) -> Approval:
        raise NotImplementedError

    monkeypatch.setattr(approver_module, "panel_approval", panel)
    monkeypatch.setattr(
        approver_module,
        "console_approval",
        lambda *a, **k: Approval(decision="approve"),
    )

    result = await human_approver()(
        "run it?", ToolCall(id="t1", function="bash", arguments={}), ToolCallView(), []
    )
    assert result.decision == "approve"
