import json
from dataclasses import dataclass
from typing import Any, cast

from upath import UPath

from inspect_ai._util.file import file
from inspect_ai._util.registry import (
    RegistryDict,
    registry_create_from_dict,
    registry_info,
    registry_log_name,
    registry_params,
)

from ._scanner.scanner import Scanner
from ._transcript.database import transcripts_from_spec
from ._transcript.transcripts import Transcripts

SCAN_OPTIONS_JSON = "scan.json"

SCAN_ID = "scan_id"
SCAN_NAME = "scan_name"
TRANSCRIPTS = "transcripts"
SCANNERS = "scanners"


@dataclass
class ScanOptions:
    scan_id: str
    scan_name: str
    transcripts: Transcripts
    scanners: dict[str, Scanner[Any]]


async def write_scan_options(scan_dir: UPath, options: ScanOptions) -> None:
    options_dict = {
        SCAN_ID: options.scan_id,
        SCAN_NAME: options.scan_name,
        TRANSCRIPTS: options.transcripts.save_spec(),
        SCANNERS: {
            k: RegistryDict(
                type=registry_info(v).type,
                name=registry_log_name(v),
                params=registry_params(v),
            )
            for k, v in options.scanners.items()
        },
    }
    with file((scan_dir / SCAN_OPTIONS_JSON).as_posix(), "w") as f:
        f.write(json.dumps(options_dict))


async def read_scan_options(scan_dir: UPath) -> ScanOptions | None:
    options_json = scan_dir / SCAN_OPTIONS_JSON
    if options_json.exists():
        with file((scan_dir / SCAN_OPTIONS_JSON).as_posix(), "r") as f:
            options_dict = json.loads(f.read())
            return ScanOptions(
                scan_id=options_dict[SCAN_ID],
                scan_name=options_dict[SCAN_NAME],
                transcripts=transcripts_from_spec(options_dict[TRANSCRIPTS]),
                scanners={
                    k: cast(Scanner[Any], registry_create_from_dict(v))
                    for k, v in options_dict[SCANNERS].items()
                },
            )
    else:
        return None
