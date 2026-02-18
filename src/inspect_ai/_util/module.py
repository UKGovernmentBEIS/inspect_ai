import sys
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType
from typing import Callable

from typing_extensions import overload


@overload
def load_module(
    module_path: Path, filter: Callable[[str], bool]
) -> ModuleType | None: ...


@overload
def load_module(module_path: Path, filter: None = None) -> ModuleType: ...


def load_module(
    module_path: Path, filter: Callable[[str], bool] | None = None
) -> ModuleType | None:
    if module_path.suffix == ".py":
        # bail if the code doesn't pass the filter
        with open(module_path, "r", encoding="utf-8") as file:
            if filter and not filter(file.read()):
                return None

        module_name = _derive_module_name(module_path) or module_path.as_posix()
        loader = SourceFileLoader(module_name, module_path.absolute().as_posix())
        spec = spec_from_loader(loader.name, loader)
        if not spec:
            raise ModuleNotFoundError(f"Module {module_name} not found")
        module = module_from_spec(spec)
        sys.modules[module_name] = module
        loader.exec_module(module)
        return module

    elif module_path.suffix == ".ipynb":
        try:
            from inspect_ai._util.notebook import NotebookLoader
        except ImportError:
            return None

        # bail if the code doesn't pass the filter
        def exec_filter(cells: list[str]) -> bool:
            code = "\n\n".join(cells)
            return not filter or filter(code)

        notebook_loader = NotebookLoader(exec_filter)
        return notebook_loader.load_module(module_path.as_posix())

    else:
        raise ModuleNotFoundError(
            f"Invalid extension for task file: {module_path.suffix}"
        )


def _derive_module_name(module_path: Path) -> str | None:
    """Derive an importable dotted module name from a file path.

    Finds the path relative to a sys.path entry and converts to a dotted name.
    When multiple sys.path entries match, prefers the shortest module name
    (fewest dots), which corresponds to the closest sys.path entry. This
    ensures the derived name is importable from the most specific path entry,
    which matters when multiprocess workers only receive a subset of sys.path.

    Returns None if the file is not under any sys.path entry.
    """
    resolved = module_path.resolve().with_suffix("")
    best: str | None = None
    for path_entry in sys.path:
        if not path_entry:
            continue
        try:
            relative = resolved.relative_to(Path(path_entry).resolve())
            candidate = ".".join(relative.parts)
            if best is None or candidate.count(".") < best.count("."):
                best = candidate
        except ValueError:
            continue
    return best
