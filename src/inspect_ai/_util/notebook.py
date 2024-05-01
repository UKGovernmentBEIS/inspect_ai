import io
import sys
import types
from pathlib import Path
from typing import Callable

from IPython import get_ipython  # type: ignore
from IPython.core.interactiveshell import InteractiveShell
from nbformat import NBFormatError, ValidationError, read
from nbformat.reader import NotJSONError

# from https://jupyter-notebook.readthedocs.io/en/stable/examples/Notebook/Importing%20Notebooks.html


class NotebookLoader(object):
    """Module Loader for Jupyter Notebooks"""

    def __init__(self, exec_filter: Callable[[list[str]], bool] | None = None) -> None:
        self.shell = InteractiveShell.instance()
        self.exec_filter = exec_filter

    def load_module(self, fullname: str) -> types.ModuleType:
        # load the notebook object
        with io.open(fullname, "r", encoding="utf-8") as f:
            nb = read(f, 4)  # type: ignore

        # create the module and add it to sys.modules
        # if name in sys.modules:
        #    return sys.modules[name]
        mod = types.ModuleType(fullname)
        mod.__file__ = fullname
        mod.__loader__ = self
        mod.__dict__["get_ipython"] = get_ipython
        sys.modules[fullname] = mod

        # extra work to ensure that magics that would affect the user_ns
        # actually affect the notebook module's ns
        save_user_ns = self.shell.user_ns
        self.shell.user_ns = mod.__dict__

        try:
            # get source code for all the calls
            cells_code: list[str] = []
            for cell in nb.cells:
                # transform the input to executable Python for each cell
                if cell.cell_type == "code":
                    code = self.shell.input_transformer_manager.transform_cell(
                        cell.source
                    )
                    cells_code.append(code)

            # check the exec filter to make sure we should execute the
            # notebook cells, if not just return an empty module
            if self.exec_filter and not self.exec_filter(cells_code):
                del sys.modules[fullname]
                return mod

            # run the code in each cell
            for code in cells_code:
                exec(code, mod.__dict__)

            return mod
        finally:
            self.shell.user_ns = save_user_ns


def read_notebook_code(path: Path) -> str:
    try:
        # load the notebook object
        with io.open(path, "r", encoding="utf-8") as f:
            nb = read(f, 4)  # type: ignore
    except NotJSONError:
        return ""
    except ValidationError:
        return ""
    except NBFormatError:
        return ""

    # for dealing w/ magics
    shell = InteractiveShell.instance()

    # get the code
    lines: list[str] = []
    for cell in nb.cells:
        # transform the input to executable Python for each cell
        if cell.cell_type == "code":
            code = shell.input_transformer_manager.transform_cell(cell.source)
            lines.append(code)
    return "\n".join(lines)
