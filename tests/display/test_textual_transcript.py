from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import cast

import pytest

from inspect_ai._display.textual.widgets.transcript import TranscriptView
from inspect_ai.dataset import Sample
from inspect_ai.event import Event, InfoEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.log._samples import ActiveSample
from inspect_ai.log._transcript import Transcript


class _Sample:
    id = "sample"

    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript


@pytest.mark.anyio
async def test_textual_transcript_view_uses_resident_events(monkeypatch) -> None:
    sample_init = SampleInitEvent(sample=Sample(input="input", id="sample"), state={})
    evicted = InfoEvent(data="evicted")
    resident = InfoEvent(data="resident")
    transcript = Transcript(
        [sample_init, evicted, resident], bounded=True, resident_tail=1
    )
    rendered_events: Sequence[Event] | None = None

    async def remove_children(self: TranscriptView) -> None:
        pass

    async def mount_all(self: TranscriptView, widgets: object) -> None:
        pass

    @asynccontextmanager
    async def batch(self: TranscriptView) -> AsyncIterator[None]:
        yield

    def scroll_end(self: TranscriptView, animate: bool = False) -> None:
        pass

    def widgets_for_events(
        self: TranscriptView, events: Sequence[Event]
    ) -> list[object]:
        nonlocal rendered_events
        rendered_events = events
        return []

    monkeypatch.setattr(TranscriptView, "remove_children", remove_children)
    monkeypatch.setattr(TranscriptView, "mount_all", mount_all)
    monkeypatch.setattr(TranscriptView, "_widgets_for_events", widgets_for_events)
    monkeypatch.setattr(TranscriptView, "batch", batch)
    monkeypatch.setattr(TranscriptView, "scroll_end", scroll_end)

    view = TranscriptView()
    view._active = True

    await view.sync_sample(cast(ActiveSample, _Sample(transcript)))

    assert rendered_events is transcript.history.resident_events
    assert rendered_events == [sample_init, resident]
