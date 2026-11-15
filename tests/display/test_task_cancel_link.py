"""Tests for the textual task row's cancel link and dialog."""

from __future__ import annotations

import pytest
from test_helpers.utils import skip_if_trio
from textual.app import App, ComposeResult

from inspect_ai._display.core.display import CancelType, TaskCancel, TaskProfile
from inspect_ai._display.textual.widgets.tasks import CancelDialog, CancelLink
from inspect_ai.log import EvalConfig
from inspect_ai.model import GenerateConfig, ModelName


def _task_cancel(cancel_type: CancelType) -> TaskCancel:
    task_cancel = TaskCancel(can_retry=True, apply=lambda _: None)
    task_cancel.request(cancel_type)
    return task_cancel


def _profile(task_cancel: TaskCancel) -> TaskProfile:
    return TaskProfile(
        name="task",
        file=None,
        model=ModelName("mockllm/model"),
        agent=None,
        dataset="(samples)",
        scorer="accuracy",
        samples=10,
        steps=10,
        eval_config=EvalConfig(),
        task_args={},
        generate_config=GenerateConfig(),
        tags=None,
        log_location="x",
        task_id="id",
        task_cancel=task_cancel,
    )


class _App(App[None]):
    def __init__(self, profile: TaskProfile) -> None:
        super().__init__()
        self._profile = profile

    def compose(self) -> ComposeResult:
        yield CancelLink(self._profile)


@skip_if_trio
@pytest.mark.anyio
async def test_escape_keeps_pending_cancel() -> None:
    """Closing the dialog without confirming leaves an existing cancel in place."""
    task_cancel = _task_cancel("drain")
    app = _App(_profile(task_cancel))
    async with app.run_test() as pilot:
        await pilot.click(CancelLink)
        await pilot.pause()
        assert isinstance(app.screen, CancelDialog)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, CancelDialog)
    assert task_cancel.cancel_type == "drain"


@skip_if_trio
@pytest.mark.anyio
async def test_confirm_cancels_task() -> None:
    task_cancel = _task_cancel(None)
    app = _App(_profile(task_cancel))
    async with app.run_test() as pilot:
        await pilot.click(CancelLink)
        await pilot.pause()
        await pilot.click("#cancel-confirm")
        await pilot.pause()
    assert task_cancel.cancel_type == "abort"
