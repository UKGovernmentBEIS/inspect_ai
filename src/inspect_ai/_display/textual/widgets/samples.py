import time
from typing import Callable, cast
from urllib.parse import urlencode, urlparse, urlunparse

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import (
    Horizontal,
    HorizontalGroup,
    Right,
    Vertical,
    VerticalGroup,
)
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import (
    Button,
    Collapsible,
    Link,
    LoadingIndicator,
    OptionList,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option, OptionDoesNotExist

from inspect_ai._display.textual.widgets.port_mappings import get_url
from inspect_ai._display.textual.widgets.vscode import conditional_vscode_link
from inspect_ai._util.file import to_uri
from inspect_ai._util.format import format_progress_time
from inspect_ai._util.port_names import get_service_by_port
from inspect_ai._util.task import task_display_name
from inspect_ai._util.vscode import EXTENSION_COMMAND_OPEN_SAMPLE, VSCodeCommand
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._samples import ActiveSample

from .clock import Clock
from .sandbox import SandboxView
from .transcript import TranscriptView


class SamplesView(Widget):
    DEFAULT_CSS = """
    SamplesView {
        width: 1fr;
        height: 1fr;
        padding: 0 1 0 1;
        layout: horizontal;
    }
    SamplesView > SamplesList {
        width: 32;
        margin-right: 1;
    }
    SamplesView > #sample-detail {
        width: 1fr;
        height: 1fr;
        layout: grid;
        grid-size: 1 3;
        grid-rows: auto 1fr 4;
        grid-gutter: 1;
    }
    /* In prompt mode the toolbar docks to the bottom of the right
       column (``#sample-detail``), removing it from the grid flow.
       The TranscriptView keeps its full grid allocation; the docked
       toolbar overlays the bottom rows of the transcript. Because
       the dock is scoped to ``#sample-detail`` (not SamplesView),
       it doesn't extend over the samples list on the left. When
       prompt mode exits, the toolbar snaps back into its grid cell. */
    SamplesView.prompt-mode #sample-detail SampleToolbar {
        dock: bottom;
        height: auto;
        min-height: 4;
        max-height: 12;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.samples: list[ActiveSample] = []
        self.last_updated = time.perf_counter()

    def compose(self) -> ComposeResult:
        yield SamplesList()
        with Vertical(id="sample-detail"):
            yield SampleInfo()
            yield TranscriptView()
            yield SampleToolbar()

    def on_mount(self) -> None:
        self.watch(
            self.query_one(SamplesList), "highlighted", self.set_highlighted_sample
        )

    async def notify_active(self, active: bool) -> None:
        try:
            await self.query_one(TranscriptView).notify_active(active)
        except NoMatches:
            pass

    def set_samples(self, samples: list[ActiveSample]) -> None:
        # throttle more aggressively with larger numbers of samples
        throttle = 1 + len(samples) / 500
        current = time.perf_counter()
        if (current - self.last_updated) > throttle:
            self.query_one(SamplesList).set_samples(samples)
            self.last_updated = current

    async def set_highlighted_sample(self, highlighted: int | None) -> None:
        sample_info = self.query_one(SampleInfo)
        sample_vnc = self.query_one(SampleVNC)
        transcript_view = self.query_one(TranscriptView)
        sample_toolbar = self.query_one(SampleToolbar)
        if highlighted is not None:
            sample = self.query_one(SamplesList).sample_for_highlighted(highlighted)
            if sample is not None:
                sample_info.display = True
                transcript_view.display = True
                sample_toolbar.display = True
                await sample_info.sync_sample(sample)
                await sample_vnc.sync_sample(sample)
                await transcript_view.sync_sample(sample)
                await sample_toolbar.sync_sample(sample)
                return

        # otherwise hide ui
        sample_info.display = False
        sample_vnc.display = False
        transcript_view.display = False
        sample_toolbar.display = False


class SamplesList(OptionList):
    DEFAULT_CSS = """
    SamplesList {
        height: 1fr;
        scrollbar-size-vertical: 1;
        margin-bottom: 5;
        background: transparent;
    }
    SamplesList:focus > .option-list--option-highlighted {
        background: $primary 40%;
    }

    SamplesList  > .option-list--option-highlighted {
        background: $primary 40%;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.samples: list[ActiveSample] = []

    def set_samples(self, samples: list[ActiveSample]) -> None:
        # check for a highlighted sample (make sure we don't remove it)
        highlighted_id = (
            self.get_id_at_index(self.highlighted)
            if self.highlighted is not None
            else None
        )
        highlighted_sample = (
            sample_for_id(self.samples, highlighted_id)
            if highlighted_id is not None
            else None
        )

        # assign the new samples
        self.samples = samples.copy()

        # add the highlighted sample if its no longer in the list
        if highlighted_sample and (highlighted_sample not in self.samples):
            self.samples.append(highlighted_sample)

        # sort the samples by running time
        self.samples.sort(key=lambda sample: sample.running_time, reverse=True)

        # rebuild the list
        self.clear_options()
        options: list[Option] = []
        for sample in self.samples:
            table = Table.grid(expand=True)
            table.add_column(width=20)
            table.add_column(width=11, justify="right")
            table.add_column(width=1)
            task_name = Text.from_markup(f"{task_display_name(sample.task)}")
            task_name.truncate(18, overflow="ellipsis", pad=True)
            task_time = Text.from_markup(f"{format_progress_time(sample.running_time)}")
            table.add_row(task_name, task_time, " ")
            sample_id = Text.from_markup(f"id: {sample.sample.id}")
            sample_id.truncate(18, overflow="ellipsis", pad=True)
            sample_epoch = Text.from_markup(f"epoch: {sample.epoch:.0f}")
            table.add_row(
                sample_id,
                sample_epoch,
                " ",
            )
            table.add_row("", "", "")
            options.append(Option(table, id=sample.id))

        self.add_options(options)

        # select sample (re-select the highlighted sample if there is one)
        if len(self.samples) > 0:
            if highlighted_id is not None:
                index = sample_index_for_id(self.samples, highlighted_id)
            else:
                index = 0
            self.highlighted = index
            self.scroll_to_highlight()

    def sample_for_highlighted(self, highlighted: int) -> ActiveSample | None:
        highlighted_id = self.get_id_at_index(highlighted)
        if highlighted_id is not None:
            return sample_for_id(self.samples, highlighted_id)
        else:
            return None

    def get_id_at_index(self, index: int) -> str | None:
        try:
            return self.get_option_at_index(index).id
        except OptionDoesNotExist:
            return None


class SampleVNC(Horizontal):
    DEFAULT_CSS = """
    SampleVNC {
        layout: grid;
        grid-size: 2 1;
        grid-columns: auto 1fr;
    }
    SampleVNC Static {
        color: $secondary;
    }
    SampleVNC Link {
        color: $accent;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._sample: ActiveSample | None = None

    def compose(self) -> ComposeResult:
        yield Static("VNC: ")
        yield Link("")

    async def sync_sample(self, sample: ActiveSample) -> None:
        if sample == self._sample:
            return

        # defult to hidden (show if we find a vnc connection)
        self.display = False

        # is there a vnc connection? if so populate
        for connection in [c for c in sample.sandboxes.values() if c.ports]:
            for port in connection.ports or []:
                service = get_service_by_port(port.container_port, port.protocol)
                if service == "noVNC" and port.mappings:
                    host_mappings = port.mappings
                    link = self.query_one(Link)
                    vnc_url = get_url(host_mappings[0].host_port, service)
                    if vnc_url:
                        link.text = vnc_url
                        link.url = link.text
                        self.display = True
                        break


class SampleInfo(Vertical):
    DEFAULT_CSS = """
    SampleInfo {
        color: $text-muted;
        layout: grid;
        grid-size: 1 2;
        grid-rows: auto 1;
        grid-gutter: 1;
    }
    SampleInfo Collapsible {
        padding: 0;
        border-top: none;
    }
    SampleInfo Collapsible CollapsibleTitle {
        padding: 0;
        color: $secondary;
        &:hover {
            background: $block-hover-background;
            color: $primary;
        }
        &:focus {
            background: $block-hover-background;
            color: $primary;
        }
    }
    SampleInfo Collapsible Contents {
        padding: 1 0 1 2;
        height: auto;
        overflow-x: auto;
    }
    SampleInfo Static {
        width: 1fr;
        background: $surface;
        color: $secondary;
    }
    SampleInfo #sample-link {
        height: auto;
        width: 11;
        margin-left: 1;
        background: $background;
    }
    SampleInfo #sample-link Link {
        color: $accent;
        background: $background;
    }
    SampleInfo #interrupt-sample {
        min-width: 0;
        width: auto;
        height: auto;
        margin: 0 0 0 1;
        padding: 0 1;
        color: $warning-darken-3;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._sample: ActiveSample | None = None
        self._sandbox_count: int | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Collapsible(title=""):
                yield SampleLimits()
                yield SandboxesView()
            yield Button(
                Text("⏸ Interrupt"),
                id="interrupt-sample",
                compact=True,
                tooltip=(
                    "Pause the agent mid-turn and inject a message. "
                    "The agent will resume after you submit."
                ),
            )
            yield Right(id="sample-link")

        yield SampleVNC()

    def on_mount(self) -> None:
        # Interrupt button only shows when the sample has a live ACP session.
        self.query_one("#interrupt-sample", Button).display = False

    async def sync_sample(self, sample: ActiveSample | None) -> None:
        # Interrupt button visibility tracks the sample's ACP session and
        # has to be re-evaluated even when the sample identity hasn't
        # changed (a sample can gain/lose its live session over time).
        # Also hide it while the toolbar is in prompt mode so a repeat
        # click can't fire a duplicate cancel_current_turn (which would
        # record a redundant InterruptEvent) before the operator submits.
        interrupt_btn = self.query_one("#interrupt-sample", Button)
        acp = sample.acp_transport if sample is not None else None
        try:
            in_prompt = self.app.query_one(SampleToolbar).in_prompt_mode
        except NoMatches:
            in_prompt = False
        interrupt_btn.display = (
            acp is not None and acp.session_id != "noop" and not in_prompt
        )

        if sample is None:
            self.display = False
            self._sample = None
        else:
            # update sample limits
            limits = self.query_one(SampleLimits)
            await limits.sync_sample(sample)

            new_sandbox_count = len(sample.sandboxes)
            # bail if we've already processed this sample
            if self._sample == sample and self._sandbox_count == new_sandbox_count:
                return

            # set sample
            self._sample = sample
            self._sandbox_count = new_sandbox_count

            # update UI
            self.display = True
            title = f"{task_display_name(sample.task)} (id: {sample.sample.id}, epoch {sample.epoch}): {sample.model}"
            self.query_one(Collapsible).title = title
            sandboxes = self.query_one(SandboxesView)
            await sandboxes.sync_sample(sample)
            await self.query_one(SampleVNC).sync_sample(sample)

            # View Log Link
            base_uri = sample.log_location
            query_params = {
                "sample_id": sample.sample.id,
                "epoch": sample.epoch,
            }

            parsed = urlparse(to_uri(base_uri))
            view_link = urlunparse(parsed._replace(query=urlencode(query_params)))

            link_container = self.query_one("#sample-link")
            link_container.remove_children()
            link = conditional_vscode_link(
                "[View Log]",
                VSCodeCommand(
                    command="inspect.openLogViewer",
                    args=[view_link] if sample.log_location else [],
                ),
                EXTENSION_COMMAND_OPEN_SAMPLE,
            )
            # When running outside VS Code, `conditional_vscode_link` returns
            # an empty Static (not a Link). Hide the container in that case
            # so we don't waste 12 cells of header space on an invisible slot
            # that would otherwise push other widgets (like the Interrupt
            # button) and squeeze the title.
            link_container.mount(link)
            link_container.display = isinstance(link, Link)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "interrupt-sample":
            return
        sample = self._sample
        if sample is None:
            return
        acp = sample.acp_transport
        if acp is None or acp.session_id == "noop":
            return
        # Hide the button immediately so a fast double-click can't fire
        # cancel_current_turn() twice before sync_sample re-evaluates
        # visibility. sync_sample will re-show it once prompt mode exits
        # (and the ACP session is still live).
        event.button.display = False
        # Fire-and-forget cancel: the transport forwards via
        # ``ref.interrupt(Cancel(...))`` to the agent's bound channel
        # scope, which raises :exc:`AgentInterrupted`; react then drains
        # any redirect we queue via prompt-mode submission.
        acp.cancel_current_turn()
        # Switch the toolbar (sibling widget) into prompt mode.
        try:
            toolbar = self.app.query_one(SampleToolbar)
        except NoMatches:
            return
        toolbar.enter_prompt_mode(sample)


class SampleLimits(Widget):
    DEFAULT_CSS = """
    SampleLimits {
        padding: 0 0 0 0;
        color: $secondary;
        background: transparent;
        height: auto;
    }
    SampleLimits Static {
        background: transparent;
        color: $secondary;
    }
    """

    messages = reactive(0)
    message_limit = reactive(0)
    tokens = reactive(0)
    token_limit = reactive(0)
    started = reactive(0)
    time_limit = reactive(0)

    def __init__(self) -> None:
        super().__init__()

    def render(self) -> RenderableType:
        limits = f"[bold]messages[/bold]: {self.messages}"
        if self.message_limit:
            limits = f"{limits} (limit {self.message_limit})"
        limits = f"{limits}, [bold]tokens[/bold]: {self.tokens:,}"
        if self.token_limit:
            limits = f"{limits} ({self.token_limit:,})"
        return limits

    async def sync_sample(self, sample: ActiveSample) -> None:
        self.messages = sample.total_messages
        self.message_limit = sample.message_limit or 0
        self.tokens = sample.total_tokens
        self.token_limit = sample.token_limit or 0


class SandboxesView(Vertical):
    DEFAULT_CSS = """
    SandboxesView {
        padding: 1 0 0 0;
        background: transparent;
        height: auto;
    }
    #sandboxes-list {
        height: auto;
    }
    SandboxesView Static {
        background: transparent;
    }
    .clipboard-message {
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Static(id="sandboxes-caption", markup=True)
        yield Vertical(id="sandboxes-list")

    async def sync_sample(self, sample: ActiveSample) -> None:
        if len(sample.sandboxes) > 0:
            multiple_sandboxes = len(sample.sandboxes) > 1
            sandboxes_caption = cast(Static, self.query_one("#sandboxes-caption"))
            sandboxes_caption.update(
                f"[bold]sandbox container{'s' if multiple_sandboxes else ''}:[/bold]"
            )

            sandboxes_list = self.query_one("#sandboxes-list")
            await sandboxes_list.remove_children()

            await sandboxes_list.mount_all(
                [
                    SandboxView(connection, name if multiple_sandboxes else None)
                    for name, connection in sample.sandboxes.items()
                ]
            )

            await sandboxes_list.mount(
                Static(
                    "[italic]Hold down Alt (or Option) to select text for copying[/italic]",
                    classes="clipboard-message",
                    markup=True,
                )
            )
            self.display = True
        else:
            self.display = False


class InterjectTextArea(TextArea):
    r"""TextArea where Enter submits and Ctrl+J inserts a newline.

    Chat-input convention rather than the standard text-editor
    convention (Enter = newline). Textual's :class:`Key` event has no
    modifier-state fields, and most terminals can't distinguish
    Shift+Enter from plain Enter at the byte level — both arrive as
    ``Key(key='enter', character='\r')``. So we use Ctrl+J for the
    newline shortcut: Enter sends CR (0x0D) and Ctrl+J sends LF
    (0x0A), which terminals universally distinguish. Posts an
    :class:`Submitted` message on submit; the parent toolbar listens.
    """

    class Submitted(Message):
        """Posted when the user presses Enter to submit the message."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            # Heuristic for terminals (e.g. macOS Terminal.app) that
            # emit Shift+Enter as two events: a backslash key followed
            # by a plain Enter. By the time we see Enter the backslash
            # is already in the buffer. If the text ends with a single
            # backslash, treat the sequence as Shift+Enter: strip the
            # backslash and insert a newline instead of submitting.
            # Side-effect: messages that intentionally end with a
            # single ``\`` can't be submitted with Enter — add another
            # character or use the Send button.
            if self.text.endswith("\\"):
                self.action_delete_left()
                self.insert("\n")
                return
            self.post_message(self.Submitted(self.text))
            return
        if event.key == "ctrl+j":
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        await super()._on_key(event)


class SampleToolbar(Horizontal):
    STATUS_GROUP = "status_group"
    TIMEOUT_TOOL_CALL = "timeout_tool_call"
    CANCEL_SCORE_OUTPUT = "cancel_score_output"
    CANCEL_RAISE_ERROR = "cancel_raise_error"
    PENDING_STATUS = "pending_status"
    PENDING_CAPTION = "pending_caption"
    TOOLBAR_SPACER = "toolbar_spacer"
    INTERJECT_INPUT = "interject-input"
    INTERJECT_SEND = "interject-send"

    TIMEOUT_TOOL_CALL_ENABLED = (
        "Cancel the tool call and report a timeout to the model."
    )
    TIMEOUT_TOOL_CALL_DISABLED = "Cancelling tool call..."
    CANCEL_SCORE_OUTPUT_ENABLED = (
        "Cancel the sample and score whatever output has been generated so far."
    )
    CANCEL_RAISE_ERROR_ENABLED = "Cancel the sample and raise an error"
    CANCEL_DISABLED = "Cancelling sample..."

    INTERJECT_PLACEHOLDER = "Type a message for the model (e.g. 'please continue')"

    DEFAULT_CSS = f"""
    SampleToolbar {{
        align-vertical: bottom;
    }}
    SampleToolbar #{STATUS_GROUP} {{
        width: 22;
    }}
    SampleToolbar Button {{
        margin-bottom: 1;
        margin-right: 2;
        min-width: 18;
    }}
    SampleToolbar #{TIMEOUT_TOOL_CALL} {{
        color: $secondary-darken-3;
        min-width: 16;
    }}
    SampleToolbar #{CANCEL_SCORE_OUTPUT} {{
        color: $primary-darken-3;
    }}
    SampleToolbar #{CANCEL_RAISE_ERROR} {{
        color: $error-darken-2;
    }}
    SampleToolbar #{INTERJECT_INPUT} {{
        width: 1fr;
        height: auto;
        min-height: 1;
        max-height: 10;
        margin-right: 1;
        margin-bottom: 1;
    }}
    SampleToolbar #{INTERJECT_SEND} {{
        min-width: 7;
        width: 7;
        text-style: bold;
    }}
    """

    def __init__(self) -> None:
        super().__init__()
        self.sample: ActiveSample | None = None
        # When True, the toolbar replaces its status indicator + cancel
        # buttons with an interject Input + Send button. Driven by the
        # Interrupt button on the SampleInfo header.
        self._prompt_mode: bool = False
        # Subscriptions on the current sample's AcpTransport (multi-client
        # interrupt-prompt coordination). When a sibling client triggers
        # the cancel, the interrupted hook fires and we enter prompt
        # mode locally; when a sibling client submits the resumption
        # text, the resolved hook fires and we exit prompt mode without
        # waiting for the user to type in this TUI. Only the in-proc
        # TUI subscribes — generic ACP clients have no modal state to
        # coordinate. See AcpTransport.subscribe_interrupted /
        # subscribe_prompt_resolved.
        self._unsubscribe_interrupted: Callable[[], None] | None = None
        self._unsubscribe_prompt_resolved: Callable[[], None] | None = None
        # Track which acp_session we're attached to so sync_sample can
        # re-subscribe if the sample's session changes (e.g. eval
        # transitioned to a new sample, or the session was re-entered).
        self._subscribed_acp_session_id: str | None = None

    @property
    def in_prompt_mode(self) -> bool:
        """True while the toolbar is awaiting an interject submission.

        SampleInfo reads this to hide the Interrupt button so a repeat
        click can't fire a second :meth:`AcpTransport.cancel_current_turn`
        (which would record a redundant InterruptEvent) while we're
        already waiting on the operator's reply.
        """
        return self._prompt_mode

    def compose(self) -> ComposeResult:
        with HorizontalGroup(id=self.STATUS_GROUP):
            with VerticalGroup(id=self.PENDING_STATUS):
                yield Static("Executing...", id=self.PENDING_CAPTION)
                yield HorizontalGroup(EventLoadingIndicator(), Clock())
        yield Button(
            Text("Timeout Tool"),
            id=self.TIMEOUT_TOOL_CALL,
            tooltip=self.TIMEOUT_TOOL_CALL_ENABLED,
        )
        yield Horizontal(id=self.TOOLBAR_SPACER)
        yield Button(
            Text("Cancel (Score)"),
            id=self.CANCEL_SCORE_OUTPUT,
            tooltip=self.CANCEL_SCORE_OUTPUT_ENABLED,
        )
        yield Button(
            Text("Cancel (Error)"),
            id=self.CANCEL_RAISE_ERROR,
            tooltip=self.CANCEL_RAISE_ERROR_ENABLED,
        )
        yield InterjectTextArea(
            id=self.INTERJECT_INPUT,
            placeholder=self.INTERJECT_PLACEHOLDER,
            soft_wrap=True,
            show_line_numbers=False,
        )
        yield Button(
            Text("⬆"),
            id=self.INTERJECT_SEND,
            variant="primary",
            tooltip="Send message and resume the agent.",
        )

    def on_mount(self) -> None:
        self.query_one("#" + self.PENDING_STATUS).visible = False
        self.query_one("#" + self.TIMEOUT_TOOL_CALL).display = False
        self.query_one("#" + self.CANCEL_SCORE_OUTPUT).display = False
        self.query_one("#" + self.CANCEL_RAISE_ERROR).display = False
        self.query_one("#" + self.INTERJECT_INPUT).display = False
        self.query_one("#" + self.INTERJECT_SEND).display = False

    def enter_prompt_mode(self, sample: ActiveSample) -> None:
        """Switch the toolbar into interject-prompt mode for ``sample``.

        Called from the Interrupt button click handler on SampleInfo
        right after firing ``acp.cancel_current_turn()``. Hides the
        status indicator and cancel buttons; reveals the TextArea +
        Send button and focuses the TextArea. Adds the ``prompt-mode``
        class on the parent :class:`SamplesView` which docks the
        toolbar to the bottom — the toolbar pops out of the grid flow
        so the transcript keeps its full height, and the docked
        toolbar overlays the bottom rows of the transcript. With
        ``align-vertical: bottom`` and ``height: auto`` the TextArea
        grows *upward* from the panel bottom as the user types.
        """
        if sample is not self.sample:
            return
        self._prompt_mode = True
        self.query_one("#" + self.STATUS_GROUP).display = False
        self.query_one("#" + self.TIMEOUT_TOOL_CALL).display = False
        self.query_one("#" + self.CANCEL_SCORE_OUTPUT).display = False
        self.query_one("#" + self.CANCEL_RAISE_ERROR).display = False
        # Collapse the flex spacer so the TextArea can claim the full width.
        self.query_one("#" + self.TOOLBAR_SPACER).display = False
        send = cast(Button, self.query_one("#" + self.INTERJECT_SEND))
        send.display = True
        interject = cast(InterjectTextArea, self.query_one("#" + self.INTERJECT_INPUT))
        interject.display = True
        interject.text = ""
        interject.focus()
        self._set_prompt_mode_class(True)

    def _exit_prompt_mode(self) -> None:
        """Revert from prompt mode back to status mode.

        Hides the Input + Send button. ``sync_sample`` will re-show the
        status group / cancel buttons on the next refresh cycle.
        Removes the ``prompt-mode`` class so the toolbar grid row
        snaps back to its idle 4-cell height.
        """
        self._prompt_mode = False
        self.query_one("#" + self.INTERJECT_INPUT).display = False
        self.query_one("#" + self.INTERJECT_SEND).display = False
        self.query_one("#" + self.STATUS_GROUP).display = True
        # Restore the flex spacer that pushes the cancel buttons to the right.
        self.query_one("#" + self.TOOLBAR_SPACER).display = True
        self._set_prompt_mode_class(False)

    def _set_prompt_mode_class(self, on: bool) -> None:
        """Add/remove ``prompt-mode`` class on the parent SamplesView.

        Drives the grid-rows switch (4 ↔ 10 cells) that gives the
        toolbar more vertical room when actively accepting interject
        input.
        """
        try:
            samples_view = self.app.query_one(SamplesView)
        except NoMatches:
            return
        if on:
            samples_view.add_class("prompt-mode")
        else:
            samples_view.remove_class("prompt-mode")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == self.INTERJECT_SEND:
            interject = cast(
                InterjectTextArea, self.query_one("#" + self.INTERJECT_INPUT)
            )
            self._submit_interject(interject.text)
            return
        if self.sample:
            if event.button.id == self.TIMEOUT_TOOL_CALL:
                # Under parallel tool calls multiple ToolEvents can be
                # pending at once. Each owns its own per-call CancelScope
                # (see _call_tools.py run_one), so fan out the cancel to
                # every pending sibling.
                pending_tools = [
                    ev
                    for ev in self.sample.transcript.pending_events
                    if isinstance(ev, ToolEvent)
                ]
                if pending_tools:
                    for tool_event in pending_tools:
                        tool_event._cancel()
                    event.button.disabled = True
                    event.button.tooltip = self.TIMEOUT_TOOL_CALL_DISABLED
            elif event.button.id in (self.CANCEL_SCORE_OUTPUT, self.CANCEL_RAISE_ERROR):
                if event.button.id == self.CANCEL_SCORE_OUTPUT:
                    self.sample.interrupt("score")
                elif event.button.id == self.CANCEL_RAISE_ERROR:
                    self.sample.interrupt("error")
                cancel_score_output = self.query_one("#" + self.CANCEL_SCORE_OUTPUT)
                cancel_score_output.disabled = True
                cancel_score_output.tooltip = self.CANCEL_DISABLED
                cancel_with_error = self.query_one("#" + self.CANCEL_RAISE_ERROR)
                cancel_with_error.disabled = True
                cancel_with_error.tooltip = self.CANCEL_DISABLED

    def on_interject_text_area_submitted(
        self, event: "InterjectTextArea.Submitted"
    ) -> None:
        self._submit_interject(event.text)

    def _submit_interject(self, text: str) -> None:
        """Forward the interject message to the live ACP session, then exit prompt mode.

        Triggered exclusively by the Send button — the TextArea's Enter
        key inserts a newline (matching standard text-editor semantics)
        so multi-line messages compose naturally. Empty input is
        silently ignored (per spec: the user must enter something to
        resume the agent). If the sample no longer has a live ACP
        session by submit time, we just exit prompt mode without
        submitting — the agent is presumably done.
        """
        from inspect_ai.model._chat_message import ChatMessageUser

        clean = text.strip()
        if not clean:
            return
        sample = self.sample
        if sample is None or sample.acp_transport is None:
            self._exit_prompt_mode()
            return
        sample.acp_transport.submit_user_message(ChatMessageUser(content=clean))
        self._exit_prompt_mode()

    def _sync_interrupt_subscriptions(self, sample: ActiveSample | None) -> None:
        """Keep our subscriptions aligned with the sample's AcpTransport.

        Subscribes to ``subscribe_interrupted`` and
        ``subscribe_prompt_resolved`` on the bound session, capturing
        the originating session id in each closure so scheduled
        handlers can re-validate against ``self.sample`` at execution
        time (the sample may have changed between event-fire and the
        Textual call_later landing). Called from :meth:`sync_sample`
        so subscriptions re-aim if the sample (or its session)
        changes.

        After subscribing, also catches up against the session's
        current ``interrupt_pending`` state — covers the case where
        the cancel arrived before the TUI was subscribed (sample
        switch, late attach, reattach window).
        """
        target_session = sample.acp_transport if sample is not None else None
        target_id = target_session.session_id if target_session is not None else None

        # No change → no work.
        if target_id == self._subscribed_acp_session_id:
            return

        # Detach from the previous session, if any.
        if self._unsubscribe_interrupted is not None:
            try:
                self._unsubscribe_interrupted()
            except Exception:
                pass
            self._unsubscribe_interrupted = None
        if self._unsubscribe_prompt_resolved is not None:
            try:
                self._unsubscribe_prompt_resolved()
            except Exception:
                pass
            self._unsubscribe_prompt_resolved = None
        self._subscribed_acp_session_id = None

        # Subscribe to the new session, if any. Skip no-op sessions
        # (sub-agent shadow): they have no cancel events and the
        # subscribe call returns a no-op unsubscribe.
        if target_session is None or target_id == "noop":
            return

        # Capture the originating session id in closures so the
        # scheduled handlers can re-validate against the current
        # sample's session at execution time. Without this, a sample
        # switch between event-fire and call_later landing could
        # enter prompt mode for the wrong sample, or exit it for an
        # unrelated session.
        sid = target_id

        def _on_interrupted() -> None:
            try:
                self.app.call_later(self._handle_interrupted, sid)
            except Exception:
                # Widget unmounted or app shutting down — drop silently.
                pass

        def _on_resolved() -> None:
            try:
                self.app.call_later(self._handle_prompt_resolved, sid)
            except Exception:
                pass

        self._unsubscribe_interrupted = target_session.subscribe_interrupted(
            _on_interrupted
        )
        self._unsubscribe_prompt_resolved = target_session.subscribe_prompt_resolved(
            _on_resolved
        )
        self._subscribed_acp_session_id = target_id

        # Catch-up: if the session is already mid-interrupt at
        # subscribe time, schedule the entry handler. Without this
        # the TUI silently misses interrupts triggered before its
        # subscription landed (external ACP cancel during a sample
        # switch, reattach window, etc.).
        if target_session.interrupt_pending:
            try:
                self.app.call_later(self._handle_interrupted, sid)
            except Exception:
                pass

    def _handle_interrupted(self, originating_session_id: str) -> None:
        """Enter prompt mode on cancel from a sibling client (Textual task).

        Re-validates that the sample STILL has the session the event
        originated from AND that the interrupt is still pending —
        guards against (a) the user switching samples between the
        event firing and call_later landing, and (b) the interrupt
        having already been resolved (e.g. by ``after_cancel``
        draining a pre-queued message). Without these checks a stale
        callback could enter prompt mode for the wrong sample or
        after the interrupt is moot.
        """
        if self._prompt_mode:
            return
        sample = self.sample
        if sample is None or sample.acp_transport is None:
            return
        if sample.acp_transport.session_id != originating_session_id:
            # Sample switched between event-fire and execution.
            return
        if not sample.acp_transport.interrupt_pending:
            # Already resolved (e.g. another client submitted the
            # resumption text first, or after_cancel drained a
            # pre-queued message).
            return
        self.enter_prompt_mode(sample)

    def _handle_prompt_resolved(self, originating_session_id: str) -> None:
        """Exit prompt mode when a sibling client resolves the cancel.

        Re-validates the originating session matches the current
        sample's session before exiting — a resolved event for
        session A shouldn't dismiss a prompt that's now showing for
        session B.
        """
        if not self._prompt_mode:
            return
        sample = self.sample
        if sample is None or sample.acp_transport is None:
            return
        if sample.acp_transport.session_id != originating_session_id:
            return
        self._exit_prompt_mode()

    async def sync_sample(self, sample: ActiveSample | None) -> None:
        # is it a new sample?
        new_sample = sample != self.sample

        # If we were in prompt mode and the world changed underneath us
        # (sample switched, completed, or lost its ACP session), exit
        # prompt mode and let the normal status sync take over.
        if self._prompt_mode and (
            sample is None
            or new_sample
            or sample.completed
            or sample.acp_transport is None
        ):
            self._exit_prompt_mode()

        # Multi-client interrupt-prompt coordination: keep our hook
        # subscriptions aligned with the sample's current AcpTransport so
        # a cancel triggered by a sibling client (Phase 13 ACP bridge)
        # auto-enters prompt mode locally, and a resumption text
        # submitted by a sibling client auto-exits it.
        self._sync_interrupt_subscriptions(sample)

        # track the sample
        self.sample = sample

        # While in prompt mode, the interject Input owns the toolbar row;
        # skip the status / cancel-button refresh path below.
        if self._prompt_mode:
            self.display = True
            return

        status_group = self.query_one("#" + self.STATUS_GROUP)
        pending_status = self.query_one("#" + self.PENDING_STATUS)
        timeout_tool = self.query_one("#" + self.TIMEOUT_TOOL_CALL)
        clock = self.query_one(Clock)
        cancel_score_output = cast(
            Button, self.query_one("#" + self.CANCEL_SCORE_OUTPUT)
        )
        cancel_with_error = cast(Button, self.query_one("#" + self.CANCEL_RAISE_ERROR))
        if sample and not sample.completed:
            # update visibility and button status
            self.display = True
            cancel_score_output.display = True
            cancel_with_error.display = not sample.fails_on_error

            # if its a new sample then reset enabled states
            if new_sample:
                cancel_score_output.disabled = False
                cancel_score_output.tooltip = self.CANCEL_SCORE_OUTPUT_ENABLED
                cancel_with_error.disabled = False
                cancel_with_error.tooltip = self.CANCEL_RAISE_ERROR_ENABLED

            # Resolve the pending state from the transcript's sidecar.
            # ``pending_events`` is maintained by ``_event``/``_event_updated``
            # so it's O(in-flight) to read regardless of total
            # transcript length — important for the once-per-second
            # ``update_display`` cadence and for future DB-backed
            # transcripts where ``events`` may not be in memory.
            #
            # Pending state classification:
            #   - Only pending ModelEvent → "Generating...", no timeout
            #     button (model calls aren't cancellable from this
            #     affordance).
            #   - Any pending ToolEvent → "Executing..." / "Executing N
            #     tools...", timeout button visible. This case wins
            #     even when a nested ModelEvent is also pending
            #     (sub-agents / handoffs / parallel-tool-internal
            #     generation) because the operator's intent in that
            #     mixed state is to cancel the tool(s), not the inner
            #     model call.
            pending_model: ModelEvent | None = None
            earliest_pending_tool: ToolEvent | None = None
            pending_tool_count = 0
            for ev in sample.transcript.pending_events:
                if isinstance(ev, ModelEvent):
                    if pending_model is None:
                        pending_model = ev
                elif isinstance(ev, ToolEvent):
                    if earliest_pending_tool is None:
                        earliest_pending_tool = ev
                    pending_tool_count += 1

            if earliest_pending_tool is not None:
                pending_status.visible = True
                pending_caption = cast(
                    Static, self.query_one("#" + self.PENDING_CAPTION)
                )
                if pending_tool_count > 1:
                    pending_caption_text = f"Executing {pending_tool_count} tools..."
                    timeout_tooltip = (
                        "Cancel the tool calls and report a timeout to the model."
                    )
                else:
                    pending_caption_text = "Executing..."
                    timeout_tooltip = self.TIMEOUT_TOOL_CALL_ENABLED
                status_group.styles.width = max(22, len(pending_caption_text))
                pending_caption.update(
                    Text.from_markup(f"[italic]{pending_caption_text}[/italic]")
                )
                timeout_tool.display = True
                timeout_tool.disabled = False
                timeout_tool.tooltip = timeout_tooltip
                clock.start(earliest_pending_tool.timestamp.timestamp())
            elif pending_model is not None:
                pending_status.visible = True
                pending_caption = cast(
                    Static, self.query_one("#" + self.PENDING_CAPTION)
                )
                if pending_model.retries:
                    suffix = "retry" if pending_model.retries == 1 else "retries"
                    pending_caption_text = (
                        f"Generating ({pending_model.retries:,} {suffix})..."
                    )
                else:
                    pending_caption_text = "Generating..."
                status_group.styles.width = max(22, len(pending_caption_text))
                pending_caption.update(
                    Text.from_markup(f"[italic]{pending_caption_text}[/italic]")
                )
                timeout_tool.display = False
                clock.start(pending_model.timestamp.timestamp())
            else:
                pending_status.visible = False
                timeout_tool.display = False
                clock.stop()

        else:
            self.display = False
            pending_status.visible = False
            timeout_tool.display = False
            clock.stop()


class EventLoadingIndicator(LoadingIndicator):
    DEFAULT_CSS = """
    EventLoadingIndicator {
        width: auto;
        height: 1;
        color: $primary;
        text-style: not reverse;
        margin-right: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()


def sample_for_id(samples: list[ActiveSample], id: str) -> ActiveSample | None:
    index = sample_index_for_id(samples, id)
    if index != -1:
        return samples[index]
    else:
        return None


def sample_index_for_id(samples: list[ActiveSample], id: str) -> int:
    for i, sample in enumerate(samples):
        if sample.id == id:
            return i
    return -1
