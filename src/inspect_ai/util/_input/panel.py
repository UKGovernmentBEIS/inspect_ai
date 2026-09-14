"""Textual panel handler for `ask_user`.

Mirrors `approval/_human/panel.py`: a queue-backed dynamic tab on the
full task display that renders the current question as an
`ElicitationForm` plus a Submit / Decline action row.
"""

from typing import Callable, Literal

import anyio
from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Button, Static
from typing_extensions import override

from inspect_ai._util.task import task_display_name
from inspect_ai._util.textual.form import ElicitationForm
from inspect_ai.util._panel import InputPanel, input_panel

from ._types import InputRequest, InputResult
from .manager import PendingQuestionRequest, human_question_manager


async def panel_handler(request: InputRequest) -> InputResult:
    """Submit a question to the Textual panel and await the answer.

    Raises `NotImplementedError` if no full Textual display is active —
    `_dispatch_builtin` translates that into a fall-through to the
    console handler.
    """
    from inspect_ai._display.core.active import _active_task_screen

    # No active task screen (e.g. REPL, unit test that didn't bootstrap an
    # eval): signal the dispatcher to fall through to the console handler.
    if _active_task_screen.get(None) is None:
        raise NotImplementedError("no active task screen")

    # Ensure the question panel is mounted on the task display. When the
    # display is not "full", `input_panel()` raises NotImplementedError,
    # which `_dispatch_builtin` catches to fall through to the console.
    await input_panel(QuestionInputPanel)

    questions = human_question_manager()
    id = questions.request_question(request)
    try:
        return await questions.wait_for_question(id)
    except anyio.get_cancelled_exc_class():
        questions.withdraw_request(id)
        raise


class QuestionInputPanel(InputPanel):
    DEFAULT_TITLE = "Question"

    DEFAULT_CSS = """
    QuestionInputPanel {
        layout: grid;
        grid-size: 1 3;
        grid-rows: auto 1fr auto;
    }
    """

    _questions: list[tuple[str, PendingQuestionRequest]] = []
    _unsubscribe: Callable[[], None] | None = None

    @override
    def compose(self) -> ComposeResult:
        yield QuestionRequestHeading()
        yield QuestionRequestBody()
        yield QuestionRequestActions()

    def on_mount(self) -> None:
        self._unsubscribe = human_question_manager().on_change(
            self.on_questions_changed
        )

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()

    def on_elicitation_form_submit_requested(
        self, event: ElicitationForm.SubmitRequested
    ) -> None:
        """Enter dispatch exhausted the form's empty required fields.

        Same path as clicking the Submit button; validation errors
        short-circuit and surface inline on the form. Submits from a
        form that is no longer the mounted one (a stale message posted
        just before a remount) are dropped.
        """
        event.stop()
        mounted = self.query_one(QuestionRequestBody).mounted()
        if mounted is None or event.form is not mounted[1]:
            return
        self.query_one(QuestionRequestActions).submit_current()

    def on_questions_changed(self, action: Literal["add", "remove"]) -> None:
        heading = self.query_one(QuestionRequestHeading)
        body = self.query_one(QuestionRequestBody)
        actions = self.query_one(QuestionRequestActions)
        self._questions = human_question_manager().question_requests()
        if len(self._questions) > 0:
            question_id, pending = self._questions[0]
            self.title = f"{self.DEFAULT_TITLE} ({len(self._questions):,})"
            heading.pending = pending
            body.pending = (question_id, pending)
            actions.question = (question_id, pending)
            if action == "add":
                self.activate()
                # Focus the first form field rather than the Submit button so
                # the user can immediately interact with the form. If we left
                # focus on Submit, pressing Space (e.g. to toggle a
                # SelectionList item) would activate the button and submit an
                # empty form. Tab order naturally carries the user from the
                # last field to Submit / Decline.
                body.focus_first()
            self.visible = True
        else:
            self.title = self.DEFAULT_TITLE
            heading.pending = None
            body.pending = None
            actions.question = None
            self.deactivate()
            self.visible = False


class QuestionRequestHeading(Static):
    DEFAULT_CSS = """
    QuestionRequestHeading {
        width: 1fr;
        background: $surface;
        margin-left: 1;
    }
    """

    pending: reactive[PendingQuestionRequest | None] = reactive(None)

    def render(self) -> RenderableType:
        p = self.pending
        if p is None:
            return ""

        # Two-column grid so the contextual `message` reads first on the left
        # in bold and the task/id/epoch metadata lines up on the far right.
        grid = Table.grid(expand=True)
        grid.add_column(justify="left", ratio=1, no_wrap=False)
        grid.add_column(justify="right", no_wrap=True)

        parts: list[str] = []
        if p.task:
            parts.append(task_display_name(p.task))
        if p.id:
            parts.append(str(p.id))
        if p.epoch:
            parts.append(str(p.epoch))
        metadata = Text("/".join(parts), style="dim") if parts else Text("")

        grid.add_row(Text(p.request.message, style="bold"), metadata)
        return grid


class QuestionRequestBody(Vertical):
    """Mounts a fresh `ElicitationForm` whenever the active question changes."""

    DEFAULT_CSS = """
    QuestionRequestBody {
        border: solid $foreground 20%;
        padding: 0 1 0 1;
    }
    """

    pending: reactive[tuple[str, PendingQuestionRequest] | None] = reactive(None)

    _mounted: tuple[str, ElicitationForm] | None = None

    async def watch_pending(
        self, pending: tuple[str, PendingQuestionRequest] | None
    ) -> None:
        self._mounted = None
        await self.remove_children()
        if pending is not None:
            question_id, request = pending
            form = ElicitationForm(request.request.schema)
            await self.mount(form)
            self._mounted = (question_id, form)

    def form(self) -> ElicitationForm | None:
        return self._mounted[1] if self._mounted is not None else None

    def mounted(self) -> tuple[str, ElicitationForm] | None:
        """The mounted form and the question id it was built for.

        The id is bound at mount time rather than read from the queue
        head: completing a question advances the head synchronously
        while this (async, reactive) remount is deferred, so a rapid
        second submit could otherwise answer the next question with the
        previous form's values. A stale submit through this binding
        targets an already-completed id, which the manager ignores.
        """
        return self._mounted

    def focus_first(self) -> None:
        if self._mounted is not None:
            self._mounted[1].focus_first()


class QuestionRequestActions(Horizontal):
    SUBMIT_QUESTION = "submit-question"
    DECLINE_QUESTION = "decline-question"

    DEFAULT_CSS = f"""
    QuestionRequestActions {{
        height: auto;
    }}
    QuestionRequestActions Button {{
        margin-right: 1;
        min-width: 20;
    }}
    QuestionRequestActions #{SUBMIT_QUESTION} {{
        color: $success;
    }}
    QuestionRequestActions #{DECLINE_QUESTION} {{
        color: $warning-darken-3;
    }}
    """

    question: reactive[tuple[str, PendingQuestionRequest] | None] = reactive(None)

    def compose(self) -> ComposeResult:
        yield Button("Submit", id=self.SUBMIT_QUESTION, tooltip="Submit the answer.")
        yield Button("Decline", id=self.DECLINE_QUESTION, tooltip="Decline to answer.")

    def activate(self) -> None:
        submit = self.query_one(f"#{self.SUBMIT_QUESTION}")
        submit.focus()

    def submit_current(self) -> None:
        """Submit the mounted form (Enter dispatch and Submit button).

        The question id comes from the body's mount-time binding, not
        the queue head — see :meth:`QuestionRequestBody.mounted`.
        """
        mounted = self._mounted()
        if mounted is None:
            return
        question_id, form = mounted
        values = form.collect_or_show_errors()
        if values is None:
            return
        human_question_manager().complete_question(
            question_id, InputResult(outcome="accepted", content=values)
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == self.SUBMIT_QUESTION:
            self.submit_current()
        elif event.button.id == self.DECLINE_QUESTION:
            # Decline the question the operator is looking at (the mounted
            # form's id); before the first mount, fall back to the head.
            mounted = self._mounted()
            question_id = (
                mounted[0]
                if mounted is not None
                else self.question[0]
                if self.question is not None
                else None
            )
            if question_id is not None:
                human_question_manager().complete_question(
                    question_id, InputResult(outcome="declined")
                )

    def _mounted(self) -> tuple[str, ElicitationForm] | None:
        body = self.parent.query_one(QuestionRequestBody) if self.parent else None
        return body.mounted() if body is not None else None
