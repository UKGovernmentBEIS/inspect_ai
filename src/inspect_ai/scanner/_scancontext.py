from dataclasses import dataclass
from typing import Any, cast

from shortuuid import uuid

from inspect_ai._util.registry import (
    RegistryDict,
    registry_create_from_dict,
    registry_log_name,
    registry_params,
)
from inspect_ai.model._model import Model, ModelName
from inspect_ai.model._model_config import (
    ModelConfig,
    model_args_for_log,
    model_roles_to_model_roles_config,
)

from ._recorder.factory import scan_recorder_type_for_location
from ._scanjob import ScanJob
from ._scanner.scanner import Scanner
from ._scanspec import (
    ScanConfig,
    ScanScanner,
    ScanSpec,
)
from ._transcript.database import transcripts_from_snapshot
from ._transcript.transcripts import Transcripts


@dataclass
class ScanContext:
    spec: ScanSpec
    """Scan specification."""

    transcripts: Transcripts
    """Corpus of transcripts to scan."""

    scanners: dict[str, Scanner[Any]]
    """Scanners to apply to transcripts."""


async def create_scan(
    scanjob: ScanJob,
    transcripts: Transcripts | None,
    model: Model,
    model_args: dict[str, Any],
    model_roles: dict[str, Model] | None,
    tags: list[str] | None,
    metadata: dict[str, Any] | None,
    config: ScanConfig | None,
    scan_id: str | None,
) -> ScanContext:
    # resolve id
    scan_id = scan_id or uuid()

    # resolve transcripts
    transcripts = transcripts or scanjob.transcripts
    if transcripts is None:
        raise ValueError("No 'transcripts' specified for scan.")

    # create scan spec
    async with transcripts:
        spec = ScanSpec(
            job_id=scan_id,
            job_name=scanjob.name,
            config=config or ScanConfig(),
            transcripts=await transcripts.snapshot(),
            scanners=_spec_scanners(scanjob.scanners),
            tags=tags,
            metadata=metadata,
            model=ModelConfig(
                model=str(ModelName(model)),
                config=model.config,
                base_url=model.api.base_url,
                args=model_args_for_log(model_args),
            ),
            model_roles=model_roles_to_model_roles_config(model_roles),
        )

    return ScanContext(spec=spec, transcripts=transcripts, scanners=scanjob.scanners)


async def resume_scan(scan_location: str) -> ScanContext:
    recorder_type = scan_recorder_type_for_location(scan_location)
    spec = await recorder_type.spec(scan_location)
    return ScanContext(
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
