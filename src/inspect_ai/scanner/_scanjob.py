from dataclasses import dataclass
from typing import Any, cast

from shortuuid import uuid

from inspect_ai._util.registry import (
    RegistryDict,
    registry_create_from_dict,
    registry_log_name,
    registry_params,
)
from inspect_ai.scanner._recorder.spec import ScanScanner, ScanSpec
from inspect_ai.scanner._recorder.types import scan_recorder_type_for_location
from inspect_ai.scanner._scandef import ScanDef
from inspect_ai.scanner._scanner.scanner import Scanner
from inspect_ai.scanner._transcript.database import transcripts_from_snapshot
from inspect_ai.scanner._transcript.transcripts import Transcripts


@dataclass
class ScanJob:
    spec: ScanSpec
    """Scan specification."""

    transcripts: Transcripts
    """Corpus of transcripts to scan."""

    scanners: dict[str, Scanner[Any]]
    """Scanners to apply to transcripts."""


async def create_scan_job(
    scandef: ScanDef, transcripts: Transcripts | None = None, scan_id: str | None = None
) -> ScanJob:
    # resolve id
    scan_id = scan_id or uuid()

    # resolve transcripts
    transcripts = transcripts or scandef.transcripts
    if transcripts is None:
        raise ValueError("No 'transcripts' specified for scan.")

    # create scan spec
    async with transcripts:
        spec = ScanSpec(
            scan_id=scan_id,
            scan_name=scandef.name,
            transcripts=await transcripts.snapshot(),
            scanners=_spec_scanners(scandef.scanners),
        )

    return ScanJob(spec=spec, transcripts=transcripts, scanners=scandef.scanners)


async def resume_scan_job(scan_location: str) -> ScanJob:
    recorder_type = scan_recorder_type_for_location(scan_location)
    spec = await recorder_type.spec(scan_location)
    return ScanJob(
        spec=spec,
        transcripts=await transcripts_from_snapshot(spec.transcripts),
        scanners=_scanners_from_spec(spec),
    )


def _spec_scanners(scanners: dict[str, Scanner[Any]]) -> dict[str, ScanScanner]:
    return {
        k: ScanScanner(name=registry_log_name(v), params=registry_params(v))
        for k, v in scanners.items()
    }


def _scanners_from_spec(spec: ScanSpec) -> dict[str, Scanner[Any]]:
    return {
        k: cast(
            Scanner[Any],
            registry_create_from_dict(
                RegistryDict(type="scanner", name=v.name, params=v.params)
            ),
        )
        for k, v in spec.scanners.items()
    }
