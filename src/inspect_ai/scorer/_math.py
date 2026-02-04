"""Mathematical expression scorer using Math-Verify library."""

from typing import TYPE_CHECKING, Any

import regex
import sympy
from sympy import N
from sympy.parsing.latex import parse_latex
from sympy.parsing.sympy_parser import (
    implicit_application,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from inspect_ai.solver._task_state import TaskState

from ._metric import CORRECT, INCORRECT, Score
from ._metrics import accuracy, stderr
from ._scorer import Scorer, scorer
from ._target import Target

if TYPE_CHECKING:
    pass


# ============================================================================
# STAGE 1: PREPROCESSING
# ============================================================================


def replace_unicode(text: str) -> str:
    """Replace unicode mathematical characters with LaTeX equivalents.

    Args:
        text: Raw text that may contain unicode math characters.

    Returns:
        Text with unicode characters replaced by LaTeX commands.
    """
    # Remove non-printable control characters (ASCII 0-31 except whitespace, and DEL)
    # This removes characters like backspace (\x08) that can corrupt pattern matching
    # Keep: \t (tab), \n (newline), \r (carriage return)
    text = regex.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", text)

    # Replace unicode box-drawing characters with \boxed{}
    text = text.replace("\u23a7", r"\boxed{")
    text = text.replace("\u23ab", r"}")
    text = text.replace("\n\u2502", r"\boxed{")
    text = text.replace("\u2502", r"}")
    text = text.replace("\n\u2503", r"\boxed{")
    text = text.replace("\u2503", r"}")
    text = text.replace("\n\uf8f0", r"\boxed{")
    text = text.replace("\uf8fb", r"}")

    # Replace mathematical unicode characters
    text = text.replace("\u221a", r"\sqrt")  # Square root symbol
    text = text.replace("\u00d7", r"\cdot")  # Multiplication sign
    text = text.replace("\u202f", r" ")  # Narrow no-break space
    text = text.replace("\u2212", "-")  # Minus sign
    text = text.replace("\u03c0", r"\pi")  # Pi symbol

    return text


# ============================================================================
# STAGE 2: EXTRACTION
# ============================================================================

# Regex patterns for extracting mathematical answers from text
# Pattern: (\\boxed|\\fbox)\s*\{((?:[^{}]|\{(?2)\})*)\}
# Explanation: Matches \boxed{...} or \fbox{...} with support for nested braces
#   - (\\boxed|\\fbox)  : Match either \boxed or \fbox command
#   - \s*               : Optional whitespace (including unicode spaces)
#   - \{                : Opening brace (escaped)
#   - (?:               : Non-capturing group for content
#     [^{}]             : Match any character except braces
#     |                 : OR
#     \{(?2)\}          : Recursively match nested braces ((?2) refers to group 2)
#   )*                  : Repeat zero or more times
#   - \}                : Closing brace (escaped)
_BOXED_CONTENT_PATTERN = r"(\\boxed|\\fbox)\s*\{((?:[^{}]|\{(?2)\})*)\}"

# Pattern: (boxed|fbox|oxed)\s*\{((?:[^{}]|\{(?2)\})*)\}
# Same as above but without backslash (for already-processed text)
# Note: \s* allows for spaces like "boxed {77}" or unicode spaces
# Note: Also matches "oxed" to handle cases where \b was interpreted as backspace
_BOXED_CONTENT_NO_BACKSLASH = r"(boxed|fbox|oxed)\s*\{((?:[^{}]|\{(?2)\})*)\}"

# Pattern: \b\d+\b
# Explanation: Match whole integers with word boundaries
#   - \b    : Word boundary (ensures we match complete numbers)
#   - \d+   : One or more digits
#   - \b    : Word boundary
_INTEGER_PATTERN = r"\b\d+\b"


def remove_inner_boxed(match: str) -> str:
    r"""Remove nested boxed expressions, keeping only outermost content.

    Args:
        match: Text containing potentially nested \boxed{} or \fbox{}.

    Returns:
        Content with inner boxed expressions removed.

    Examples:
        >>> remove_inner_boxed(r"\boxed{\frac{1}{2}}")
        "\\frac{1}{2}"
        >>> remove_inner_boxed(r"\boxed{\boxed{42}}")
        "42"
    """
    matches = list(regex.finditer(_BOXED_CONTENT_PATTERN, match))
    if not matches:
        return match
    for m in matches:
        match = match.replace(m.group(0), m.group(2))
    return match


def find_last_boxed_content(text: str) -> str | None:
    r"""Extract content from the last \boxed{} or \fbox{} in text.

    Args:
        text: Text potentially containing boxed expressions.

    Returns:
        Content of the last boxed expression, or None if not found.

    Examples:
        >>> find_last_boxed_content(r"The answer is \boxed{42}")
        "42"
        >>> find_last_boxed_content(r"\boxed{10} and \boxed{42}")
        "42"
        >>> find_last_boxed_content("No boxed content here")
        None
    """
    matches = list(regex.finditer(_BOXED_CONTENT_NO_BACKSLASH, text))

    if not matches:
        return None

    last_match = remove_inner_boxed(matches[-1].group(2))
    return last_match


def extract_last_integer(text: str) -> int | None:
    """Fallback: extract the last integer found in text.

    Args:
        text: Text to search for integers.

    Returns:
        The last integer found, or None if no integers exist.

    Examples:
        >>> extract_last_integer("The answer is 42")
        42
        >>> extract_last_integer("Results: 10, 20, 30")
        30
        >>> extract_last_integer("No numbers here")
        None
    """
    matches = list(regex.finditer(_INTEGER_PATTERN, text))
    if not matches:
        return None
    try:
        return int(matches[-1].group())
    except Exception as e:
        print(f"Error extracting last integer: {e}")
        return None


# ============================================================================
# STAGE 3: NORMALIZATION
# ============================================================================

# Regex patterns for normalizing LaTeX strings

# Pattern: \\{2,}\n?\(
# Explanation: Match multiple backslashes followed by optional newline and opening paren
#   - \\{2,}  : Two or more backslashes
#   - \n?     : Optional newline character
#   - \(      : Opening parenthesis
_LEADING_BACKSLASHES_PAREN = r"\\{2,}\n?\("

# Pattern: \\begin{align[^}]*}(.*?)\\end{align[^}]*}
# Explanation: Match align environment and capture its content
#   - \\begin{align[^}]*}  : Match \begin{align} or \begin{align*}
#   - (.*?)                : Capture content (non-greedy)
#   - \\end{align[^}]*}    : Match corresponding \end{align} or \end{align*}
_ALIGN_ENVIRONMENT = r"\\begin{align[^}]*}(.*?)\\end{align[^}]*}"

# Pattern: (?<=\d),(?=\d)
# Explanation: Match comma between digits (for removing thousands separators)
#   - (?<=\d)  : Positive lookbehind - preceded by a digit
#   - ,        : The comma to remove
#   - (?=\d)   : Positive lookahead - followed by a digit
#   Example: "1,234" → "1234"
_COMMA_BETWEEN_DIGITS = r"(?<=\d),(?=\d)"

# Pattern: \\sqrt\s*([^\s{}]*)
# Explanation: Match \sqrt followed by space and capture non-braced content
#   - \\sqrt   : The \sqrt command
#   - \s*      : Optional whitespace
#   - ([^\s{}]*) : Capture any non-whitespace, non-brace characters
#   Example: "\sqrt 2" → "\sqrt{2}"
_SQRT_WITHOUT_BRACES = r"\\sqrt\s*([^\s{}]*)"

# Pattern: \\text\{.*?\}
# Explanation: Match \text{...} environments and remove them
#   - \\text   : The \text command
#   - \{       : Opening brace
#   - .*?      : Any content (non-greedy)
#   - \}       : Closing brace
_TEXT_ENVIRONMENT = r"\\text\{.*?\}"

# Pattern: \\mathrm\{(.*?)\}
# Explanation: Match \mathrm{...} and capture content to unwrap it
#   - \\mathrm : The \mathrm command
#   - \{       : Opening brace
#   - (.*?)    : Capture content (non-greedy)
#   - \}       : Closing brace
_MATHRM_ENVIRONMENT = r"\\mathrm\{(.*?)\}"


def strip(s: str) -> str:
    r"""Strip whitespace and LaTeX newlines from string edges.

    Args:
        s: String to strip.

    Returns:
        Stripped string.

    Examples:
        >>> strip("  42  ")
        "42"
        >>> strip(r"\n42\n")
        "42"
        >>> strip(r"\\ 42")
        "42"
    """
    s = s.strip()
    # Remove LaTeX newlines from edges (careful: plain .strip() would remove "\" in "\begin")
    while s.startswith(r"\n"):
        s = s[2:]
    while s.endswith(r"\n"):
        s = s[:-2]
    # Remove LaTeX spacing from start
    while s.startswith("\\ "):
        s = s[2:]
    # Remove multiple backslashes followed by opening paren (e.g., "\\\\(x)")
    while regex.match(_LEADING_BACKSLASHES_PAREN, s):
        s = s[3:]
    return s


def normalize_string(s: str) -> str:
    r"""Normalize a LaTeX string for parsing.

    Removes sizing commands, alignment environments, converts brackets,
    and performs various LaTeX-to-parseable transformations.

    Args:
        s: The LaTeX string to normalize.

    Returns:
        The normalized string.

    Examples:
        >>> normalize_string(r"$\left[\frac{1}{2}\right]$")
        r"(\frac{1}{2})"
        >>> normalize_string("x = 42")
        "42"
        >>> normalize_string(r"\text{answer: }42")
        "42"
    """
    # Remove LaTeX sizing commands that don't affect mathematical meaning
    s = s.replace(r"\left", "").replace(r"\right", "")
    s = s.replace(r"\Bigl", "").replace(r"\Bigr", "")
    s = s.replace(r"\bigl", "").replace(r"\bigr", "")
    s = (
        s.replace(r"\Big", "")
        .replace(r"\big", "")
        .replace(r"\Large", "")
        .replace(r"\large", "")
    )

    # Remove align environments and their alignment markers (&) and line breaks (\\)
    s = regex.sub(
        _ALIGN_ENVIRONMENT,
        lambda m: m.group(1).replace("&", "").replace("\\\\", ""),
        s,
        flags=regex.DOTALL,
    )

    # Convert all bracket types to parentheses for uniform parsing
    s = s.replace("[", "(")
    s = s.replace("]", ")")
    s = s.replace("\\{", "(")  # LaTeX sets become lists
    s = s.replace("\\}", ")")

    # Remove mathematical delimiters and spacing commands
    s = s.replace("$", "")  # Remove inline math delimiters
    s = s.replace("\\ ", " ")  # LaTeX space to regular space
    s = s.replace(r"\hline", "")  # Remove table lines
    s = s.replace(r"\vline", "")
    s = s.replace(r"\quad", " ")  # Quad space to regular space

    # Normalize unicode characters to ASCII equivalents
    s = s.replace("−", "-")  # Unicode minus
    s = s.replace("–", "-")  # En dash
    s = s.replace("·", " \\cdot ")  # Middle dot to cdot

    # Remove degree symbols
    s = s.replace("^\\circ", " ")
    s = s.replace("^{\\circ}", " ")

    # Remove display style command
    s = s.replace("\\displaystyle", "")

    # Convert escaped parentheses to regular ones
    s = s.replace("\\(", "(")
    s = s.replace("\\)", ")")
    s = s.replace("{,}", "")  # Remove empty comma groups (o4-mini quirk)

    # Remove trailing period if present
    if s.endswith("."):
        s = s[:-1]

    # Remove thousands separators (1,234 → 1234)
    s = regex.sub(_COMMA_BETWEEN_DIGITS, "", s)
    s = s.replace("{,}", "")

    # Fix \sqrt without braces: "\sqrt 2" → "\sqrt{2}"
    if "\\sqrt " in s:
        s = regex.sub(_SQRT_WITHOUT_BRACES, r"\\sqrt{\1}", s)

    # Remove text annotations: "\text{answer: }42" → "42"
    s = regex.sub(_TEXT_ENVIRONMENT, "", s)

    # Unwrap \mathrm{...} to plain text
    s = regex.sub(_MATHRM_ENVIRONMENT, r" \1 ", s)

    # Dataset-specific: Replace Fibonacci F_30 with its value
    s = s.replace("F_{30}", "832040")

    # Extract value after equals sign (keep only the answer part)
    if "=" in s:
        s = s.split("=")[-1]

    # Handle approximate values: keep only the left side
    if "\\approx" in s:
        s = s.split("\\approx")[0]
        if s.endswith("("):  # Remove dangling opening paren
            s = s[:-1]

    return strip(s)


def remove_outer_brackets(s: str) -> str:
    """Remove matching outer parentheses if they wrap the entire expression.

    Args:
        s: String potentially wrapped in parentheses.

    Returns:
        String with outer parentheses removed if they matched.

    Examples:
        >>> remove_outer_brackets("(42)")
        "42"
        >>> remove_outer_brackets("((1+2))")
        "1+2"
        >>> remove_outer_brackets("(1)+(2)")
        "(1)+(2)"
    """
    while True:
        if not s:
            return s
        opening = s[0]
        closing = s[-1]

        if opening == "(" and closing == ")":
            count = 0
            matched = True
            for i, char in enumerate(s):
                if char == opening:
                    count += 1
                elif char == closing:
                    count -= 1
                if count == 0 and i != len(s) - 1:
                    matched = False
                    break

            if matched:
                s = s[1:-1]
                continue
        break

    return s


def remove_invalid_characters(text: str) -> str:
    r"""Remove LaTeX spacing commands that interfere with parsing.

    Args:
        text: Text containing LaTeX spacing commands.

    Returns:
        Text with spacing commands removed.

    Examples:
        >>> remove_invalid_characters(r"1\,234")
        "1234"
        >>> remove_invalid_characters(r"x\;=\;42")
        "x=42"
    """
    # Remove LaTeX spacing commands:
    # \; - thick space (5/18 em)
    # \: - medium space (4/18 em)
    # \, - thin space (3/18 em)
    # \! - negative thin space (-3/18 em)
    text = regex.sub(r"\\;", "", text)
    text = regex.sub(r"\\:", "", text)
    text = regex.sub(r"\\,", "", text)
    text = regex.sub(r"\\!", "", text)
    return text


# ============================================================================
# STAGE 4: PARSING
# ============================================================================

# Regex patterns for converting LaTeX mathematical expressions to Python syntax
# These patterns are applied iteratively to handle nested expressions

# Pattern: sqrt(\d+)
# Explanation: Match sqrt followed by digits without braces
#   - sqrt     : Literal "sqrt"
#   - (\d+)    : Capture one or more digits
#   Example: "sqrt2" → "sqrt{2}"
_SQRT_MISSING_BRACES = r"sqrt(\d+)"

# Pattern: frac(\d)
# Explanation: Match frac followed by single digit without braces
#   - frac     : Literal "frac"
#   - (\d)     : Capture single digit
#   Example: "frac1" → "frac{1}"
_FRAC_MISSING_BRACES = r"frac(\d)"

# Pattern: (\d+(\.\d+)?)\s*%
# Explanation: Match number followed by percent sign
#   - (\d+(\.\d+)?)  : Capture integer or decimal number
#   - \s*            : Optional whitespace
#   - %              : Percent sign
#   Example: "33.5%" → "(33.5/100)"
_PERCENTAGE = r"(\d+(\.\d+)?)\s*%"

# Pattern: \\*(?:dfrac|tfrac|frac)\{([^{}]*)\}\{([^{}]*)\}
# Explanation: Match LaTeX fraction commands
#   - \\*                : Optional backslash(es)
#   - (?:dfrac|tfrac|frac) : Match any fraction command
#   - \{([^{}]*)\}       : First braced group (numerator)
#   - \{([^{}]*)\}       : Second braced group (denominator)
#   Example: "\frac{1}{2}" → "(1)/(2)"
_LATEX_FRACTION = r"\\*(?:dfrac|tfrac|frac)\{([^{}]*)\}\{([^{}]*)\}"

# Pattern: \\*binom\{([^{}]*)\}\{([^{}]*)\}
# Explanation: Match LaTeX binomial coefficient
#   - \\*binom         : Binomial command
#   - \{([^{}]*)\}     : First argument (n)
#   - \{([^{}]*)\}     : Second argument (k)
#   Example: "\binom{5}{2}" → "binomial(5, 2)"
_LATEX_BINOM = r"\\*binom\{([^{}]*)\}\{([^{}]*)\}"

# Pattern: \\*sqrt\[(.*?)\]\{(.*?)\}
# Explanation: Match n-th root notation
#   - \\*sqrt          : Square root command
#   - \[(.*?)\]        : Optional bracket for root degree (n)
#   - \{(.*?)\}        : Braced content (radicand)
#   Example: "\sqrt[3]{8}" → "(8)**(1/(3))"
_LATEX_NTH_ROOT = r"\\*sqrt\[(.*?)\]\{(.*?)\}"

# Pattern: \\*sqrt\{(.*?)\}
# Explanation: Match square root
#   - \\*sqrt          : Square root command
#   - \{(.*?)\}        : Braced content
#   Example: "\sqrt{2}" → "(2)**(1/2)"
_LATEX_SQRT = r"\\*sqrt\{(.*?)\}"

# Pattern: \{(\d+)\}
# Explanation: Match braced digits to convert to parens
#   - \{       : Opening brace
#   - (\d+)    : One or more digits
#   - \}       : Closing brace
#   Example: "{42}" → "(42)"
_BRACED_DIGITS = r"\{(\d+)\}"

# Pattern: \bi\b
# Explanation: Match standalone 'i' (imaginary unit) with word boundaries
#   - \b       : Word boundary
#   - i        : The letter 'i'
#   - \b       : Word boundary
#   Example: "2 + 3i" → "2 + 3I" (for SymPy's imaginary unit)
_IMAGINARY_I = r"\bi\b"

# Patterns for implicit multiplication handling
# Pattern: (\d|(?<![a-zA-Z])[a-zA-Z]{1,2}(?![a-zA-Z]))\(
# Explanation: Number or variable followed by opening paren
#   - (\d|...)         : Digit OR...
#   - (?<![a-zA-Z])    : Not preceded by letter (negative lookbehind)
#   - [a-zA-Z]{1,2}    : One or two letters
#   - (?![a-zA-Z])     : Not followed by letter (negative lookahead)
#   - \(               : Opening paren
#   Example: "2(x+1)" → "2*(x+1)", "x(2)" → "x*(2)"
_IMPLICIT_MULT_BEFORE_PAREN = r"(\d|(?<![a-zA-Z])[a-zA-Z]{1,2}(?![a-zA-Z]))\("

# Pattern: \)(\d|(?<![a-zA-Z])[a-zA-Z]{1,2}(?![a-zA-Z]))
# Explanation: Closing paren followed by number or variable
#   Example: "(x+1)2" → "(x+1)*2"
_IMPLICIT_MULT_AFTER_PAREN = r"\)(\d|(?<![a-zA-Z])[a-zA-Z]{1,2}(?![a-zA-Z]))"

# Pattern: (?<=\d)((?<![a-zA-Z])[a-zA-Z]{1,2}(?![a-zA-Z]))
# Explanation: Variable after digit
#   Example: "2x" → "2*x", "3pi" → "3*pi"
_IMPLICIT_MULT_DIGIT_VAR = r"(?<=\d)((?<![a-zA-Z])[a-zA-Z]{1,2}(?![a-zA-Z]))"

# Pattern: ((?<![a-zA-Z])[a-zA-Z]{1,2}(?![a-zA-Z]))(?=\d)
# Explanation: Variable before digit
#   Example: "x2" → "x*2"
_IMPLICIT_MULT_VAR_DIGIT = r"((?<![a-zA-Z])[a-zA-Z]{1,2}(?![a-zA-Z]))(?=\d)"

# Pattern: \{([^{}]*)\}
# Explanation: Convert remaining braces to lists
#   - \{       : Opening brace
#   - ([^{}]*) : Capture content without nested braces
#   - \}       : Closing brace
#   Example: "{1, 2, 3}" → "[1, 2, 3]"
_BRACES_TO_LIST = r"\{([^{}]*)\}"


def _parse_integer(text: str) -> int | None:
    """Try to parse text as a simple integer.

    Args:
        text: Text to parse.

    Returns:
        Integer value if successful, None otherwise.
    """
    if text.isdigit():
        return int(text)
    return None


def _parse_float(text: str) -> int | float | None:
    """Try to parse text as a float (returns int if whole number).

    Args:
        text: Text to parse.

    Returns:
        Numeric value if successful, None otherwise.
    """
    try:
        float_text = float(text)
        if int(float_text) == float_text:
            return int(float_text)
        return float_text
    except ValueError:
        return None


def _preprocess_latex_for_sympify(text: str) -> str:
    """Apply iterative regex transformations to prepare LaTeX for sympify.

    Converts LaTeX commands (frac, sqrt, etc.) to Python-parseable format.

    Args:
        text: LaTeX text to preprocess.

    Returns:
        Preprocessed string ready for sympify.
    """
    # Fix missing braces and convert percentages
    if bool(regex.search(_SQRT_MISSING_BRACES, text)):
        text = regex.sub(_SQRT_MISSING_BRACES, r"sqrt{\1}", text)
    if bool(regex.search(_FRAC_MISSING_BRACES, text)):
        text = regex.sub(_FRAC_MISSING_BRACES, r"frac{\1}", text)
    if bool(regex.search(r"%", text)):
        text = regex.sub(_PERCENTAGE, r"(\1/100)", text)

    latex_str = text

    # First pass: convert LaTeX commands to Python operators
    # Run iteratively (max 5 times) to handle nested expressions
    for _ in range(5):
        init_str = latex_str

        # Convert fractions: \frac{1}{2} → (1)/(2)
        latex_str = regex.sub(_LATEX_FRACTION, r"(\1)/(\2)", latex_str)

        # Convert binomial coefficients: \binom{n}{k} → binomial(n, k)
        latex_str = regex.sub(_LATEX_BINOM, r"binomial(\1, \2)", latex_str)

        # Convert n-th roots: \sqrt[3]{8} → (8)**(1/(3))
        latex_str = regex.sub(_LATEX_NTH_ROOT, r"(\2)**(1/(\1))", latex_str)

        # Convert square roots: \sqrt{2} → (2)**(1/2)
        latex_str = regex.sub(_LATEX_SQRT, r"(\1)**(1/2)", latex_str)

        # Convert operators and constants
        latex_str = latex_str.replace("^", "**")  # Exponentiation
        latex_str = latex_str.replace("\\cdot", "*").replace("\\times", "*")
        latex_str = (
            latex_str.replace("\\pi", " pi ")  # Pi constant
            .replace("\\e", " E ")  # Euler's number
            .replace("\\i", " I ")  # Imaginary unit
        )
        latex_str = regex.sub(_IMAGINARY_I, "I", latex_str)  # Standalone 'i' → 'I'

        # Stop if no changes (convergence)
        if init_str == latex_str:
            break

    # Second pass: handle remaining braces and operators
    # This catches any nested expressions that emerged from the first pass
    for _ in range(5):
        init_str = latex_str

        # Convert braced digits to parens: {42} → (42)
        latex_str = regex.sub(_BRACED_DIGITS, r"(\1)", latex_str)

        # Repeat LaTeX command conversions for newly exposed nested content
        latex_str = regex.sub(_LATEX_FRACTION, r"(\1)/(\2)", latex_str)
        latex_str = regex.sub(_LATEX_BINOM, r"binomial(\1, \2)", latex_str)
        latex_str = regex.sub(_LATEX_NTH_ROOT, r"(\2)**(1/(\1))", latex_str)
        latex_str = regex.sub(_LATEX_SQRT, r"(\1)**(1/2)", latex_str)

        # Re-apply operator conversions
        latex_str = latex_str.replace("^", "**")
        latex_str = latex_str.replace("\\cdot", "*").replace("\\times", "*")
        latex_str = (
            latex_str.replace("\\pi", " pi ")
            .replace("\\e", " E ")
            .replace("\\i", " I ")
        )
        latex_str = regex.sub(_IMAGINARY_I, "I", latex_str)

        if init_str == latex_str:
            break

    # Add explicit multiplication where it's implicit in mathematical notation
    # Example: 2(x+1) → 2*(x+1), (x+1)2 → (x+1)*2, 2x → 2*x
    latex_str = regex.sub(_IMPLICIT_MULT_BEFORE_PAREN, r"\1*(", latex_str)
    latex_str = regex.sub(_IMPLICIT_MULT_AFTER_PAREN, r")*\1", latex_str)
    latex_str = regex.sub(_IMPLICIT_MULT_DIGIT_VAR, r"*\1", latex_str)
    latex_str = regex.sub(_IMPLICIT_MULT_VAR_DIGIT, r"\1*", latex_str)

    # Convert remaining braces to Python lists (for set notation)
    # Example: {1, 2, 3} → [1, 2, 3]
    latex_str = regex.sub(
        _BRACES_TO_LIST,
        lambda m: "[" + m.group(1).replace(",", ", ") + "]",
        latex_str,
    )

    return latex_str


def _sympify_latex(latex_str: str) -> Any:
    """Convert preprocessed LaTeX string to SymPy expression.

    Args:
        latex_str: Preprocessed LaTeX string.

    Returns:
        SymPy expression or None if conversion fails.
    """
    try:
        if latex_str == "None":
            return sympy.core.symbol.Symbol("None")
        else:
            transformations = standard_transformations + (
                implicit_multiplication_application,
                implicit_application,
            )
            latex_str = parse_expr(latex_str, transformations=transformations)
            return sympy.sympify(
                latex_str,
                locals={  # type: ignore[arg-type]
                    "binomial": sympy.binomial,
                    "pi": sympy.pi,
                    "E": sympy.E,
                    "e": sympy.E,
                    "I": sympy.I,
                },
            )
    except Exception as e:
        print(f"Couldn't parse {latex_str} with sympify: {e}")
        return None


def latex2sympy_fixed(latex: str) -> Any:
    """Fallback parser using SymPy's native LaTeX parser.

    Args:
        latex: LaTeX string to parse.

    Returns:
        SymPy expression with constants replaced.
    """
    # Fix subscripts: _123 → _{123}
    # Pattern: _([0-9]+)
    # Explanation: Match underscore followed by digits without braces
    #   - _         : Underscore (subscript in LaTeX)
    #   - ([0-9]+)  : One or more digits
    #   Example: "x_123" → "x_{123}"
    latex = regex.sub(r"_([0-9]+)", r"_{\1}", latex)
    latex_parsed = parse_latex(latex)
    # replace constants like pi and e with their numerical value
    known_constants: dict[str, Any] = {"pi": sympy.pi, "e": sympy.E, "I": 1j, "i": 1j}

    # Replace any symbol in expr that is in our known_constants dictionary.
    if latex_parsed is not None:
        expr = latex_parsed.xreplace(
            {
                s: known_constants[s.name]
                for s in latex_parsed.free_symbols
                if s.name in known_constants
            }
        )
        return expr
    return latex_parsed


def parse_primitives(text: str) -> Any:
    """Parse mathematical text into SymPy expression.

    Pipeline:
    1. Try integer parsing
    2. Try float parsing
    3. Try sympify with LaTeX preprocessing (primary method)
    4. Fall back to latex2sympy_fixed() (backup method)

    Args:
        text: Mathematical text to parse.

    Returns:
        Parsed expression (int, float, complex, or SymPy object) or None.
    """
    # Step 1: Try simple integer parsing
    int_result = _parse_integer(text)
    if int_result is not None:
        return int_result

    # Step 2: Try float parsing
    float_result = _parse_float(text)
    if float_result is not None:
        return float_result

    # Step 3: Try sympify with LaTeX preprocessing (primary method)
    latex_str = _preprocess_latex_for_sympify(text)
    sympy_result = _sympify_latex(latex_str)
    if sympy_result is not None:
        return sympy_result

    # Step 4: Fall back to latex2sympy_fixed (backup method)
    text_no_eq = text
    try:
        if "=" in text_no_eq:
            # rfind is used to remove the last occurence of "="
            text_no_eq = text_no_eq[text_no_eq.rfind("=") + 1 :]
        output_val = latex2sympy_fixed(text_no_eq)

        try:
            float_val = float(N(output_val, 101))
            if (
                float_val.is_integer()
                or float("inf") == float_val
                or float("-inf") == float_val
            ):
                return int(
                    N(latex2sympy_fixed(text_no_eq), 50001)
                )  # important for large ints
            return float_val
        except:  # noqa: E722
            try:
                complex_val = complex(N(output_val, 101))
                return complex_val
            except:  # noqa: E722
                return output_val
    except Exception as e:
        print(f"Error: Custom parsing error {e}, {text_no_eq}")
        return None


# ============================================================================
# STAGE 5: COMPARISON
# ============================================================================


def check_answers(ans1: Any, ans2: Any) -> bool:
    """Check if two parsed answers are mathematically equivalent.

    Uses SymPy's equals() method when available, otherwise uses
    approximate equality for numerical values.

    Args:
        ans1: First parsed answer.
        ans2: Second parsed answer.

    Returns:
        True if answers are equivalent, False otherwise.
    """

    def _both_have_equals(a: Any, b: Any) -> bool:
        return (
            hasattr(a, "equals")
            and callable(getattr(a, "equals"))
            and hasattr(b, "equals")
            and callable(getattr(b, "equals"))
        )

    def _approx_equal(ans1: Any, ans2: Any) -> bool:
        err = abs(N(ans1 - ans2))
        if err >= 1e-10:
            return False
        denom = max(abs(N(ans1)), abs(N(ans2)))
        if denom < 1e-10:
            return True
        return err / denom < 1e-10

    if ans1 is None or ans2 is None:
        return False
    if isinstance(ans1, list) != isinstance(ans2, list):
        return False
    if isinstance(ans1, list) and isinstance(ans2, list):
        return False

    try:
        if _both_have_equals(ans1, ans2):
            return bool(ans1.equals(ans2))  # type: ignore[union-attr]
        if isinstance(ans1, str) or isinstance(ans2, str):
            return ans1 == ans2
        return _approx_equal(ans1, ans2)
    except Exception:
        return False


# ============================================================================
# PUBLIC API
# ============================================================================


def parse_answer(text: str) -> Any:
    """Parse a mathematical answer string into a SymPy expression.

    Pipeline: Normalization → Parsing

    Args:
        text: Mathematical text to parse.

    Returns:
        Parsed expression or None.
    """
    text_normalized_1 = remove_invalid_characters(text)
    text_normalized_2 = remove_outer_brackets(normalize_string(text_normalized_1))
    answer = parse_primitives(text_normalized_2)
    return answer


def extract_answer(text: str) -> Any:
    """Extract and parse the final answer from model output.

    Pipeline: Preprocessing → Extraction → Normalization → Parsing

    Args:
        text: Raw model output text.

    Returns:
        Parsed answer or None.
    """
    text_normalized = replace_unicode(text)

    # Try to extract boxed content first
    answer = find_last_boxed_content(text_normalized)

    # If no boxed content, use the full text
    if answer is None:
        answer = text_normalized

    # Check for multiple equals signs (ambiguous)
    if answer.count("=") > 1:
        print(f"Warning: more than one '=' in answer {answer}")
        return None

    # Try to parse the extracted/normalized answer
    parsed_answer = parse_answer(answer)

    # If parsing succeeded, validate it's not nonsense
    if parsed_answer is not None:
        # Check if the result contains unexpected free symbols (variables)
        # Expected symbols: I (imaginary unit), pi, E (Euler's number)
        # If we have other symbols, it's likely garbage from parsing plain text
        if hasattr(parsed_answer, "free_symbols"):
            unexpected_symbols = {
                s.name
                for s in parsed_answer.free_symbols
                if s.name not in {"I", "pi", "E", "e"}
            }
            # If there are unexpected symbols, the parser interpreted
            # plain text as variables (e.g., "The answer is 42" → T*h*e*...)
            # In this case, reject the parse and fall back to integer extraction
            if not unexpected_symbols:
                return parsed_answer
        else:
            # No free symbols (it's a number), return it
            return parsed_answer

    # Fallback 1: Try to extract integer from the answer string
    integer_from_answer = extract_last_integer(answer)
    if integer_from_answer is not None:
        return integer_from_answer

    # Fallback 2: Try to extract integer from the full normalized text
    # (in case the answer extraction was too restrictive)
    return extract_last_integer(text_normalized)


@scorer(metrics=[accuracy(), stderr()])
def math() -> Scorer:
    """Create a mathematical expression scorer.

    Extracts answers from model output and compares them to target answers
    using mathematical equivalence checking.

    Returns:
        Scorer function for evaluating mathematical answers.
    """

    async def score(state: TaskState, target: Target) -> Score:
        result = extract_answer(state.output.completion)
        target_expr = parse_answer(target.text)

        if check_answers(result, target_expr):
            return Score(
                value=CORRECT,
                answer=str(result),
                explanation=state.output.completion,
            )

        return Score(
            value=INCORRECT,
            answer=str(result),
            explanation=state.output.completion,
        )

    return score
