import json
from typing import Any, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SkipValidation,
    field_serializer,
    field_validator,
)
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


class ScanOptions(BaseModel):
    """Scan options."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    scan_id: str
    """Unique identifier (uuid) for scan."""

    scan_name: str = Field(default="scan")
    """Scan name (defaults to 'scan' if not specified)"""

    transcripts: Transcripts
    """Corpus of transcripts to scan."""

    scanners: SkipValidation[dict[str, Scanner[Any]]]
    """Scanners to apply to transcripts."""

    @field_serializer("transcripts")
    def serialize_transcripts(self, value: Transcripts) -> dict[str, Any]:
        """Serialize Transcripts object to its spec dictionary."""
        return value.save_spec()

    @field_validator("transcripts", mode="before")
    @classmethod
    def validate_transcripts(cls, value: Any) -> Transcripts:
        """Validate and reconstruct Transcripts from spec dictionary."""
        if isinstance(value, Transcripts):
            return value
        elif isinstance(value, dict):
            return transcripts_from_spec(value)
        else:
            raise ValueError(f"Invalid transcripts value: {value}")

    @field_serializer("scanners")
    def serialize_scanners(
        self, value: dict[str, Scanner[Any]]
    ) -> dict[str, RegistryDict]:
        """Serialize Scanner objects to RegistryDict format."""
        return {
            k: RegistryDict(
                type=registry_info(v).type,
                name=registry_log_name(v),
                params=registry_params(v),
            )
            for k, v in value.items()
        }

    @field_validator("scanners", mode="before")
    @classmethod
    def validate_scanners(cls, value: Any) -> dict[str, Scanner[Any]]:
        """Validate and reconstruct Scanner objects from RegistryDict format."""
        if isinstance(value, dict):
            # Check if it's already Scanner objects or needs to be reconstructed
            if value:
                first_val = next(iter(value.values()))
                if isinstance(first_val, dict) and "type" in first_val:
                    # It's a dict of RegistryDicts, need to reconstruct
                    return {
                        k: cast(Scanner[Any], registry_create_from_dict(v))
                        for k, v in value.items()
                    }
            # Assume it's already Scanner objects
            return value
        else:
            raise ValueError(f"Invalid scanners value: {value}")


SCAN_OPTIONS_JSON = "scan.json"


async def write_scan_options(scan_dir: UPath, options: ScanOptions) -> None:
    # Use Pydantic's model_dump to get the serialized dictionary
    options_dict = options.model_dump(mode="json")
    with file((scan_dir / SCAN_OPTIONS_JSON).as_posix(), "w") as f:
        f.write(json.dumps(options_dict))


async def read_scan_options(scan_dir: UPath) -> ScanOptions | None:
    options_json = scan_dir / SCAN_OPTIONS_JSON
    if options_json.exists():
        with file((scan_dir / SCAN_OPTIONS_JSON).as_posix(), "r") as f:
            options_dict = json.loads(f.read())
            # Use Pydantic's model_validate to reconstruct the object
            return ScanOptions.model_validate(options_dict)
    else:
        return None
