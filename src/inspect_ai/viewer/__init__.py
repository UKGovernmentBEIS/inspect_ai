"""Public viewer-configuration surface.

Typed Pydantic classes that a `Task` author passes via the `viewer=` argument
(see `Task.viewer`) to control how the Inspect log viewer renders scanner
output in the sidebar.
"""

from inspect_ai._util.deprecation import relocated_module_attribute
from inspect_ai.viewer._config import (
    MetadataField,
    SampleScoreView,
    SampleScoreViewSort,
    ScannerResultField,
    ScannerResultView,
    ScoreColorScale,
    TaskSamplesColumn,
    TaskSamplesColumnId,
    TaskSamplesSort,
    TaskSamplesView,
    ViewerConfig,
)

__all__ = [
    "MetadataField",
    "SampleScoreView",
    "SampleScoreViewSort",
    "ScannerResultField",
    "ScannerResultView",
    "ScoreColorScale",
    "TaskSamplesColumn",
    "TaskSamplesColumnId",
    "TaskSamplesSort",
    "TaskSamplesView",
    "ViewerConfig",
]


_RENAMED_IN = "0.3.218"
_REMOVED_IN = "0.4"

for old, new in [
    ("SamplesView", "TaskSamplesView"),
    ("SamplesColumn", "TaskSamplesColumn"),
    ("SamplesSort", "TaskSamplesSort"),
]:
    relocated_module_attribute(
        old,
        f"inspect_ai.viewer._config.{new}",
        _RENAMED_IN,
        _REMOVED_IN,
        f"'{old}' has been renamed to '{new}'. Please update your import.",
    )
