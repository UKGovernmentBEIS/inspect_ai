import { StreamLanguage, StringStream } from "@codemirror/language";
import { tags } from "@lezer/highlight";
import { KEYWORDS, MATH_FUNCTIONS, SAMPLE_FUNCTIONS } from "./language";

// Types
export interface Token {
  type: string;
  text: string;
  from: number;
  to: number;
}

// Constants
const TOKEN_PATTERNS = {
  STRING: /^"[^"]*"/,
  UNTERMINATED_STRING: /^"[^"]*/,
  NUMBER: /^(-|\+)?\d+(\.\d+)?/,
  RELATION: /^(==|!=|<=|>=|<|>|~=)/,
  MISC_OPERATOR: /^(=|!|~)/,
  OPERATOR: /^(\+|-|\*|\/|\^|\(|\)|,|\.)/,
  VARIABLE: /^[a-zA-Z_][a-zA-Z0-9_]*/,
};

// Utilities
const createWordRegex = (words: string[]): RegExp =>
  new RegExp(`^(${words.join("|")})\\b`);

const countSpaces = (word: string): number => word.split(" ").length - 1;

// Regular expressions for functions and keywords
const mathFunctionsRegex = createWordRegex(
  MATH_FUNCTIONS.map(([label]) => label),
);
const sampleFunctionsRegex = createWordRegex(
  SAMPLE_FUNCTIONS.map(([label]) => label),
);
const keywordsRegex = createWordRegex(
  // Ensure 'not in' matches first
  KEYWORDS.sort((a, b) => countSpaces(b) - countSpaces(a)),
);

// Token recognition
function nextToken(stream: StringStream): string | null {
  // Check patterns in order of specificity
  if (stream.match(TOKEN_PATTERNS.STRING)) return "string";
  if (stream.match(TOKEN_PATTERNS.UNTERMINATED_STRING))
    return "unterminatedString";
  if (stream.match(TOKEN_PATTERNS.NUMBER)) return "number";
  if (stream.match(keywordsRegex)) return "keyword";
  if (stream.match(mathFunctionsRegex)) return "mathFunction";
  if (stream.match(sampleFunctionsRegex)) return "sampleFunction";
  if (stream.match(TOKEN_PATTERNS.VARIABLE)) return "variable";
  if (stream.match(TOKEN_PATTERNS.RELATION)) return "relation";
  if (stream.match(TOKEN_PATTERNS.MISC_OPERATOR)) return "miscOperator";
  if (stream.match(TOKEN_PATTERNS.OPERATOR)) return "miscOperator";

  stream.next();
  return null;
}

// Main tokenizer function
export function tokenize(input: string): Token[] {
  const tokens: Token[] = [];
  const stream = new StringStream(input, 0, 0);

  while (stream.pos < input.length) {
    const from = stream.pos;
    const type = nextToken(stream);

    if (type) {
      tokens.push({
        type,
        text: input.slice(from, stream.pos),
        from,
        to: stream.pos,
      });
    }
  }

  return tokens;
}

// Language definition
export const language = StreamLanguage.define({
  token: nextToken,
  tokenTable: {
    string: tags.string,
    unterminatedString: tags.string,
    number: tags.number,
    keyword: tags.keyword,
    mathFunction: tags.function(tags.variableName),
    sampleFunction: tags.function(tags.variableName),
    variable: tags.variableName,
    relation: tags.operator,
    miscOperator: tags.operator,
  },
});
