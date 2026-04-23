from typing import Literal

from pydantic import BaseModel, Field


class ScannerResultField(BaseModel):
    """A built-in scanner-result section (e.g. `value`, `explanation`)."""

    kind: Literal["builtin"] = "builtin"

    name: Literal[
        "explanation",
        "label",
        "value",
        "validation",
        "answer",
        "metadata",
    ]
    """Which built-in section to render."""

    label: str | None = None
    """Override the section header text (e.g. `"Explanation" → "Rationale"`)."""

    collapsed: bool = False
    """Whether the field should be collapsed by default."""


class MetadataField(BaseModel):
    """A metadata key promoted out of metadata into a top level value."""

    kind: Literal["metadata"] = "metadata"

    key: str
    """The `metadata[key]` entry to promote into its own section."""

    label: str | None = None
    """Override the section header text. Defaults to `key` when unset."""

    collapsed: bool = False
    """Whether the field should be collapsed by default."""


class ScannerResultView(BaseModel):
    """How the scann results should render the results."""

    fields: list[ScannerResultField | MetadataField | str] | None = None
    """Ordered list of sections to render. List order is render order; `None` means fall back to the built-in default order."""

    exclude_fields: list[ScannerResultField | MetadataField | str] = Field(
        default_factory=list
    )
    """Fields to suppress. For a `ScannerResultField` entry, the matching
    section is removed from the resolved `fields` list (useful to subtract
    from the default order). For a `MetadataField` entry, the key is
    additionally removed from the generic `metadata` section's dump."""


class ViewerConfig(BaseModel):
    """Top-level viewer configuration.

    `scanner_result_view` keys are fnmatch-style glob patterns (`"*"`,
    ``"audit_*"``, exact names). Pass a ScannerResultView to apply a single
    configuration to every scanner.
    """

    scanner_result_view: ScannerResultView | dict[str, ScannerResultView] = Field(
        default_factory=dict
    )
    """Glob-keyed map from scanner name pattern to its sidebar config. May also
    be a bare `ScannerResultView`."""
