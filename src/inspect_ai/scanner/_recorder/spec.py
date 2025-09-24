from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SkipValidation,
    field_serializer,
)
from shortuuid import uuid
from typing_extensions import Literal


class ScanScanner(BaseModel):
    scanner: str
    """Scanner name."""

    args: dict[str, Any] = Field(default_factory=dict)
    """Scanner arguments."""


class ScanRevision(BaseModel):
    """Git revision for scan."""

    type: Literal["git"]
    """Type of revision (currently only "git")"""

    origin: str
    """Revision origin server"""

    commit: str
    """Revision commit."""


class ScanConfig(BaseModel):
    """Configuration used for evaluation."""

    limit: int | None = Field(default=None)
    """Transcript limit (maximum number of transcripts to read)."""

    shuffle: bool | int | None = Field(default=None)
    """Shuffle order of transcripts."""


class ScanTranscripts:
    """Transcripts target by a scan."""

    fields: list[dict[Literal["name", "type", "tz"], str]]
    data: str


class ScanSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    scan_id: str = Field(default_factory=uuid)
    """Globally unique id for scan."""

    created: datetime = Field(default_factory=datetime.now)
    """Time created."""

    scan_file: str | None = Field(default=None)
    """Source file for scan."""

    scan_name: str = Field(default="scan")
    """Scan name (defaults to 'scan')."""

    scan_attribs: dict[str, Any] = Field(default_factory=dict)
    """Attributes of the @scandef decorator."""

    scan_args: dict[str, Any] = Field(default_factory=dict)
    """Arguments used for invoking the scan (including defaults)."""

    scan_args_passed: dict[str, Any] = Field(default_factory=dict)
    """Arguments explicitly passed by caller for invoking the scan."""

    tags: list[str] | None = Field(default=None)
    """Tags associated with the scan."""

    revision: ScanRevision | None = Field(default=None)
    """Source revision of scan."""

    packages: dict[str, str] = Field(default_factory=dict)
    """Package versions for scan."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional scan metadata."""

    config: ScanConfig = Field(default_factory=ScanConfig)
    """Scan configuration."""

    transcripts: ScanTranscripts
    """Transcripts to scan."""

    scanners: SkipValidation[dict[str, ScanScanner]]
    """Scanners to apply to transcripts."""

    @field_serializer("created")
    def serialize_created(self, created: datetime) -> str:
        return created.astimezone().isoformat()
