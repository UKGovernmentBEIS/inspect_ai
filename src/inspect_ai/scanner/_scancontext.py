from dataclasses import dataclass
from pathlib import Path
from typing import Any, Set, cast

import importlib_metadata

from inspect_ai._util.constants import PKG_NAME
from inspect_ai._util.git import git_context
from inspect_ai._util.module import load_module
from inspect_ai._util.path import cwd_relative_path
from inspect_ai._util.registry import (
    RegistryDict,
    is_registry_object,
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
from ._scanjob import SCANJOB_FILE_ATTR, ScanJob
from ._scanner.scanner import SCANNER_FILE_ATTR, Scanner
from ._scanner.types import ScannerInput
from ._scanspec import (
    ScanConfig,
    ScanRevision,
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

    scanners: dict[str, Scanner[ScannerInput]]
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
) -> ScanContext:
    # resolve transcripts
    transcripts = transcripts or scanjob.transcripts
    if transcripts is None:
        raise ValueError("No 'transcripts' specified for scan.")

    # get revision and package version
    git = git_context()
    revision = (
        ScanRevision(type="git", origin=git.origin, commit=git.commit) if git else None
    )
    packages = {PKG_NAME: importlib_metadata.version(PKG_NAME)}

    # create scan spec
    async with transcripts:
        spec = ScanSpec(
            job_file=job_file(scanjob),
            job_name=scanjob.name,
            job_args=job_args(scanjob),
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
            revision=revision,
            packages=packages,
        )

    return ScanContext(spec=spec, transcripts=transcripts, scanners=scanjob.scanners)


async def resume_scan(scan_location: str) -> ScanContext:
    # load the spec
    recorder_type = scan_recorder_type_for_location(scan_location)
    spec = await recorder_type.spec(scan_location)

    return ScanContext(
        spec=spec,
        transcripts=await transcripts_from_snapshot(spec.transcripts),
        scanners=_scanners_from_spec(spec),
    )


def _spec_scanners(
    scanners: dict[str, Scanner[ScannerInput]],
) -> dict[str, ScanScanner]:
    return {
        k: ScanScanner(
            name=registry_log_name(v), file=scanner_file(v), params=registry_params(v)
        )
        for k, v in scanners.items()
    }


def _scanners_from_spec(spec: ScanSpec) -> dict[str, Scanner[ScannerInput]]:
    loaded: Set[str] = set()
    scanners: dict[str, Scanner[ScannerInput]] = {}
    for name, scanner in spec.scanners.items():
        # we need to ensure that any files scanners were defined in have been loaded/parsed
        if scanner.file is not None and scanner.file not in loaded:
            load_module(Path(scanner.file))
            loaded.add(scanner.file)

        # create the scanner
        scanners[name] = cast(
            Scanner[ScannerInput],
            registry_create_from_dict(
                RegistryDict(type="scanner", name=scanner.name, params=scanner.params)
            ),
        )

    return scanners


def scanner_file(scanner: Scanner[ScannerInput]) -> str | None:
    file = cast(str | None, getattr(scanner, SCANNER_FILE_ATTR, None))
    if file:
        return cwd_relative_path(file)
    else:
        return None


def job_file(scanjob: ScanJob) -> str | None:
    file = cast(str | None, getattr(scanjob, SCANJOB_FILE_ATTR, None))
    if file:
        return cwd_relative_path(file)
    else:
        return None


def job_args(scanjob: ScanJob) -> dict[str, Any] | None:
    if is_registry_object(scanjob):
        return dict(registry_params(scanjob))
    else:
        return None
