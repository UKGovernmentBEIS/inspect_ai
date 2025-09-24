from typing import Any, Sequence

from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai.scanner._scanner.scanner import Scanner
from inspect_ai.scanner._transcript.transcripts import Transcripts


class ScanDef:
    def __init__(
        self,
        *,
        transcripts: Transcripts | None = None,
        scanners: Sequence[Scanner[Any] | tuple[str, Scanner[Any]]]
        | dict[str, Scanner[Any]],
    ):
        # alias to transcripts
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

    @property
    def transcripts(self) -> Transcripts | None:
        return self._trancripts

    @property
    def scanners(self) -> dict[str, Scanner[Any]]:
        return self._scanners
