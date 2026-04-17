"""Unit tests for `_validated_path` in the text_editor sandbox tool."""

import pytest
from inspect_sandbox_tools._in_process_tools._text_editor.text_editor import (
    _validated_path,
)
from inspect_sandbox_tools._util.common_types import ToolException


def test_validated_path_rejects_too_long_filename() -> None:
    """Pathological long path from the model must raise ToolException, not OSError.

    Regression: UKGovernmentBEIS/inspect_ai#3689 — a 5000-char path component
    caused `path.exists()` to raise `OSError(ENAMETOOLONG)`, which propagated as
    JSON-RPC `-32098` and crashed the eval instead of being fed back to the model.
    """
    with pytest.raises(ToolException):
        _validated_path("a" * 5000, "view")
