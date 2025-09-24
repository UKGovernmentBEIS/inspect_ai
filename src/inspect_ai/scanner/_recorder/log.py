from typing import Any

from pydantic import BaseModel, Field
from shortuuid import uuid


class ScanScanner(BaseModel):
    scanner: str
    """Scanner name."""

    args: dict[str, Any] = Field(default_factory=dict)
    """Scanner arguments."""


class ScanSpec(BaseModel):
    scan_id: str = Field(default_factory=uuid)
    """Globally unique id for scan."""

    scan_file: str | None = Field(default=None)
    """Source file for scan."""

    scan_name: str = Field(default="scan")
    """Scan name (defaults to 'scan')."""

    # transcripts:


class ScanLog(BaseModel):
    pass
