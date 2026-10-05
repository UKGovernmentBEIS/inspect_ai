import ast
import sys
from pathlib import Path

import inspect_ai.core

CORE_DIR = Path(inspect_ai.core.__file__).parent

ALLOWED_THIRD_PARTY = {"pydantic", "pydantic_core", "typing_extensions", "shortuuid"}


def _module_name(path: Path) -> str:
    parts = path.relative_to(CORE_DIR).with_suffix("").parts
    return ".".join(
        ("inspect_ai.core", *(parts[:-1] if parts[-1] == "__init__" else parts))
    )


def _imported_modules(path: Path) -> set[str]:
    """Every module imported anywhere in the file, with relative imports resolved."""
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    nodes = list(ast.walk(ast.parse(path.read_text())))
    return {
        alias.name
        for node in nodes
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        ".".join(
            filter(
                None,
                (
                    package.rsplit(".", node.level - 1)[0] if node.level else None,
                    node.module,
                ),
            )
        )
        for node in nodes
        if isinstance(node, ast.ImportFrom)
    }


def _is_allowed(module: str) -> bool:
    top = module.split(".")[0]
    return (
        module == "inspect_ai.core"
        or module.startswith("inspect_ai.core.")
        or top in sys.stdlib_module_names
        or top in ALLOWED_THIRD_PARTY
    )


def test_core_imports_only_allowed_modules() -> None:
    disallowed = {
        str(path.relative_to(CORE_DIR)): sorted(
            module for module in _imported_modules(path) if not _is_allowed(module)
        )
        for path in sorted(CORE_DIR.rglob("*.py"))
    }
    assert not any(disallowed.values()), (
        f"inspect_ai.core imports disallowed modules: "
        f"{ {file: modules for file, modules in disallowed.items() if modules} }"
    )
