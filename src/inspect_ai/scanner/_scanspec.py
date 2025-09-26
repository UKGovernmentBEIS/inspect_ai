from datetime import datetime
from typing import Any, NotRequired, Required, TypedDict

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
)
from shortuuid import uuid
from typing_extensions import Literal

from inspect_ai.model._model_config import ModelConfig


class ScanScanner(BaseModel):
    name: str
    """Scanner name."""

    params: dict[str, Any] = Field(default_factory=dict)
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
    """Configuration used for scan."""

    max_transcripts: int | None = Field(default=None)
    """Maximum number of concurrent transcripts (defaults to 10)."""

    limit: int | None = Field(default=None)
    """Transcript limit (maximum number of transcripts to read)."""

    shuffle: bool | int | None = Field(default=None)
    """Shuffle order of transcripts."""


class TranscriptField(TypedDict, total=False):
    name: Required[str]
    type: Required[str]
    tz: NotRequired[str]


class ScanTranscripts(BaseModel):
    """Transcripts target by a scan."""

    type: str
    """Transcripts backing store type (currently only 'eval_log')."""

    fields: list[TranscriptField]
    """Data types of transcripts fields."""

    data: str
    """Transcript data as a csv."""


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
    """Attributes of the @scanjob decorator."""

    scan_args: dict[str, Any] = Field(default_factory=dict)
    """Arguments used for invoking the scan (including defaults)."""

    scan_args_passed: dict[str, Any] = Field(default_factory=dict)
    """Arguments explicitly passed by caller for invoking the scan."""

    tags: list[str] | None = Field(default=None)
    """Tags associated with the scan."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional scan metadata."""

    model: ModelConfig | None = Field(default=None)
    """Model used for eval."""

    model_roles: dict[str, ModelConfig] | None = Field(default=None)
    """Model roles."""

    revision: ScanRevision | None = Field(default=None)
    """Source revision of scan."""

    packages: dict[str, str] = Field(default_factory=dict)
    """Package versions for scan."""

    config: ScanConfig = Field(default_factory=ScanConfig)
    """Scan configuration."""

    transcripts: ScanTranscripts
    """Transcripts to scan."""

    scanners: dict[str, ScanScanner]
    """Scanners to apply to transcripts."""

    @field_serializer("created")
    def serialize_created(self, created: datetime) -> str:
        return created.astimezone().isoformat()
