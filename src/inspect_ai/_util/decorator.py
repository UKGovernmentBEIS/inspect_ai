import ast
from logging import getLogger
from pathlib import Path
from typing import Any

from .error import exception_message
from .file import file

logger = getLogger(__name__)


def parse_decorators(
    path: Path, decorator_name: str
) -> list[tuple[str, dict[str, Any]]]:
    # read code from python source file
    if path.suffix.lower() == ".py":
        with file(path.as_posix(), "r", encoding="utf-8") as f:
            code = f.read()

    # read code from notebook
    elif path.suffix.lower() == ".ipynb":
        try:
            from inspect_ai._util.notebook import read_notebook_code
        except ImportError:
            return []

        code = read_notebook_code(path)

    # unsupported file type
    else:
        raise ModuleNotFoundError(f"Invalid extension for module file: {path.suffix}")

    # parse the top level decorators out of the code
    decorators: list[tuple[str, dict[str, Any]]] = []
    try:
        tree = ast.parse(code)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    result = parse_decorator(node, decorator, decorator_name)
                    if result:
                        decorators.append(result)
    except SyntaxError:
        pass

    return decorators


def parse_decorator(
    node: ast.FunctionDef, decorator: ast.expr, decorator_name: str
) -> tuple[str, dict[str, Any]] | None:
    if isinstance(decorator, ast.Name):
        if str(decorator.id) == decorator_name:
            return node.name, {}
    elif isinstance(decorator, ast.Call):
        if isinstance(decorator.func, ast.Name):
            if str(decorator.func.id) == decorator_name:
                return parse_decorator_name_and_params(node, decorator)
    return None


def parse_decorator_name_and_params(
    node: ast.FunctionDef, decorator: ast.Call
) -> tuple[str, dict[str, Any]]:
    name = node.name
    attribs: dict[str, Any] = {}
    for arg in decorator.keywords:
        if arg.arg is not None:
            try:
                value = ast.literal_eval(arg.value)
                if arg.arg == "name":
                    name = value
                else:
                    attribs[arg.arg] = value
            except ValueError as ex:
                # when parsing, we can't provide the values of expressions that execute code
                logger.debug(
                    f"Error parsing attribute {arg.arg} of {node.name}: {exception_message(ex)}"
                )
                pass
    return name, attribs
