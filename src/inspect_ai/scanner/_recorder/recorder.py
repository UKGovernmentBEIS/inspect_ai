from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Sequence

from inspect_ai.scanner._scanner.result import Result
from inspect_ai.scanner._scanspec import ScanSpec
from inspect_ai.scanner._transcript.types import TranscriptInfo

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class ScanResults:
    status: Literal["started", "complete"]
    spec: ScanSpec
    location: str
    scanners: dict[str, "pd.DataFrame"]


class ScanRecorder(abc.ABC):
    @abc.abstractmethod
    async def init(self, spec: ScanSpec, scans_location: str) -> None: ...

    @abc.abstractmethod
    async def resume(self, scan_location: str) -> ScanSpec: ...

    @abc.abstractmethod
    async def location(self) -> str: ...

    @abc.abstractmethod
    async def is_recorded(self, transcript: TranscriptInfo, scanner: str) -> bool: ...

    @abc.abstractmethod
    async def record(
        self, transcript: TranscriptInfo, scanner: str, results: Sequence[Result]
    ) -> None: ...

    @abc.abstractmethod
    async def flush(self) -> None: ...

    @abc.abstractmethod
    async def complete(self) -> ScanResults: ...

    @staticmethod
    @abc.abstractmethod
    async def spec(scan_location: str) -> ScanSpec: ...

    @staticmethod
    @abc.abstractmethod
    async def results(scan_location: str) -> ScanResults: ...
