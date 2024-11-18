from typing import cast

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, OptionList
from textual.widgets.option_list import Option, Separator

from inspect_ai._display.core.progress import progress_time
from inspect_ai._display.textual.widgets.transcript import TranscriptView
from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai.log._samples import ActiveSample


class SamplesView(Widget):
    DEFAULT_CSS = """
    SamplesView {
        width: 1fr;
        height: 1fr;
        padding: 0 1 0 1;
        layout: grid;
        grid-size: 2 2;
        grid-rows: 1fr auto;
        grid-columns: 30 1fr;
        grid-gutter: 1;
    }
    SamplesView OptionList {
        height: 100%;
        scrollbar-size-vertical: 1;
        margin-bottom: 1;
        row-span: 2;
    }
    SamplesView OptionList:focus > .option-list--option-highlighted {
        background: $accent 40%;
    }

    SamplesView OptionList > .option-list--option-highlighted {
        background: $accent 40%;
        text-style: none;
    }

    SamplesView TranscriptView {
        scrollbar-size-vertical: 1;
        scrollbar-gutter: stable;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.samples: list[ActiveSample] = []

    def compose(self) -> ComposeResult:
        yield OptionList()
        yield TranscriptView()
        yield SampleToolbar()

    def on_mount(self) -> None:
        self.watch(self.query_one(OptionList), "highlighted", self.set_highlighted)

    def set_samples(self, samples: list[ActiveSample]) -> None:
        # check for a highlighted sample (make sure we don't remove it)
        option_list = self.query_one(OptionList)
        highlighted_id = (
            option_list.get_option_at_index(option_list.highlighted).id
            if option_list.highlighted is not None
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
        option_list.clear_options()
        options: list[Option | Separator] = []
        for sample in self.samples:
            table = Table.grid(expand=True)
            table.add_column()
            table.add_column(justify="right")
            table.add_column()
            task_name = Text.from_markup(
                f"{registry_unqualified_name(sample.task)}", style="black"
            )
            task_name.truncate(18, overflow="ellipsis", pad=True)
            task_time = Text.from_markup(
                f"{progress_time(sample.execution_time)}", style="black"
            )
            table.add_row(task_name, task_time, " ")
            sample_id = Text.from_markup(f"id: {sample.sample.id}", style="dim black")
            sample_id.truncate(18, overflow="ellipsis", pad=True)
            sample_epoch = Text.from_markup(
                f"epoch: {sample.epoch:.0f}", style="dim black"
            )
            table.add_row(
                sample_id,
                sample_epoch,
                " ",
            )
            options.append(Option(table, id=sample.id))
            options.append(Separator())

        option_list.add_options(options)

        # select sample (re-select the highlighted sample if there is one)
        if len(self.samples) > 0:
            if highlighted_id is not None:
                index = sample_index_for_id(self.samples, highlighted_id)
            else:
                index = 0
            option_list.highlighted = index
            option_list.scroll_to_highlight()

    async def set_highlighted(self, highlighted: int | None) -> None:
        # alias widgets
        option_list = self.query_one(OptionList)
        transcript_view = self.query_one(TranscriptView)
        sample_toolbar = self.query_one(SampleToolbar)

        # look for a highlighted sample to sync
        if highlighted is not None:
            highlighted_id = option_list.get_option_at_index(highlighted).id
            if highlighted_id is not None:
                sample = sample_for_id(self.samples, highlighted_id)
                if sample:
                    await sample_toolbar.sync_sample(sample)
                    await transcript_view.sync_sample(sample)
                    return


class SampleToolbar(Horizontal):
    DEFAULT_CSS = """
    SampleToolbar Button {
        margin-bottom: 1;
        margin-right: 2;
        min-width: 24;
    }
    SampleToolbar #cancel-score-output {
        color: $accent-darken-3;
    }
    SampleToolbar #cancel-raise-error {
        color: $warning-darken-3;
    }
    """

    def __init__(self) -> None:
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Button(
            Text("Cancel (Score Output)"),
            id="cancel-score-output",
            tooltip="Cancel the sample and score whatever output has been generated so far.",
        )
        yield Button(
            Text("Cancel (Raise Error)"),
            id="cancel-raise-error",
            tooltip="Cancel the sample and raise an error (task will exit unless fail_on_error is set)",
        )

    async def sync_sample(self, sample: ActiveSample | None) -> None:
        cancel_with_error = cast(Button, self.query_one("#cancel-raise-error"))
        if sample:
            self.display = True
            cancel_with_error.display = not sample.fails_on_error
        else:
            self.display = False


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
