from typing import Any, Sequence

from inspect_ai._util.registry import (
    is_registry_object,
    registry_info,
    registry_unqualified_name,
)
from inspect_ai.scanner._scanner.scanner import Scanner
from inspect_ai.scanner._transcript.transcripts import Transcripts


class ScanDef:
    def __init__(
        self,
        *,
        transcripts: Transcripts | None = None,
        scanners: Sequence[Scanner[Any] | tuple[str, Scanner[Any]]]
        | dict[str, Scanner[Any]],
        name: str | None = None,
    ):
        # save transcripts
        self._trancripts = transcripts

        # resolve scanners and confirm unique names
        self._scanners: dict[str, Scanner[Any]] = {}
        if isinstance(scanners, dict):
            self._scanners = scanners
        else:
            for scanner in scanners:
                if isinstance(scanner, tuple):
                    name, scanner = scanner
                else:
                    name = registry_unqualified_name(scanner)
                if name in self._scanners:
                    raise ValueError(
                        f"Scanners must have unique names (found duplicate name '{name}'). Use a tuple of str,Scanner to explicitly name a scanner."
                    )
                self._scanners[name] = scanner

        # save name
        self._name = name

    @property
    def name(self) -> str:
        if self._name is not None:
            return self._name
        elif is_registry_object(self):
            return registry_info(self).name
        else:
            return "task"

    @property
    def transcripts(self) -> Transcripts | None:
        return self._trancripts

    @property
    def scanners(self) -> dict[str, Scanner[Any]]:
        return self._scanners
