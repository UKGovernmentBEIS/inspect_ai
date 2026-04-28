"""Public viewer-configuration surface.

Typed Pydantic classes that a `Task` author passes via the `viewer=` argument
(see `Task.viewer`) to control how the Inspect log viewer renders scanner
output in the sidebar.
"""

from inspect_ai.viewer._config import (
    MetadataField,
    ScannerResultField,
    ScannerResultView,
    ViewerConfig,
)

__all__ = [
    "MetadataField",
    "ScannerResultField",
    "ScannerResultView",
    "ViewerConfig",
]
