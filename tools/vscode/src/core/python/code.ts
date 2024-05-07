


export function isValidPythonFnName(input: string) {
  if (!kFnCharsRegex.test(input)) {
    return false;
  }
  if (kReservedWords.includes(input)) {
    return false;
  }
  return true;
}
const kFnCharsRegex = /^[A-Za-z_][A-Za-z0-9_]*$/;
const kReservedWords = [
  "False",
  "None",
  "True",
  "and",
  "as",
  "assert",
  "async",
  "await",
  "break",
  "class",
  "continue",
  "def",
  "del",
  "elif",
  "else",
  "except",
  "finally",
  "for",
  "from",
  "global",
  "if",
  "import",
  "in",
  "is",
  "lambda",
  "nonlocal",
  "not",
  "or",
  "pass",
  "raise",
  "return",
  "try",
  "while",
  "with",
  "yield",
];


