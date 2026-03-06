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

        module_name = module_path.as_posix()
        loader = SourceFileLoader(module_name, module_path.absolute().as_posix())
        spec = spec_from_loader(loader.name, loader)
        if not spec:
            raise ModuleNotFoundError(f"Module {module_name} not found")
        module = module_from_spec(spec)
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
