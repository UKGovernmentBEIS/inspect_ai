from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import cast

import pytest

from inspect_ai._display.textual.widgets.transcript import TranscriptView
from inspect_ai.dataset import Sample
from inspect_ai.event import Event, InfoEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.log import Transcript
from inspect_ai.log._samples import ActiveSample
from inspect_ai.util._checkpoint._transcript_store import CheckpointTranscriptStore


class _RaisingHistoryProvider:
    def __init__(self) -> None:
        self.event_count_calls = 0

    @property
    def event_count(self) -> int:
        self.event_count_calls += 1
        return 3

    def iter_events(self) -> Iterator[Event]:
        raise AssertionError("textual transcript view should use resident events")

    def events(self) -> Sequence[Event]:
        raise AssertionError("textual transcript view should use resident events")

    def recent_events(self, n: int | None = None) -> Sequence[Event]:
        raise AssertionError("textual transcript view should use resident events")

    def events_from(self, start: int) -> Sequence[Event]:
        raise AssertionError("textual transcript view should use resident events")

    def events_since_last(self, event_type: type[Event]) -> list[Event]:
        raise AssertionError("textual transcript view should use resident events")

    def attachments(self) -> Mapping[str, str]:
        return {}

    def attachment(self, hash: str) -> str | None:
        return None

    def import_checkpoint_events(
        self, transcript_store: CheckpointTranscriptStore
    ) -> int:
        raise AssertionError("textual transcript view should use resident events")


class _Sample:
    id = "sample"

    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript


@pytest.mark.anyio
async def test_textual_transcript_view_uses_resident_events(monkeypatch) -> None:
    provider = _RaisingHistoryProvider()
    transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=provider,
    )
    sample_init = SampleInitEvent(sample=Sample(input="input", id="sample"), state={})
    transcript._event(sample_init)
    transcript._event(InfoEvent(data="evicted"))
    transcript._event(InfoEvent(data="resident"))

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
        return []

    monkeypatch.setattr(TranscriptView, "remove_children", remove_children)
    monkeypatch.setattr(TranscriptView, "mount_all", mount_all)
    monkeypatch.setattr(TranscriptView, "_widgets_for_events", widgets_for_events)
    monkeypatch.setattr(TranscriptView, "batch", batch)
    monkeypatch.setattr(TranscriptView, "scroll_end", scroll_end)

    view = TranscriptView()
    view._active = True

    await view.sync_sample(cast(ActiveSample, _Sample(transcript)))

    assert provider.event_count_calls == 0
