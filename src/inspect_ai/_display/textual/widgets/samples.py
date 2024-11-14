from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

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
    """

    def __init__(self) -> None:
        super().__init__()
        self.samples: list[ActiveSample] = []

    def compose(self) -> ComposeResult:
        yield OptionList()
        yield Static("Foobar")

    def set_samples(self, samples: list[ActiveSample]) -> None:
        self.samples = samples.copy()
        options = self.query_one(OptionList)
        highlighted_id = (
            options.get_option_at_index(options.highlighted).id
            if options.highlighted is not None
            else None
        )
        options.clear_options()
        options.add_options(
            [
                Option(f"{sample.task}: {sample.sample.id}", id=sample.id)
                for sample in self.samples
            ]
        )
        if highlighted_id is not None:
            index = sample_index_for_id(samples, highlighted_id)
            if index != -1:
                options.highlighted = index


def sample_index_for_id(samples: list[ActiveSample], id: str) -> int:
    for i, sample in enumerate(samples):
        if sample.id == id:
            return i
    return -1
