from typing import cast

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, HorizontalGroup, VerticalGroup
from textual.widget import Widget
from textual.widgets import Button, LoadingIndicator, OptionList, Static
from textual.widgets.option_list import Option, Separator

from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai.log._samples import ActiveSample

from ...core.progress import progress_time
from .clock import Clock
from .transcript import TranscriptView


class SamplesView(Widget):
    DEFAULT_CSS = """
    SamplesView {
        width: 1fr;
        height: 1fr;
        padding: 0 1 0 1;
        layout: grid;
        grid-size: 2 3;
        grid-rows: auto 1fr auto;
        grid-columns: 32 1fr;
        grid-gutter: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.samples: list[ActiveSample] = []

    def compose(self) -> ComposeResult:
        yield SamplesList()
        yield SampleInfo()
        yield TranscriptView()
        yield SampleToolbar()

    def on_mount(self) -> None:
        self.watch(
            self.query_one(SamplesList), "highlighted", self.set_highlighted_sample
        )

    async def notify_active(self, active: bool) -> None:
        await self.query_one(TranscriptView).notify_active(active)

    def set_samples(self, samples: list[ActiveSample]) -> None:
        self.query_one(SamplesList).set_samples(samples)

    async def set_highlighted_sample(self, highlighted: int | None) -> None:
        if highlighted is not None:
            sample = self.query_one(SamplesList).sample_for_highlighted(highlighted)
            if sample is not None:
                await self.query_one(SampleInfo).sync_sample(sample)
                await self.query_one(TranscriptView).sync_sample(sample)
                await self.query_one(SampleToolbar).sync_sample(sample)


class SamplesList(OptionList):
    DEFAULT_CSS = """
    SamplesList {
        height: 100%;
        scrollbar-size-vertical: 1;
        margin-bottom: 1;
        row-span: 3;
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
            self.get_option_at_index(self.highlighted).id
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

        # sort the samples by execution time
        self.samples.sort(key=lambda sample: sample.execution_time, reverse=True)

        # rebuild the list
        self.clear_options()
        options: list[Option | Separator] = []
        for sample in self.samples:
            table = Table.grid(expand=True)
            table.add_column(width=20)
            table.add_column(width=11, justify="right")
            table.add_column(width=1)
            task_name = Text.from_markup(f"{registry_unqualified_name(sample.task)}")
            task_name.truncate(18, overflow="ellipsis", pad=True)
            task_time = Text.from_markup(f"{progress_time(sample.execution_time)}")
            table.add_row(task_name, task_time, " ")
            sample_id = Text.from_markup(f"id: {sample.sample.id}")
            sample_id.truncate(18, overflow="ellipsis", pad=True)
            sample_epoch = Text.from_markup(f"epoch: {sample.epoch:.0f}")
            table.add_row(
                sample_id,
                sample_epoch,
                " ",
            )
            options.append(Option(table, id=sample.id))
            options.append(Separator())

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
        highlighted_id = self.get_option_at_index(highlighted).id
        if highlighted_id is not None:
            return sample_for_id(self.samples, highlighted_id)
        else:
            return None


class SampleInfo(Horizontal):
    DEFAULT_CSS = """
    SampleInfo {
        color: $text-muted;
        layout: grid;
        grid-size: 2 1;
        grid-columns: 1fr auto;
        width: 100%;
    }
    #sample-info-model {
        text-align: right;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="sample-info-id")
        yield Static(id="sample-info-model")

    async def sync_sample(self, sample: ActiveSample | None) -> None:
        info_id = cast(Static, self.query_one("#sample-info-id"))
        info_model = cast(Static, self.query_one("#sample-info-model"))
        if sample is not None:
            self.display = True
            id = Text.from_markup(
                f"[bold]{registry_unqualified_name(sample.task)}[/bold] - id: {sample.sample.id} (epoch {sample.epoch})"
            )
            info_id.update(id)
            model = Text.from_markup(sample.model)
            info_model.update(model)
        else:
            self.display = False


class SampleToolbar(Horizontal):
    DEFAULT_CSS = """
    SampleToolbar Button {
        margin-bottom: 1;
        margin-right: 2;
        min-width: 20;
    }
    SampleToolbar #cancel-score-output {
        color: $primary-darken-3;
    }
    SampleToolbar #cancel-raise-error {
        color: $warning-darken-3;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.sample: ActiveSample | None = None

    def compose(self) -> ComposeResult:
        with VerticalGroup(id="pending-status"):
            yield Static("Executing...", id="pending-caption")
            yield HorizontalGroup(EventLoadingIndicator(), Clock())
        yield Button(
            Text("Cancel (Score)"),
            id="cancel-score-output",
            tooltip="Cancel the sample and score whatever output has been generated so far.",
        )
        yield Button(
            Text("Cancel (Error)"),
            id="cancel-raise-error",
            tooltip="Cancel the sample and raise an error (task will exit unless fail_on_error is set)",
        )

    def on_mount(self) -> None:
        self.query_one("#pending-status").visible = False
        self.query_one("#cancel-score-output").display = False
        self.query_one("#cancel-raise-error").display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if self.sample:
            if event.button.id == "cancel-score-output":
                self.sample.interrupt("score")
            elif event.button.id == "cancel-raise-error":
                self.sample.interrupt("error")

    async def sync_sample(self, sample: ActiveSample | None) -> None:
        from inspect_ai.log._transcript import ModelEvent

        # track the sample
        self.sample = sample

        pending_status = self.query_one("#pending-status")
        clock = self.query_one(Clock)
        cancel_score_output = cast(Button, self.query_one("#cancel-score-output"))
        cancel_with_error = cast(Button, self.query_one("#cancel-raise-error"))
        if sample and not sample.completed:
            # update visibility and button status
            self.display = True
            cancel_score_output.display = True
            cancel_with_error.display = not sample.fails_on_error

            # if we have a pending event then start the clock and show pending status
            last_event = (
                sample.transcript.events[-1]
                if len(sample.transcript.events) > 0
                else None
            )
            if last_event and last_event.pending:
                pending_status.visible = True
                pending_caption = cast(Static, self.query_one("#pending-caption"))
                pending_caption_text = (
                    "Generating..."
                    if isinstance(last_event, ModelEvent)
                    else "Executing..."
                )
                pending_caption.update(
                    Text.from_markup(f"[italic]{pending_caption_text}[/italic]")
                )
                clock.start(last_event.timestamp.timestamp())
            else:
                pending_status.visible = False
                clock.stop()

        else:
            self.display = False
            pending_status.visible = False
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
