"""Inline Textual app for console `ask_user` on an interactive terminal.

Replaces the dot-sentinel line reader whenever stdin/stdout are a tty.
Textual enables bracketed paste (and, where the terminal supports it, the
kitty keyboard protocol), so a pasted answer containing newlines or
dot-only lines arrives as one Paste event and stays content — it can no
longer terminate a multiline answer early or spill into the next field.
Typed Enter accepts; Ctrl+J (or Shift+Enter on kitty-protocol terminals)
inserts a newline — see :class:`FormTextArea`.

The app runs with ``run_async(inline=True)`` so it renders under the
prompt rather than taking over the screen (except on Windows, where
Textual has no inline driver and falls back to fullscreen on the
alternate screen).
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, Static

from inspect_ai._util.textual.form import ElicitationForm

from ._types import InputRequest, InputResult


class InlineQuestionApp(App[InputResult]):
    """Renders one `InputRequest` as an inline form and returns the result.

    Exits with `accepted` + content on submit, `declined` on the Decline
    button, and `cancelled` on Ctrl+C. Ctrl+Q (Textual's default quit)
    exits with `None`; the caller maps that to `cancelled`.
    """

    SUBMIT_QUESTION = "submit-question"
    DECLINE_QUESTION = "decline-question"

    CSS = f"""
    Screen {{
        height: auto;
        background: transparent;
    }}
    #question-message {{
        text-style: bold;
        padding: 0 1;
    }}
    ElicitationForm {{
        height: auto;
        max-height: 16;
    }}
    #question-actions {{
        height: auto;
        padding: 0 1;
    }}
    #question-actions Button {{
        margin-right: 1;
        min-width: 16;
    }}
    #question-actions #{SUBMIT_QUESTION} {{
        color: $success;
    }}
    #question-actions #{DECLINE_QUESTION} {{
        color: $warning-darken-3;
    }}
    """

    BINDINGS = [
        Binding("ctrl+c", "cancel", "Cancel", priority=True, show=False),
    ]

    def __init__(self, request: InputRequest) -> None:
        super().__init__()
        self._request = request

    def compose(self) -> ComposeResult:
        yield Static(self._request.message, id="question-message")
        yield ElicitationForm(self._request.schema)
        with Horizontal(id="question-actions"):
            yield Button(
                "Submit",
                id=self.SUBMIT_QUESTION,
                compact=True,
                tooltip="Submit the answer.",
            )
            yield Button(
                "Decline",
                id=self.DECLINE_QUESTION,
                compact=True,
                tooltip="Decline to answer.",
            )

    def on_mount(self) -> None:
        # Defer one refresh cycle: focus() is a no-op against a widget
        # that isn't laid out yet (same dance as the ACP elicitation card).
        form = self.query_one(ElicitationForm)
        self.call_after_refresh(form.focus_first)

    def on_elicitation_form_submit_requested(
        self, event: ElicitationForm.SubmitRequested
    ) -> None:
        event.stop()
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == self.SUBMIT_QUESTION:
            self._submit()
        elif event.button.id == self.DECLINE_QUESTION:
            self.exit(InputResult(outcome="declined"))

    def _submit(self) -> None:
        form = self.query_one(ElicitationForm)
        form.clear_errors()
        values, errors = form.collect()
        if errors:
            form.show_errors(errors)
            return
        self.exit(InputResult(outcome="accepted", content=values))

    def action_cancel(self) -> None:
        self.exit(InputResult(outcome="cancelled"))
