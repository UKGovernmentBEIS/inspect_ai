"""Tests for the textual task row's cancel link and dialog."""

from __future__ import annotations

import pytest
from test_helpers.utils import skip_if_trio
from textual.app import App, ComposeResult

from inspect_ai._display.core.display import (
    CancelType,
    TaskCancel,
    TaskCancelled,
    TaskProfile,
    TaskWithResult,
)
from inspect_ai._display.textual.widgets.tasks import (
    CancelDialog,
    CancelLink,
    TaskProgressView,
)
from inspect_ai._display.textual.widgets.vscode import VSCodeLink
from inspect_ai._util.file import to_uri
from inspect_ai._util.vscode import VSCodeCommand
from inspect_ai.log import EvalConfig, EvalStats
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


class _RowApp(App[None]):
    def __init__(self, profile: TaskProfile) -> None:
        super().__init__()
        self.row = TaskProgressView(
            TaskWithResult(profile, None),
            description_width=10,
            agent_name_width=5,
            model_name_width=10,
            sample_count_width=5,
            display_metrics=False,
        )

    def compose(self) -> ComposeResult:
        yield self.row


@skip_if_trio
@pytest.mark.anyio
@pytest.mark.parametrize("log_location", ["", "x"])
async def test_row_hides_view_log_when_task_ends_with_no_log(
    monkeypatch: pytest.MonkeyPatch, log_location: str
) -> None:
    """A row whose task ended with no log no longer offers View Log."""
    monkeypatch.setattr(
        "inspect_ai._display.textual.widgets.vscode.can_execute_vscode_command",
        lambda command, context=None: True,
    )
    profile = _profile(_task_cancel(None))
    app = _RowApp(profile)
    async with app.run_test() as pilot:
        link = app.row.view_log_link
        assert isinstance(link, VSCodeLink) and link.display
        assert link.commands == [
            VSCodeCommand(command="inspect.openLogViewer", args=[to_uri("x")])
        ]
        # an abort before the task registered clears the location
        profile.log_location = log_location
        app.row.complete(TaskCancelled(0, EvalStats()))
        await pilot.pause()
        assert link.display is bool(log_location)
