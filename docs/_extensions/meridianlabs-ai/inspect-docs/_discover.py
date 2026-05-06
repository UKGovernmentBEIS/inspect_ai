"""Shared discovery helpers for inferring project metadata from pyproject.toml.

Imported by both `pre-render.py` (extension root) and
`filters/reference/filter.py` (two levels deeper). Each importer is
responsible for adding the extension root to `sys.path` before importing
this module.
"""

import tomllib
from pathlib import Path
from typing import Any


def _load_pyproject() -> dict[str, Any] | None:
    """Walk up from cwd looking for a pyproject.toml; return its parsed contents."""
    for directory in [Path.cwd(), *Path.cwd().parents]:
        pyproject = directory / "pyproject.toml"
        if not pyproject.is_file():
            continue
        try:
            with pyproject.open("rb") as f:
                return tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            return None
    return None


def discover_module_name() -> str | None:
    """Return the package import name from pyproject.toml, or None.

    Reads `[project].name` (PEP 621) or `[tool.poetry].name` and normalizes
    distribution names to import names by replacing `-` with `_`.
    """
    data = _load_pyproject()
    if data is None:
        return None
    name = data.get("project", {}).get("name") or (
        data.get("tool", {}).get("poetry", {}).get("name")
    )
    if isinstance(name, str) and name:
        return name.replace("-", "_")
    return None


def discover_cli(module_name: str) -> tuple[str, str] | None:
    """Return `(cli_name, entry_point)` from pyproject.toml `[project.scripts]`.

    Prefers a script whose entry-point value references `{module_name}._cli`
    (the convention this extension assumes). Falls back to the first script
    in the table if no such match exists. The entry point is returned as the
    raw `module:attribute` string from pyproject. Returns `None` when there
    are no scripts at all.
    """
    data = _load_pyproject()
    if data is None:
        return None
    scripts = data.get("project", {}).get("scripts") or (
        data.get("tool", {}).get("poetry", {}).get("scripts")
    )
    if not isinstance(scripts, dict) or not scripts:
        return None

    cli_marker = f"{module_name}._cli"
    for script_name, entry in scripts.items():
        if isinstance(entry, str) and cli_marker in entry:
            return script_name, entry

    # fall back to the first script
    name, entry = next(iter(scripts.items()))
    return (name, entry) if isinstance(entry, str) else None


def discover_cli_name(module_name: str) -> str | None:
    """Backwards-compatible helper returning just the CLI binary name."""
    info = discover_cli(module_name)
    return info[0] if info is not None else None
