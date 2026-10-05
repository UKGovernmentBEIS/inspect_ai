import ast
import importlib.util
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ImportScope = Literal["module", "function", "type_checking"]
"""Where an import statement sits: at module level, inside a function, or under
`if TYPE_CHECKING:`."""

DEFAULT_ALLOWED: tuple[str, ...] = (
    "pydantic",
    "pydantic_core",
    "typing_extensions",
    "shortuuid",
    "inspect_ai.core",
)
"""Modules (and their submodules) allowed besides the standard library."""


@dataclass(frozen=True)
class ImportViolation:
    """An import of a module that is not allowed."""

    file: str
    """Source file containing the import."""

    line: int
    """Line number of the import statement."""

    module: str
    """Imported module, with relative imports resolved."""

    scope: ImportScope
    """Where the import statement sits."""


def check_imports(name: str, allowed: Iterable[str] = ()) -> list[ImportViolation]:
    """Check every import in a module or package against an allowlist.

    Reads source files with `ast` rather than importing them, so the module's own
    code does not run. Locating a submodule (e.g. `"pkg.sub"`) imports its parent
    packages, as `importlib.util.find_spec` does. For a package, every `.py` file
    under it is checked. Imports done at runtime (`importlib.import_module()`,
    `__import__`, `exec`) are not seen.

    Allowed: the standard library, `DEFAULT_ALLOWED`, `allowed`, and modules of
    `name` itself. An entry allows the module and its submodules.

    Not supported: modules inside a zip file on `sys.path` (for a package no
    files are found, so nothing is reported; a single module raises
    `NotADirectoryError`), and symlinked directories inside a package (not
    followed, so their files are not checked).

    Args:
        name: Module or package name, e.g. `"my_monitors"`.
        allowed: Additional allowed module names.

    Returns:
        Violations ordered by file and line; empty if every import is allowed.

    Raises:
        ModuleNotFoundError: `name` can't be found.
        ValueError: `name` has no Python source, e.g. a built-in, frozen,
            compiled-only or extension module.
        SyntaxError: A checked file isn't valid Python.
        NotADirectoryError: `name` is a single module inside a zip file.
        Exception: Whatever a parent package of `name` raises when imported.
    """
    spec = importlib.util.find_spec(name)
    if spec is None:
        raise ModuleNotFoundError(f"No module named '{name}'")
    prefixes = (*DEFAULT_ALLOWED, *allowed, name)
    if spec.submodule_search_locations:
        roots = [Path(location) for location in spec.submodule_search_locations]
        files = [
            (path, _module_name(name, root, path))
            for root in roots
            for path in sorted(root.rglob("*.py"))
        ]
    elif spec.has_location and spec.origin and spec.origin.endswith(".py"):
        files = [(Path(spec.origin), name)]
    else:
        raise ValueError(
            f"Module '{name}' has no Python source to check (origin: {spec.origin})"
        )
    return [
        violation
        for path, module in files
        for violation in check_file(path, module, prefixes)
    ]


def check_file(
    path: Path, module: str, allowed: Sequence[str]
) -> list[ImportViolation]:
    """Check every import in one source file against an allowlist.

    Args:
        path: Source file.
        module: Module name of the file (used to resolve relative imports); for a
            package `__init__.py`, the package name.
        allowed: Allowed module names besides the standard library. An entry
            allows the module and its submodules.

    Returns:
        Violations ordered by line; empty if every import is allowed.
    """
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    return sorted(
        (
            ImportViolation(
                file=str(path), line=node.lineno, module=imported, scope=scope
            )
            for node, scope in _imports(ast.parse(path.read_bytes(), str(path)))
            for imported in _imported_modules(node, package)
            if not _is_allowed(imported, allowed)
        ),
        key=lambda violation: violation.line,
    )


def _module_name(package: str, root: Path, path: Path) -> str:
    parts = path.relative_to(root).with_suffix("").parts
    return ".".join((package, *(parts[:-1] if parts[-1] == "__init__" else parts)))


def _imports(
    tree: ast.Module,
) -> Iterator[tuple[ast.Import | ast.ImportFrom, ImportScope]]:
    """Every import statement in `tree`, with where it sits."""

    def visit(
        nodes: Iterable[ast.AST], scope: ImportScope
    ) -> Iterator[tuple[ast.Import | ast.ImportFrom, ImportScope]]:
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                yield node, scope
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner: ImportScope = (
                    "type_checking" if scope == "type_checking" else "function"
                )
                yield from visit(ast.iter_child_nodes(node), inner)
            elif isinstance(node, ast.If) and _is_type_checking(node.test):
                yield from visit(node.body, "type_checking")
                yield from visit(node.orelse, scope)
            else:
                yield from visit(ast.iter_child_nodes(node), scope)

    return visit(tree.body, "module")


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _imported_modules(node: ast.Import | ast.ImportFrom, package: str) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    base = package.rsplit(".", node.level - 1)[0] if node.level else None
    return [".".join(part for part in (base, node.module) if part)]


def _is_allowed(module: str, allowed: Sequence[str]) -> bool:
    return module.split(".")[0] in sys.stdlib_module_names or any(
        module == prefix or module.startswith(f"{prefix}.") for prefix in allowed
    )
