"""Tests for the Textual `QuestionInputPanel` and the shared `ElicitationForm`.

Two layers:
- Pilot tests (`run_test`) mount the widgets inside a minimal Textual App
  and drive Submit/Decline button presses + form-value entry through the
  real event loop.
- Pure-function tests for `_dispatch_builtin` selection use mocking to
  flip the "active task screen" precondition without booting an App.
"""

from __future__ import annotations

from typing import Any

import pytest
from acp.schema import (
    ElicitationBooleanPropertySchema,
    ElicitationIntegerPropertySchema,
    ElicitationMultiSelectPropertySchema,
    ElicitationNumberPropertySchema,
    ElicitationSchema,
    ElicitationStringPropertySchema,
    EnumOption,
    TitledMultiSelectItems,
)
from test_helpers.utils import skip_if_trio
from textual.app import App, ComposeResult
from textual.widgets import Checkbox, Input, Select, SelectionList

from inspect_ai._util.textual.form import ElicitationForm
from inspect_ai.input._types import InputRequest, InputResult
from inspect_ai.input.manager import (
    HumanQuestionManager,
    PendingQuestionRequest,
    init_human_question_manager,
)
from inspect_ai.input.panel import (
    QuestionInputPanel,
    QuestionRequestActions,
    QuestionRequestBody,
)
from inspect_ai.util._panel import InputPanel


class _StubHost(InputPanel.Host):
    """Test-only `InputPanel.Host` — records calls without touching the DOM."""

    def __init__(self) -> None:
        self.title: str | None = None
        self.active = False
        self.closed = False

    def set_title(self, title: str) -> None:
        self.title = title

    def activate(self) -> None:
        self.active = True

    def deactivate(self) -> None:
        self.active = False

    def close(self) -> None:
        self.closed = True


class _PanelApp(App[None]):
    """Minimal App that hosts a single `QuestionInputPanel`."""

    def __init__(self) -> None:
        super().__init__()
        self.host = _StubHost()
        self.panel = QuestionInputPanel(self.host)

    def compose(self) -> ComposeResult:
        yield self.panel


def _request_string(*, required: bool = True) -> InputRequest:
    return InputRequest(
        message="What's your name?",
        schema=ElicitationSchema(
            properties={
                "name": ElicitationStringPropertySchema(type="string", title="Name"),
            },
            required=["name"] if required else [],
        ),
    )


def _request_kitchen_sink() -> InputRequest:
    return InputRequest(
        message="Please fill out the form",
        schema=ElicitationSchema(
            properties={
                "name": ElicitationStringPropertySchema(
                    type="string", title="Name", min_length=2
                ),
                "color": ElicitationStringPropertySchema(
                    type="string",
                    title="Color",
                    one_of=[
                        EnumOption(const="r", title="Red"),
                        EnumOption(const="b", title="Blue"),
                    ],
                ),
                "count": ElicitationIntegerPropertySchema(
                    type="integer", title="Count", minimum=1, maximum=10
                ),
                "ratio": ElicitationNumberPropertySchema(type="number", title="Ratio"),
                "confirm": ElicitationBooleanPropertySchema(
                    type="boolean", title="Confirm"
                ),
                "tags": ElicitationMultiSelectPropertySchema(
                    type="array",
                    title="Tags",
                    items=TitledMultiSelectItems(
                        any_of=[
                            EnumOption(const="a", title="Alpha"),
                            EnumOption(const="b", title="Beta"),
                        ]
                    ),
                ),
            },
            required=["name", "color", "count", "confirm"],
        ),
    )


def _set_input_value(input_widget: Input, value: str) -> None:
    """Set an `Input` value without going through user keystrokes."""
    input_widget.value = value


# ---------------------------------------------------------------------------
# ElicitationForm — per-field rendering and `collect`
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_form_renders_widget_per_property_type() -> None:
    request = _request_kitchen_sink()

    class FormApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ElicitationForm(request.schema)

    app = FormApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(ElicitationForm)
        assert len(form.query(Input)) == 3  # name, count, ratio
        assert len(form.query(Select)) == 1  # color
        assert len(form.query(Checkbox)) == 1  # confirm
        assert len(form.query(SelectionList)) == 1  # tags


@skip_if_trio
@pytest.mark.anyio
async def test_form_collect_accepts_valid_values() -> None:
    request = _request_kitchen_sink()

    class FormApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ElicitationForm(request.schema)

    app = FormApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(ElicitationForm)
        inputs = list(form.query(Input))
        _set_input_value(inputs[0], "Jane")  # name
        _set_input_value(inputs[1], "3")  # count
        _set_input_value(inputs[2], "0.5")  # ratio
        form.query_one(Select).value = "r"
        form.query_one(Checkbox).value = True
        form.query_one(SelectionList).select_all()
        await pilot.pause()

        values, errors = form.collect()
        assert errors == {}
        assert values == {
            "name": "Jane",
            "color": "r",
            "count": 3,
            "ratio": 0.5,
            "confirm": True,
            "tags": ["a", "b"],
        }


@skip_if_trio
@pytest.mark.anyio
async def test_form_collect_reports_required_missing() -> None:
    request = _request_kitchen_sink()

    class FormApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ElicitationForm(request.schema)

    app = FormApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(ElicitationForm)
        # leave required fields blank
        values, errors = form.collect()
        assert values is None
        assert "name" in errors
        assert "count" in errors


@skip_if_trio
@pytest.mark.anyio
async def test_form_collect_reports_constraint_violations() -> None:
    request = _request_kitchen_sink()

    class FormApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ElicitationForm(request.schema)

    app = FormApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(ElicitationForm)
        inputs = list(form.query(Input))
        _set_input_value(inputs[0], "J")  # name too short (min_length=2)
        _set_input_value(inputs[1], "99")  # count over maximum (10)
        form.query_one(Select).value = "r"
        await pilot.pause()

        values, errors = form.collect()
        assert values is None
        assert "name" in errors and "characters" in errors["name"]
        assert "count" in errors and "<=" in errors["count"]


@skip_if_trio
@pytest.mark.anyio
async def test_form_show_errors_renders_messages() -> None:
    request = _request_string()

    class FormApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ElicitationForm(request.schema)

    app = FormApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(ElicitationForm)
        form.show_errors({"name": "bad"})
        await pilot.pause()
        assert any("bad" in str(s.render()) for s in form.query(".field-error"))
        form.clear_errors()
        await pilot.pause()
        for static in form.query(".field-error"):
            assert "bad" not in str(static.render())


@skip_if_trio
@pytest.mark.anyio
async def test_form_show_errors_focuses_first_failed_field() -> None:
    """First failed field gets focus + scroll on `show_errors`.

    Lands the user directly on the thing to fix; if the field is off-screen
    in a long form, the surrounding VerticalScroll scrolls it into view.
    """
    schema = ElicitationSchema(
        properties={
            "first": ElicitationStringPropertySchema(type="string", title="First"),
            "second": ElicitationStringPropertySchema(type="string", title="Second"),
            "third": ElicitationStringPropertySchema(type="string", title="Third"),
        },
        required=["first", "second", "third"],
    )

    class FormApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ElicitationForm(schema)

    app = FormApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(ElicitationForm)
        # First field fine; second and third blank → only "second" and "third"
        # in the error dict. The form should focus the "second" field.
        inputs = list(form.query(Input))
        inputs[0].value = "ok"
        await pilot.pause()
        form.show_errors({"second": "required", "third": "required"})
        await pilot.pause()
        assert app.focused is inputs[1]


@skip_if_trio
@pytest.mark.anyio
async def test_form_multiselect_toggles_multiple_items_via_keyboard() -> None:
    """Regression for multi-select being misinterpreted as single-select.

    Focuses the SelectionList, navigates between options with the arrow keys,
    and presses space on two different options. Both should be selected.
    """
    schema = ElicitationSchema(
        properties={
            "tags": ElicitationMultiSelectPropertySchema(
                type="array",
                title="Tags",
                items=TitledMultiSelectItems(
                    any_of=[
                        EnumOption(const="a", title="Alpha"),
                        EnumOption(const="b", title="Beta"),
                        EnumOption(const="c", title="Gamma"),
                    ]
                ),
            ),
        },
    )

    class FormApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ElicitationForm(schema)

    app = FormApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        selection_list = app.query_one(SelectionList)
        selection_list.focus()
        await pilot.pause()

        # Toggle the first option, jump two rows down, toggle the third.
        await pilot.press("space")  # toggles "a"
        await pilot.press("down", "down")
        await pilot.press("space")  # toggles "c"
        await pilot.pause()

        form = app.query_one(ElicitationForm)
        values, errors = form.collect()
        assert errors == {}
        assert values == {"tags": ["a", "c"]}


@skip_if_trio
@pytest.mark.anyio
async def test_form_optional_boolean_blank_is_omitted() -> None:
    """Optional booleans with no default render as a 3-state Select.

    Leaving the Select blank must drop the property from the result
    (matching the console handler's `test_optional_boolean_blank_omits`).
    """
    schema = ElicitationSchema(
        properties={
            "flag": ElicitationBooleanPropertySchema(type="boolean", title="Flag"),
        },
        # not required, no default → tri-state
    )

    class FormApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ElicitationForm(schema)

    app = FormApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(ElicitationForm)
        # Sanity: tri-state booleans render as a Select, not a Checkbox.
        assert len(form.query(Select)) == 1
        assert len(form.query(Checkbox)) == 0

        # Leave it blank → field omitted.
        values, errors = form.collect()
        assert errors == {}
        assert values == {}

        # Pick "Yes" → value is True and key is present.
        select = form.query_one(Select)
        select.value = True
        await pilot.pause()
        values, errors = form.collect()
        assert errors == {}
        assert values == {"flag": True}


@skip_if_trio
@pytest.mark.anyio
async def test_form_required_boolean_uses_checkbox() -> None:
    """Required boolean (or one with a default) keeps the simple Checkbox."""
    schema = ElicitationSchema(
        properties={
            "flag": ElicitationBooleanPropertySchema(type="boolean", title="Flag"),
        },
        required=["flag"],
    )

    class FormApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ElicitationForm(schema)

    app = FormApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(ElicitationForm)
        assert len(form.query(Checkbox)) == 1
        assert len(form.query(Select)) == 0

        values, errors = form.collect()
        assert errors == {}
        assert values == {"flag": False}


# ---------------------------------------------------------------------------
# QuestionInputPanel — submit / decline / queue lifecycle
# ---------------------------------------------------------------------------


def _post_pending(manager: HumanQuestionManager, request: InputRequest) -> str:
    return manager.request_question(request)


@skip_if_trio
@pytest.mark.anyio
async def test_panel_submit_resolves_with_accepted() -> None:
    import anyio

    init_human_question_manager()
    from inspect_ai.input.manager import human_question_manager

    manager = human_question_manager()
    holder: dict[str, InputResult] = {}

    async def wait(qid: str) -> None:
        holder["result"] = await manager.wait_for_question(qid)

    app = _PanelApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        question_id = manager.request_question(_request_string())
        await pilot.pause()

        async with anyio.create_task_group() as tg:
            tg.start_soon(wait, question_id)
            await anyio.sleep(0)  # let waiter capture the Future

            body = app.panel.query_one(QuestionRequestBody)
            form = body.form()
            assert form is not None
            _set_input_value(form.query_one(Input), "Sam")

            actions = app.panel.query_one(QuestionRequestActions)
            await pilot.click(f"#{actions.SUBMIT_QUESTION}")
            await pilot.pause()

    result = holder["result"]
    assert result.outcome == "accepted"
    assert result.content == {"name": "Sam"}


@skip_if_trio
@pytest.mark.anyio
async def test_panel_decline_resolves_with_declined() -> None:
    import anyio

    init_human_question_manager()
    from inspect_ai.input.manager import human_question_manager

    manager = human_question_manager()
    holder: dict[str, InputResult] = {}

    async def wait(qid: str) -> None:
        holder["result"] = await manager.wait_for_question(qid)

    app = _PanelApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        question_id = manager.request_question(_request_string())
        await pilot.pause()

        async with anyio.create_task_group() as tg:
            tg.start_soon(wait, question_id)
            await anyio.sleep(0)

            actions = app.panel.query_one(QuestionRequestActions)
            await pilot.click(f"#{actions.DECLINE_QUESTION}")
            await pilot.pause()

    result = holder["result"]
    assert result.outcome == "declined"
    assert result.content is None


@skip_if_trio
@pytest.mark.anyio
async def test_panel_invalid_submit_keeps_panel_open_with_errors() -> None:
    init_human_question_manager()
    from inspect_ai.input.manager import human_question_manager

    manager = human_question_manager()

    app = _PanelApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        manager.request_question(_request_string(required=True))
        await pilot.pause()

        # Submit without filling out the required field.
        actions = app.panel.query_one(QuestionRequestActions)
        await pilot.click(f"#{actions.SUBMIT_QUESTION}")
        await pilot.pause()

        # Question still queued — manager hasn't resolved it.
        assert len(manager.question_requests()) == 1

        # Error message rendered against the field.
        form = app.panel.query_one(QuestionRequestBody).form()
        assert form is not None
        rendered = [str(s.render()) for s in form.query(".field-error")]
        assert any("required" in r.lower() for r in rendered)


@skip_if_trio
@pytest.mark.anyio
async def test_panel_visibility_tracks_queue() -> None:
    init_human_question_manager()
    from inspect_ai.input.manager import human_question_manager

    manager = human_question_manager()

    app = _PanelApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        # adding a question activates and shows the panel
        manager.request_question(_request_string())
        await pilot.pause()
        assert app.panel.visible is True
        assert app.host.active is True

        # withdraw the request → panel hides and deactivates
        question_id = manager.question_requests()[0][0]
        manager.withdraw_request(question_id)
        await pilot.pause()
        assert app.panel.visible is False
        assert app.host.active is False


@skip_if_trio
@pytest.mark.anyio
async def test_panel_queue_counter_reflects_pending_count() -> None:
    init_human_question_manager()
    from inspect_ai.input.manager import human_question_manager

    manager = human_question_manager()

    app = _PanelApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        manager.request_question(_request_string())
        manager.request_question(_request_string())
        await pilot.pause()
        assert "(2" in (app.host.title or "")


# ---------------------------------------------------------------------------
# _dispatch_builtin — panel vs. console selection
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_dispatch_falls_through_to_console_without_task_screen() -> None:
    """No task screen → panel raises NotImplementedError → falls to console."""
    request = _request_string()
    called: list[Any] = []

    async def fake_console(req: InputRequest) -> InputResult:
        called.append(req)
        return InputResult(outcome="accepted", content={"name": "from-console"})

    import inspect_ai.input.builtin as builtin_module
    import inspect_ai.input.console as console_module

    original = console_module.console_handler
    console_module.console_handler = fake_console  # type: ignore[assignment]
    try:
        result = await builtin_module._dispatch_builtin(request)
    finally:
        console_module.console_handler = original

    assert called == [request]
    assert result.outcome == "accepted"
    assert result.content == {"name": "from-console"}


# ---------------------------------------------------------------------------
# HumanQuestionManager — basic queue mechanics
# ---------------------------------------------------------------------------


def test_manager_round_trip() -> None:
    manager = HumanQuestionManager()
    request = InputRequest(
        message="m",
        schema=ElicitationSchema(properties={}),
    )
    qid = manager.request_question(request)
    pending = manager.question_requests()
    assert len(pending) == 1
    assert isinstance(pending[0][1], PendingQuestionRequest)

    manager.complete_question(qid, InputResult(outcome="declined"))
    assert manager.question_requests() == []


def test_manager_withdraw_is_idempotent() -> None:
    manager = HumanQuestionManager()
    qid = manager.request_question(
        InputRequest(message="m", schema=ElicitationSchema(properties={}))
    )
    manager.withdraw_request(qid)
    # second withdraw is a no-op (not a KeyError)
    manager.withdraw_request(qid)


def test_manager_on_change_callback_fires() -> None:
    manager = HumanQuestionManager()
    events: list[str] = []
    unsub = manager.on_change(lambda action: events.append(action))

    qid = manager.request_question(
        InputRequest(message="m", schema=ElicitationSchema(properties={}))
    )
    manager.complete_question(qid, InputResult(outcome="declined"))
    assert events == ["add", "remove"]

    unsub()
    manager.request_question(
        InputRequest(message="m", schema=ElicitationSchema(properties={}))
    )
    assert events == ["add", "remove"]  # unsubscribed, no further events
