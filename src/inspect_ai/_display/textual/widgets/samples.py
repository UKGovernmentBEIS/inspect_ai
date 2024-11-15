from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from inspect_ai._display.core.progress import progress_time
from inspect_ai._display.core.rich import rich_theme
from inspect_ai._display.textual.widgets.transcript import TranscriptView
from inspect_ai.log._samples import ActiveSample


class SamplesView(Widget):
    DEFAULT_CSS = """
    SamplesView {
        width: 1fr;
        height: 1fr;
        padding: 0 1 0 1;
        layout: grid;
        grid-size: 2 1;
        grid-columns: 30 1fr;
    }
    SamplesView OptionList {
        height: 100%;
        scrollbar-size-vertical: 1;
    }
    SamplesView TranscriptView {
        scrollbar-size-vertical: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.samples: list[ActiveSample] = []

    def compose(self) -> ComposeResult:
        yield OptionList()
        yield TranscriptView()

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
        theme = rich_theme()
        option_list.clear_options()
        options: list[Option] = []
        for sample in self.samples:
            table = Table.grid(expand=True)
            table.add_column()
            table.add_column(justify="right")
            table.add_column()
            task_name = Text(sample.task)
            task_name.truncate(20, overflow="ellipsis", pad=True)
            task_time = Text.from_markup(
                f"[{theme.light}]{progress_time(sample.execution_time)}[/{theme.light}]"
            )
            table.add_row(task_name, task_time, " ")
            options.append(Option(table, id=sample.id))
        option_list.add_options(options)

        # re-select the highlighted sample
        if highlighted_id is not None:
            index = sample_index_for_id(self.samples, highlighted_id)
            if index != -1:
                option_list.highlighted = index
                option_list.scroll_to_highlight()

    async def set_highlighted(self, highlighted: int | None) -> None:
        option_list = self.query_one(OptionList)
        transcript_view = self.query_one(TranscriptView)
        if highlighted is not None:
            highlighted_id = option_list.get_option_at_index(highlighted).id
            if highlighted_id is not None:
                sample = sample_for_id(self.samples, highlighted_id)
                if sample:
                    await transcript_view.sync_sample(sample)
                    return

        # no sample to sync
        await transcript_view.sync_sample(None)


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
