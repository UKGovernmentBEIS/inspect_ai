"""Regression tests for task-row column sizing in the textual TasksView.

The name/agent/model columns must size to the *displayed* text. Two prior bugs:

1. Widths defaulted to their MAX, so when ``init_tasks`` didn't seed them those
   maxes acted as a permanent floor.
2. Widths were measured from the raw name / full ``provider/model`` string,
   while the row renders the stripped display name (``task_display_name``) and
   the bare model name (``ModelName.name``) — so columns reserved space for
   text that is never shown (e.g. an ``inspect_evals/`` prefix, an ``openai/``
   provider), leaving a gap before the next column.
"""

from __future__ import annotations

import pytest
from test_helpers.utils import skip_if_trio
from textual.app import App, ComposeResult

from inspect_ai._display.core.display import TaskProfile, TaskSpec, TaskWithResult
from inspect_ai._display.textual.widgets.tasks import COLUMN_SPACING, TasksView
from inspect_ai.log import EvalConfig
from inspect_ai.model import GenerateConfig, ModelName

# a rendered column region is: content + COLUMN_SPACING (trailing) + 1 (CSS padding-left)
PAD = COLUMN_SPACING + 1


def _profile(name: str, agent: str | None, model: str = "openai/gpt-5") -> TaskProfile:
    return TaskProfile(
        name=name,
        file=None,
        model=ModelName(model),
        agent=agent,
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
        task_cancel=None,
    )


class _App(App):
    def compose(self) -> ComposeResult:
        yield TasksView()


def _col_widths(app: App) -> dict[str, int]:
    panel = app.query_one("#task-progress-panel")
    return {
        str(w.id): w.region.width
        for w in panel.children
        if w.id in ("task-description", "task-agent", "task-model")
    }


@skip_if_trio
@pytest.mark.anyio
async def test_columns_size_to_displayed_text() -> None:
    """Columns size to the rendered text, not the raw name / full model id."""
    app = _App()
    async with app.run_test(size=(200, 24)) as pilot:
        tv = app.query_one(TasksView)
        # raw name carries a package prefix; model carries a provider — neither
        # is shown, so neither should be reserved in the column width
        tv.add_task(
            TaskWithResult(
                _profile("inspect_evals/terminal_bench_2", "react", "openai/gpt-5"),
                None,
            )
        )
        await pilot.pause()
        widths = _col_widths(app)
        assert widths["task-description"] == len("terminal_bench_2") + PAD
        assert widths["task-agent"] == len("react") + PAD
        assert widths["task-model"] == len("gpt-5") + PAD


@skip_if_trio
@pytest.mark.anyio
async def test_columns_seeded_by_init_tasks_match_displayed_text() -> None:
    app = _App()
    async with app.run_test(size=(200, 24)) as pilot:
        tv = app.query_one(TasksView)
        # TaskSpec.name is already the display name (task_specs strips it)
        tv.init_tasks(
            [TaskSpec("terminal_bench_2", ModelName("openai/gpt-5"), "react")]
        )
        tv.add_task(
            TaskWithResult(_profile("inspect_evals/terminal_bench_2", "react"), None)
        )
        await pilot.pause()
        widths = _col_widths(app)
        assert widths["task-description"] == len("terminal_bench_2") + PAD
        assert widths["task-model"] == len("gpt-5") + PAD


@skip_if_trio
@pytest.mark.anyio
async def test_adding_wider_task_grows_existing_rows() -> None:
    """A later task with longer displayed name/agent/model widens earlier rows."""
    app = _App()
    async with app.run_test(size=(200, 24)) as pilot:
        tv = app.query_one(TasksView)
        tv.add_task(TaskWithResult(_profile("short", "react", "openai/gpt-5"), None))
        tv.add_task(
            TaskWithResult(
                _profile(
                    "a_much_longer_task_name",
                    "planner",
                    "anthropic/claude-sonnet-4-5",
                ),
                None,
            )
        )
        await pilot.pause()
        # first (short) row widened to match the longer task's displayed text
        first_panel = app.query("#task-progress-panel").first()
        first = {
            str(w.id): w.region.width
            for w in first_panel.children
            if w.id in ("task-description", "task-agent", "task-model")
        }
        assert first["task-description"] == len("a_much_longer_task_name") + PAD
        assert first["task-agent"] == len("planner") + PAD
        # displayed model "claude-sonnet-4-5" (17), not "anthropic/..." (27)
        assert tv.model_name_width == len("claude-sonnet-4-5") + COLUMN_SPACING
