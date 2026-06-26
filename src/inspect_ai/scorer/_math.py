"""Safe mathematical answer extraction, parsing, and comparison."""

from __future__ import annotations

import ast
import math as stdlib_math
import re
from dataclasses import dataclass
from typing import Any, Literal

import anyio
from anyio.lowlevel import RunVar
from anyio.to_process import run_sync

from inspect_ai._util.error import PrerequisiteError, pip_dependency_error
from inspect_ai.solver._task_state import TaskState

from ._metric import CORRECT, INCORRECT, Score
from ._metrics import accuracy, stderr
from ._scorer import Scorer, scorer
from ._target import Target

_PARSER_PACKAGE = "latex2sympy2-extended"
_PARSER_VERSION = "1.11.0"

_MAX_COMPLETION_CHARS = 1_000_000
_MAX_CANDIDATE_CHARS = 4_096
_MAX_NESTING = 64
_MAX_COMMANDS = 256
_MAX_OPERATORS = 1_024
_MAX_DIGIT_RUN = 256
_MAX_TOTAL_DIGITS = 2_048
_MAX_MATRIX_CELLS = 256
_MAX_EXPRESSION_NODES = 512
_MAX_EXPRESSION_DEPTH = 64
_MAX_EXPRESSION_ARGS = 128
_MAX_SYMBOLS = 64
_MAX_SYMBOL_CHARS = 128
_MAX_INTEGER_BITS = 4_096
_SYMBOLIC_POWER_EXPONENT_LIMIT = 10_000
_MAX_FACTORIAL_ARGUMENT = 10_000

_TARGET_TIMEOUT_SECONDS = 2.0
_ANSWER_TIMEOUT_SECONDS = 2.0
_COLD_WORKER_TIMEOUT_SECONDS = 10.0
_MATH_WORKERS = 4

_BOX_START = re.compile(
    r"(?:\\(?:beginboxed|boxed|fbox)|(?<![A-Za-z\\])(?:boxed|fbox|oxed))\s*\{"
)
_ANSWER_MARKER = re.compile(r"(?i)(?:final\s+answer|answer|result)\s*(?:is\b|[:=])\s*")
_NUMBER = re.compile(
    r"[-+]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
    r"(?:[eE][-+]?\d+)?\s*%?"
)
_DIGIT_RUN = re.compile(r"\d+")
_COMMAND = re.compile(r"\\[A-Za-z]+")
_WORD = re.compile(r"[A-Za-z]{2,}")
_CODE_SHAPED = re.compile(
    r"__|"
    r"\b(?:breakpoint|compile|eval|exec|getattr|globals|import|locals|open|"
    r"setattr)\s*\(|"
    r"\b(?:builtins|os|pathlib|subprocess|sys)\s*\."
)
_EAGER_PARSER_OPERATION = re.compile(
    r"\\begin\{[vV]matrix\}|"
    r"\\(?:det|gcd|lcm)\b|"
    r"\\xrightarrow|"
    r"\\operatorname\s*\{\s*(?:"
    r"cols|diag|diagonalize|eig|eigen|eigenvals|eigenvalues|eigenvects|"
    r"eigenvectors|eye|gcd|hstack|lcm|nullspace|norm|ones|orth|ortho|"
    r"orthogonal|orthogonalize|rank|ref|rows|rref|svd|trace|tr|vstack|"
    r"zeros"
    r")\s*\}"
)

_PLAIN_FUNCTIONS = {
    "abs",
    "acos",
    "acosh",
    "asin",
    "asinh",
    "atan",
    "atanh",
    "binomial",
    "ceil",
    "cos",
    "cosh",
    "exp",
    "factorial",
    "floor",
    "ln",
    "log",
    "max",
    "min",
    "sin",
    "sinh",
    "sqrt",
    "tan",
    "tanh",
}

_ParseStatus = Literal[
    "correct",
    "incorrect",
    "answer_parse_error",
    "answer_limit",
]


class _MathParseError(ValueError):
    pass


class _MathLimitError(_MathParseError):
    pass


class _MathUnsafeError(_MathParseError):
    pass


@dataclass(frozen=True)
class _ParsedValue:
    expression: Any | None
    text: str | None
    source: str
    expensive: bool = False


@dataclass(frozen=True)
class _ExpressionInfo:
    expensive: bool


@dataclass(frozen=True)
class _WorkerScore:
    status: _ParseStatus
    answer: str | None
    reason: str | None = None


@dataclass
class _MathWorkerContext:
    queue: anyio.CapacityLimiter
    process_limiter: anyio.CapacityLimiter
    started: bool = False


_MATH_WORKER_CONTEXT: RunVar[_MathWorkerContext] = RunVar("math_worker_context")


def _math_worker_context() -> _MathWorkerContext:
    try:
        return _MATH_WORKER_CONTEXT.get()
    except LookupError:
        context = _MathWorkerContext(
            queue=anyio.CapacityLimiter(_MATH_WORKERS),
            process_limiter=anyio.CapacityLimiter(_MATH_WORKERS),
        )
        _MATH_WORKER_CONTEXT.set(context)
        return context


def _replace_unicode(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", text)
    replacements = {
        "\u23a7": r"\boxed{",
        "\u23ab": "}",
        "\n\u2502": r"\boxed{",
        "\u2502": "}",
        "\n\u2503": r"\boxed{",
        "\u2503": "}",
        "\n\uf8f0": r"\boxed{",
        "\uf8fb": "}",
        "\u221a": r"\sqrt",
        "\u00d7": r"\cdot",
        "\u00f7": "/",
        "\u202f": " ",
        "\u2212": "-",
        "\u2013": "-",
        "\u03c0": r"\pi",
        "\u00b0": r"^\circ",
        "\u221e": r"\infty",
        "\u2264": r"\le",
        "\u2265": r"\ge",
        "\u2260": r"\ne",
        "\u222a": r"\cup",
        "\u2229": r"\cap",
    }
    for source, replacement in replacements.items():
        text = text.replace(source, replacement)
    return text


def _balanced_content(text: str, opening: int) -> tuple[str, int] | None:
    depth = 0
    for index in range(opening, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
            if depth > _MAX_NESTING:
                return None
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = min(index, opening + _MAX_CANDIDATE_CHARS + 2)
                return text[opening + 1 : end], index + 1
    return None


def _boxed_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    position = 0
    while len(candidates) < _MAX_COMMANDS:
        match = _BOX_START.search(text, position)
        if match is None:
            break
        parsed = _balanced_content(text, match.end() - 1)
        if parsed is None:
            position = match.end()
            continue
        content, position = parsed
        candidates.append(content)
    return candidates


def _last_single_dollar_math(text: str) -> str | None:
    positions: list[int] = []
    for index, char in enumerate(text):
        if char == "$" and (index == 0 or text[index - 1] != "\\"):
            if index + 1 < len(text) and text[index + 1] == "$":
                continue
            if index > 0 and text[index - 1] == "$":
                continue
            positions.append(index)
    last_match: str | None = None
    for index in range(0, len(positions) - 1, 2):
        last_match = text[positions[index] + 1 : positions[index + 1]]
    return last_match


def _last_delimited_math(text: str) -> str | None:
    matches: list[tuple[int, str]] = []
    for opening, closing in (("$$", "$$"), (r"\[", r"\]"), (r"\(", r"\)")):
        end = text.rfind(closing)
        if end < 0:
            continue
        start = text.rfind(opening, 0, end)
        if start >= 0:
            matches.append((end, text[start + len(opening) : end]))

    single_dollar = _last_single_dollar_math(text)
    if single_dollar is not None:
        end = text.rfind("$")
        matches.append((end, single_dollar))

    if not matches:
        return None
    return max(matches, key=lambda item: item[0])[1]


def _strip_delimiters(text: str) -> str:
    text = text.strip()
    while len(text) >= 4 and text.startswith("**") and text.endswith("**"):
        text = text[2:-2].strip()
    for opening, closing in (
        ("$$", "$$"),
        (r"\[", r"\]"),
        (r"\(", r"\)"),
        ("$", "$"),
    ):
        if (
            text.startswith(opening)
            and text.endswith(closing)
            and (opening != "$" or text.count("$") == 2)
        ):
            text = text[len(opening) : -len(closing)].strip()
    text = re.sub(r"^(?:(?:\\[,;:!]|\\quad|\\qquad)\s*)+", "", text)
    text = re.sub(r"(?:(?:\\[,;:!]|\\quad|\\qquad)\s*)+$", "", text)
    return text.rstrip(" \t\r\n.,;:")


def _append_candidate(candidates: list[str], candidate: str | None) -> None:
    if candidate is None:
        return
    candidate = _strip_delimiters(candidate)
    if candidate and candidate not in candidates:
        candidates.append(candidate)


def _answer_candidates(text: str) -> list[str]:
    text = _replace_unicode(text)
    if len(text) > _MAX_COMPLETION_CHARS:
        raise _MathLimitError("model output is too long")

    candidates: list[str] = []
    boxes = _boxed_candidates(text)
    if boxes:
        _append_candidate(candidates, boxes[-1])

    last_marker: re.Match[str] | None = None
    for match in _ANSWER_MARKER.finditer(text):
        last_marker = match
    if last_marker is not None:
        suffix = text[last_marker.end() :]
        _append_candidate(candidates, suffix.splitlines()[0] if suffix else None)

    if _is_short_composite_answer(text):
        _append_candidate(candidates, text)

    _append_candidate(candidates, _last_delimited_math(text))

    if len(text) <= _MAX_CANDIDATE_CHARS and not _is_short_composite_answer(text):
        _append_candidate(candidates, text)

    nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if nonempty_lines:
        _append_candidate(candidates, nonempty_lines[-1])

    last_number: str | None = None
    for match in _NUMBER.finditer(text):
        last_number = match.group(0)
    _append_candidate(candidates, last_number)

    return candidates


def _target_candidates(text: str) -> list[str]:
    text = _replace_unicode(text)
    candidates: list[str] = []
    boxes = _boxed_candidates(text)
    if boxes:
        _append_candidate(candidates, boxes[-1])
    _append_candidate(candidates, text)
    return candidates


def _contains_nested_latex_power(text: str) -> bool:
    index = 0
    while True:
        index = text.find("^", index)
        if index < 0:
            return False
        cursor = index + 1
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor < len(text) and text[cursor] == "{":
            parsed = _balanced_content(text, cursor)
            if (
                parsed is not None
                and "^" in parsed[0]
                and not re.search(r"[A-Za-z]", parsed[0])
            ):
                return True
        index += 1


def _validate_candidate(candidate: str) -> None:
    if not candidate:
        raise _MathParseError("answer is empty")
    if len(candidate) > _MAX_CANDIDATE_CHARS:
        raise _MathLimitError("expression is too long")
    if _CODE_SHAPED.search(candidate):
        raise _MathUnsafeError("expression contains non-mathematical code syntax")
    if _EAGER_PARSER_OPERATION.search(candidate):
        raise _MathLimitError("expression requests an eager mathematical operation")
    if _contains_nested_latex_power(candidate):
        raise _MathLimitError("expression contains a nested exponent")

    digit_runs = _DIGIT_RUN.findall(candidate)
    if any(len(run) > _MAX_DIGIT_RUN for run in digit_runs):
        raise _MathLimitError("expression contains an oversized numeric literal")
    if sum(len(run) for run in digit_runs) > _MAX_TOTAL_DIGITS:
        raise _MathLimitError("expression contains too many digits")
    if len(_COMMAND.findall(candidate)) > _MAX_COMMANDS:
        raise _MathLimitError("expression contains too many LaTeX commands")
    if sum(candidate.count(operator) for operator in "+-*/^=!<>") > _MAX_OPERATORS:
        raise _MathLimitError("expression contains too many operators")

    depth = 0
    max_depth = 0
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    for char in candidate:
        if char in "([{":
            stack.append(char)
            depth += 1
            max_depth = max(max_depth, depth)
        elif char in ")]}":
            if stack and stack[-1] == pairs[char]:
                stack.pop()
                depth -= 1
    if max_depth > _MAX_NESTING:
        raise _MathLimitError("expression is nested too deeply")

    matrix_rows = candidate.count(r"\\") + 1
    matrix_columns = candidate.count("&") + 1
    if matrix_rows * matrix_columns > _MAX_MATRIX_CELLS:
        raise _MathLimitError("expression contains an oversized matrix")


def _looks_like_prose(candidate: str) -> bool:
    if "\\" in candidate or any(char in candidate for char in "=+-*/^<>[]{}()"):
        return False
    return len(_WORD.findall(candidate)) >= 2


def _is_short_composite_answer(candidate: str) -> bool:
    if len(candidate) > 512 or candidate.count("\n") > 2:
        return False
    if "$" not in candidate and r"\(" not in candidate and r"\[" not in candidate:
        return False
    if "\n" in candidate and candidate.count("$") >= 4:
        return True
    outside_math = re.sub(
        r"\$\$.*?\$\$|\$.*?\$|\\\(.*?\\\)|\\\[.*?\\\]", " ", candidate, flags=re.DOTALL
    )
    return bool(_WORD.search(outside_math))


def _normalize_text(candidate: str) -> str:
    candidate = _strip_delimiters(candidate)
    candidate = re.sub(r"\\(?:text|mathrm|mbox)\s*\{([^{}]*)\}", r"\1", candidate)
    candidate = candidate.replace(r"\ ", " ")
    candidate = re.sub(r"\s+", " ", candidate)
    return candidate.strip(" \t\r\n.,;:").casefold()


def _split_plain_equation(text: str) -> tuple[str, str] | None:
    depth = 0
    split_at: int | None = None
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "=" and depth == 0:
            previous = text[index - 1] if index else ""
            following = text[index + 1] if index + 1 < len(text) else ""
            if previous in "<>!=" or following == "=":
                continue
            if split_at is not None:
                return None
            split_at = index
    if split_at is None:
        return None
    return text[:split_at], text[split_at + 1 :]


class _PlainExpressionBuilder(ast.NodeVisitor):
    def __init__(self, sympy: Any) -> None:
        self.sympy = sympy
        self.nodes = 0

    def visit(self, node: ast.AST) -> Any:
        self.nodes += 1
        if self.nodes > _MAX_EXPRESSION_NODES:
            raise _MathLimitError("plain expression contains too many nodes")
        return super().visit(node)

    def generic_visit(self, node: ast.AST) -> Any:
        raise _MathParseError(
            f"unsupported plain expression syntax: {type(node).__name__}"
        )

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        value = node.value
        if isinstance(value, bool) or value is None or isinstance(value, str):
            raise _MathParseError("unsupported literal")
        if isinstance(value, int):
            if value.bit_length() > _MAX_INTEGER_BITS:
                raise _MathLimitError("integer literal is too large")
            return self.sympy.Integer(value)
        if isinstance(value, float):
            if not stdlib_math.isfinite(value):
                raise _MathLimitError("non-finite numeric literal")
            return self.sympy.Float(repr(value))
        if isinstance(value, complex):
            if not (
                stdlib_math.isfinite(value.real) and stdlib_math.isfinite(value.imag)
            ):
                raise _MathLimitError("non-finite complex literal")
            return self.sympy.Add(
                self.sympy.Float(repr(value.real)),
                self.sympy.Mul(
                    self.sympy.Float(repr(value.imag)),
                    self.sympy.I,
                    evaluate=False,
                ),
                evaluate=False,
            )
        raise _MathParseError("unsupported literal")

    def visit_Name(self, node: ast.Name) -> Any:
        constants = {
            "E": self.sympy.E,
            "I": self.sympy.I,
            "e": self.sympy.E,
            "i": self.sympy.I,
            "inf": self.sympy.oo,
            "infinity": self.sympy.oo,
            "pi": self.sympy.pi,
        }
        return constants.get(node.id, self.sympy.Symbol(node.id))

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.UAdd):
            return operand
        if isinstance(node.op, ast.USub):
            return self.sympy.Mul(-1, operand, evaluate=False)
        raise _MathParseError("unsupported unary operator")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, ast.Add):
            return self.sympy.Add(left, right, evaluate=False)
        if isinstance(node.op, ast.Sub):
            return self.sympy.Add(
                left, self.sympy.Mul(-1, right, evaluate=False), evaluate=False
            )
        if isinstance(node.op, ast.Mult):
            return self.sympy.Mul(left, right, evaluate=False)
        if isinstance(node.op, ast.Div):
            return self.sympy.Mul(
                left, self.sympy.Pow(right, -1, evaluate=False), evaluate=False
            )
        if isinstance(node.op, ast.Pow):
            return self.sympy.Pow(left, right, evaluate=False)
        if isinstance(node.op, ast.Mod):
            return self.sympy.Mod(left, right, evaluate=False)
        raise _MathParseError("unsupported binary operator")

    def visit_Call(self, node: ast.Call) -> Any:
        if (
            not isinstance(node.func, ast.Name)
            or node.func.id not in _PLAIN_FUNCTIONS
            or node.keywords
        ):
            raise _MathParseError("unsupported function call")
        args = [self.visit(arg) for arg in node.args]
        name = node.func.id
        if name == "sqrt" and len(args) == 1:
            return self.sympy.Pow(args[0], self.sympy.S.Half, evaluate=False)
        if name == "factorial" and len(args) == 1:
            return self.sympy.factorial(args[0], evaluate=False)
        if name == "binomial" and len(args) == 2:
            return self.sympy.binomial(*args, evaluate=False)
        if name == "abs" and len(args) == 1:
            return self.sympy.Abs(args[0], evaluate=False)
        if name in {"ceil", "floor"} and len(args) == 1:
            function = self.sympy.ceiling if name == "ceil" else self.sympy.floor
            return function(args[0], evaluate=False)
        if name in {"log", "ln"} and 1 <= len(args) <= 2:
            base = args[1] if len(args) == 2 else self.sympy.E
            return self.sympy.log(args[0], base, evaluate=False)
        if name in {"min", "max"} and args:
            function = self.sympy.Min if name == "min" else self.sympy.Max
            return function(*args, evaluate=False)
        functions = {
            "acos": self.sympy.acos,
            "acosh": self.sympy.acosh,
            "asin": self.sympy.asin,
            "asinh": self.sympy.asinh,
            "atan": self.sympy.atan,
            "atanh": self.sympy.atanh,
            "cos": self.sympy.cos,
            "cosh": self.sympy.cosh,
            "exp": self.sympy.exp,
            "sin": self.sympy.sin,
            "sinh": self.sympy.sinh,
            "tan": self.sympy.tan,
            "tanh": self.sympy.tanh,
        }
        function = functions.get(name)
        if function is None or len(args) != 1:
            raise _MathParseError("unsupported function arguments")
        return function(args[0], evaluate=False)

    def visit_Tuple(self, node: ast.Tuple) -> Any:
        return self.sympy.Tuple(*(self.visit(element) for element in node.elts))

    def visit_List(self, node: ast.List) -> Any:
        return self.sympy.Tuple(*(self.visit(element) for element in node.elts))

    def visit_Set(self, node: ast.Set) -> Any:
        return self.sympy.FiniteSet(
            *(self.visit(element) for element in node.elts), evaluate=False
        )

    def visit_Compare(self, node: ast.Compare) -> Any:
        values = [
            self.visit(node.left),
            *(self.visit(item) for item in node.comparators),
        ]
        relations: list[Any] = []
        for left, operator, right in zip(
            values[:-1], node.ops, values[1:], strict=True
        ):
            if isinstance(operator, ast.Eq):
                relation = self.sympy.Eq(left, right, evaluate=False)
            elif isinstance(operator, ast.NotEq):
                relation = self.sympy.Ne(left, right, evaluate=False)
            elif isinstance(operator, ast.Lt):
                relation = self.sympy.StrictLessThan(left, right, evaluate=False)
            elif isinstance(operator, ast.LtE):
                relation = self.sympy.LessThan(left, right, evaluate=False)
            elif isinstance(operator, ast.Gt):
                relation = self.sympy.StrictGreaterThan(left, right, evaluate=False)
            elif isinstance(operator, ast.GtE):
                relation = self.sympy.GreaterThan(left, right, evaluate=False)
            else:
                raise _MathParseError("unsupported comparison")
            relations.append(relation)
        if len(relations) == 1:
            return relations[0]
        return self.sympy.And(*relations, evaluate=False)


def _parse_plain_expression(candidate: str, sympy: Any) -> Any | None:
    if "\\" in candidate or re.search(r"\^\s*\{", candidate):
        return None
    text = candidate.strip()
    if text.endswith("%"):
        text = f"({text[:-1]}) / 100"
    text = text.replace("\u00d7", "*").replace("\u00f7", "/").replace("^", "**")

    equation = _split_plain_equation(text)
    if equation is not None:
        left_text, right_text = equation
        left = _parse_plain_expression(left_text, sympy)
        right = _parse_plain_expression(right_text, sympy)
        if left is None or right is None:
            raise _MathParseError("invalid equation")
        return sympy.Eq(left, right, evaluate=False)

    try:
        parsed = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError):
        return None
    return _PlainExpressionBuilder(sympy).visit(parsed)


def _looks_complex(candidate: str) -> bool:
    return bool(
        re.search(
            r"\\mathbb\{C\}|\\(?:i|imath)\b|(?<![A-Za-z])i(?![A-Za-z])|"
            r"\\(?:arg|Re|Im)\b",
            candidate,
        )
    )


def _parse_latex_expression(candidate: str) -> Any:
    from latex2sympy2_extended import (  # type: ignore[import-untyped]
        NormalizationConfig,
        latex2sympy,
    )
    from latex2sympy2_extended.latex2sympy2 import (  # type: ignore[import-untyped]
        ConversionConfig,
    )

    normalized_candidate = re.sub(
        r"\\(?:left|right|Bigl|Bigr|bigl|bigr|Big|big|Large|large)\b",
        "",
        candidate,
    )
    return latex2sympy(
        normalized_candidate,
        variable_values=None,
        is_real=not _looks_complex(candidate),
        convert_degrees=False,
        normalization_config=NormalizationConfig(
            basic_latex=True,
            units=True,
            malformed_operators=True,
            nits=True,
            boxed="last",
            equations=False,
        ),
        conversion_config=ConversionConfig(
            interpret_as_mixed_fractions=True,
            interpret_simple_eq_as_assignment=False,
            interpret_contains_as_eq=True,
            lowercase_symbols=True,
        ),
    )


def _integer_too_large(value: Any) -> bool:
    try:
        return abs(int(value)).bit_length() > _MAX_INTEGER_BITS
    except (TypeError, ValueError, OverflowError):
        return True


def _validate_expression(expression: Any, sympy: Any) -> _ExpressionInfo:
    if isinstance(expression, sympy.MatrixBase):
        rows, columns = expression.shape
        if rows * columns > _MAX_MATRIX_CELLS:
            raise _MathLimitError("parsed matrix is too large")
        roots = list(expression)
    elif isinstance(expression, sympy.Basic):
        roots = [expression]
    else:
        raise _MathParseError("parser returned an unsupported value")

    nodes = 0
    symbols: set[str] = set()
    expensive = False
    stack = [(root, 1) for root in roots]
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_EXPRESSION_NODES:
            raise _MathLimitError("parsed expression contains too many nodes")
        if depth > _MAX_EXPRESSION_DEPTH:
            raise _MathLimitError("parsed expression is nested too deeply")

        if isinstance(node, sympy.Integer) and _integer_too_large(node):
            raise _MathLimitError("parsed integer is too large")
        if isinstance(node, sympy.Rational) and (
            _integer_too_large(node.p) or _integer_too_large(node.q)
        ):
            raise _MathLimitError("parsed rational is too large")
        if isinstance(node, sympy.Symbol):
            symbols.add(node.name)
            if len(node.name) > _MAX_SYMBOL_CHARS:
                raise _MathLimitError("parsed symbol is too long")
            if len(symbols) > _MAX_SYMBOLS:
                raise _MathLimitError("parsed expression contains too many symbols")

        if isinstance(node, sympy.Pow):
            exponent = node.exp
            if isinstance(exponent, sympy.Integer):
                try:
                    if abs(int(exponent)) > _SYMBOLIC_POWER_EXPONENT_LIMIT:
                        expensive = True
                except (TypeError, ValueError, OverflowError):
                    expensive = True
            elif isinstance(exponent, sympy.Pow):
                expensive = True

        function_name = getattr(getattr(node, "func", None), "__name__", "")
        if function_name == "factorial" and node.args:
            argument = node.args[0]
            if isinstance(argument, sympy.Integer):
                try:
                    value = abs(int(argument))
                except (TypeError, ValueError, OverflowError):
                    value = _MAX_FACTORIAL_ARGUMENT + 1
                if value > _MAX_FACTORIAL_ARGUMENT:
                    raise _MathLimitError("factorial argument is too large")
                if value > 100:
                    expensive = True
        if function_name in {
            "Derivative",
            "Integral",
            "Limit",
            "Product",
            "Sum",
        }:
            expensive = True

        args = getattr(node, "args", ())
        if len(args) > _MAX_EXPRESSION_ARGS:
            raise _MathLimitError("parsed expression has too many arguments")
        stack.extend((arg, depth + 1) for arg in args if isinstance(arg, sympy.Basic))

    return _ExpressionInfo(expensive=expensive)


def _parse_candidate(candidate: str) -> _ParsedValue:
    import sympy  # type: ignore[import-untyped]

    candidate = _strip_delimiters(candidate)
    _validate_candidate(candidate)
    if _looks_like_prose(candidate) or _is_short_composite_answer(candidate):
        return _ParsedValue(None, _normalize_text(candidate), candidate)

    expression: Any | None = None
    try:
        expression = _parse_plain_expression(candidate, sympy)
    except _MathLimitError:
        raise
    except Exception:
        expression = None

    if expression is None:
        try:
            expression = _parse_latex_expression(candidate)
        except Exception:
            expression = None

    if expression is not None:
        try:
            info = _validate_expression(expression, sympy)
        except _MathParseError:
            raise
        except Exception as ex:
            raise _MathParseError("could not validate mathematical answer") from ex
        return _ParsedValue(expression, None, candidate, info.expensive)

    equation = _split_plain_equation(candidate)
    if equation is not None:
        _, right = equation
        try:
            return _parse_candidate(right)
        except _MathParseError:
            pass

    normalized_text = _normalize_text(candidate)
    if normalized_text and _WORD.search(normalized_text):
        return _ParsedValue(None, normalized_text, candidate)
    raise _MathParseError("could not parse mathematical answer")


def _parse_first(candidates: list[str]) -> _ParsedValue:
    parse_error: _MathParseError | None = None
    for candidate in candidates:
        try:
            return _parse_candidate(candidate)
        except (_MathLimitError, _MathUnsafeError):
            raise
        except _MathParseError as ex:
            parse_error = ex
    raise parse_error or _MathParseError("could not extract mathematical answer")


def _is_numeric_expression(expression: Any, sympy: Any) -> bool:
    return isinstance(expression, sympy.Basic) and not expression.free_symbols


def _numeric_equivalent(left: Any, right: Any, sympy: Any) -> bool:
    if not (
        _is_numeric_expression(left, sympy) and _is_numeric_expression(right, sympy)
    ):
        return False
    try:
        left_value = complex(sympy.N(left, 30))
        right_value = complex(sympy.N(right, 30))
        if not all(
            stdlib_math.isfinite(value)
            for value in (
                left_value.real,
                left_value.imag,
                right_value.real,
                right_value.imag,
            )
        ):
            return False
        error = abs(left_value - right_value)
        scale = max(abs(left_value), abs(right_value), 1e-10)
        return error < 1e-10 or error / scale < 1e-10
    except (ArithmeticError, TypeError, ValueError):
        return False


def _expression_equivalent(left: _ParsedValue, right: _ParsedValue, sympy: Any) -> bool:
    if left.text is not None or right.text is not None:
        return (
            left.text is not None and right.text is not None and left.text == right.text
        )

    left_expression = left.expression
    right_expression = right.expression
    if left_expression is None or right_expression is None:
        return False

    if isinstance(right_expression, sympy.Equality) and not bool(
        getattr(left_expression, "is_Relational", False)
    ):
        right = _ParsedValue(
            right_expression.rhs,
            None,
            right.source,
            right.expensive,
        )
        right_expression = right.expression

    try:
        if left_expression == right_expression:
            return True
    except Exception:
        pass

    if left.expensive or right.expensive:
        return False

    if isinstance(left_expression, sympy.MatrixBase) or isinstance(
        right_expression, sympy.MatrixBase
    ):
        if not (
            isinstance(left_expression, sympy.MatrixBase)
            and isinstance(right_expression, sympy.MatrixBase)
            and left_expression.shape == right_expression.shape
        ):
            return False
        return all(
            _expression_equivalent(
                _ParsedValue(left_item, None, left.source),
                _ParsedValue(right_item, None, right.source),
                sympy,
            )
            for left_item, right_item in zip(
                left_expression, right_expression, strict=True
            )
        )

    try:
        equals = left_expression.equals(right_expression)
        if equals is True:
            return True
    except Exception:
        pass

    return _numeric_equivalent(left_expression, right_expression, sympy)


def _parse_targets_worker(targets: tuple[str, ...]) -> str | None:
    from sympy.core.cache import clear_cache  # type: ignore[import-untyped]

    try:
        if not targets:
            return "target is empty"
        last_error: _MathParseError | None = None
        for target in targets:
            try:
                _parse_first(_target_candidates(target))
                return None
            except _MathParseError as ex:
                last_error = ex
        return str(last_error or "could not parse mathematical target")
    finally:
        clear_cache()


def _score_answer_worker(completion: str, targets: tuple[str, ...]) -> _WorkerScore:
    import sympy  # type: ignore[import-untyped]
    from sympy.core.cache import clear_cache  # type: ignore[import-untyped]

    try:
        try:
            answer = _parse_first(_answer_candidates(completion))
        except _MathLimitError as ex:
            return _WorkerScore("answer_limit", None, str(ex))
        except _MathParseError as ex:
            return _WorkerScore("answer_parse_error", None, str(ex))

        parsed_targets: list[_ParsedValue] = []
        for target_text in targets:
            try:
                parsed_targets.append(_parse_first(_target_candidates(target_text)))
            except _MathParseError:
                continue
        if not parsed_targets:
            raise RuntimeError("validated math target could not be reparsed")
        correct = any(
            _expression_equivalent(target_value, answer, sympy)
            for target_value in parsed_targets
        )
        return _WorkerScore(
            "correct" if correct else "incorrect",
            answer.source[:_MAX_CANDIDATE_CHARS],
        )
    finally:
        clear_cache()


def _dependency_error() -> Exception:
    return pip_dependency_error(
        "math() scorer", [f"{_PARSER_PACKAGE}=={_PARSER_VERSION}"]
    )


def _check_dependency() -> None:
    try:
        from importlib.metadata import version

        import latex2sympy2_extended  # noqa: F401
        import sympy  # noqa: F401
    except ImportError:
        raise _dependency_error() from None

    installed = version(_PARSER_PACKAGE)
    if installed != _PARSER_VERSION:
        raise PrerequisiteError(
            f"ERROR: math() scorer requires {_PARSER_PACKAGE}=={_PARSER_VERSION} "
            f"(you have {installed}).\n\n"
            f"Install with: pip install {_PARSER_PACKAGE}=={_PARSER_VERSION}"
        )


def _status_metadata(status: str) -> dict[str, str]:
    return {"math_scorer_status": status}


@scorer(metrics=[accuracy(), stderr()])
def math() -> Scorer:
    """Create a mathematical expression scorer.

    Extracts a bounded final answer from model output, parses it without
    evaluating Python, and compares it to each target under bounded symbolic
    work.
    """
    _check_dependency()

    async def score(state: TaskState, target: Target) -> Score:
        worker = _math_worker_context()
        targets = tuple(target)
        try:
            async with worker.queue:
                target_timeout = (
                    _TARGET_TIMEOUT_SECONDS
                    if worker.started
                    else _COLD_WORKER_TIMEOUT_SECONDS
                )
                with anyio.fail_after(target_timeout):
                    target_error = await run_sync(
                        _parse_targets_worker,
                        targets,
                        cancellable=True,
                        limiter=worker.process_limiter,
                    )
            worker.started = True
        except TimeoutError:
            worker.started = False
            return Score.unscored(
                explanation="Mathematical target exceeded the parsing time limit.",
                metadata=_status_metadata("target_timeout"),
            )

        if target_error is not None:
            return Score.unscored(
                explanation=f"Could not parse mathematical target: {target_error}.",
                metadata=_status_metadata("target_parse_error"),
            )

        try:
            async with worker.queue:
                with anyio.fail_after(_ANSWER_TIMEOUT_SECONDS):
                    result = await run_sync(
                        _score_answer_worker,
                        state.output.completion,
                        targets,
                        cancellable=True,
                        limiter=worker.process_limiter,
                    )
        except TimeoutError:
            worker.started = False
            return Score(
                value=INCORRECT,
                explanation="Mathematical answer exceeded the scoring time limit.",
                metadata=_status_metadata("answer_timeout"),
            )

        if result.status == "correct":
            return Score(
                value=CORRECT,
                answer=result.answer,
                explanation=state.output.completion,
                metadata=_status_metadata(result.status),
            )
        if result.status == "incorrect":
            return Score(
                value=INCORRECT,
                answer=result.answer,
                explanation=state.output.completion,
                metadata=_status_metadata(result.status),
            )
        return Score(
            value=INCORRECT,
            answer=result.answer,
            explanation=(
                f"Could not parse mathematical answer: {result.reason}."
                if result.status == "answer_parse_error"
                else f"Mathematical answer exceeded a complexity limit: {result.reason}."
            ),
            metadata=_status_metadata(result.status),
        )

    return score
