"""Import hygiene for `import inspect_ai` and the `inspect` CLI entry point.

The `acp` package builds its full protocol schema (a large set of pydantic
models) when imported, and importing any `acp.*` submodule runs that too. It
used to be the single largest cost of `inspect --version`, so every module on
the eager import path defers its `acp` imports to first use. This guards
against a new module-level import putting it back.
"""

import subprocess
import sys

import pytest

_REPORT_ACP_MODULES = (
    "import sys; "
    "print(sorted(m for m in sys.modules if m == 'acp' or m.startswith('acp.')))"
)


@pytest.mark.parametrize("module", ["inspect_ai", "inspect_ai._cli.main"])
def test_import_does_not_load_acp(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}; {_REPORT_ACP_MODULES}"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]", (
        f"`import {module}` eagerly loaded the acp package: {result.stdout.strip()}"
    )
