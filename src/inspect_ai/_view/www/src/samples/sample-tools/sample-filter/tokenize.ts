import { StreamLanguage, StringStream } from "@codemirror/language";
import { tags } from "@lezer/highlight";
import { KEYWORDS, MATH_FUNCTIONS, SAMPLE_FUNCTIONS } from "./language";

export type Token = {
  type: string;
  text: string;
  from: number;
  to: number;
};

export function tokenize(input: string): Token[] {
  const tokens = [];
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

const mathFunctionsRe = wordRegex(MATH_FUNCTIONS.map(([label]) => label));
const sampleFunctionsRe = wordRegex(SAMPLE_FUNCTIONS.map(([label]) => label));

const keywordsRe = wordRegex(
  // Sort to make sure "not in" is matched before "not".
  KEYWORDS.sort((a, b) => countSpaces(b) - countSpaces(a)),
);

function wordRegex(words: string[]): RegExp {
  return new RegExp(`^(${words.join("|")})\\b`);
}

function countSpaces(word: string) {
  return word.split(" ").length - 1;
}

function nextToken(stream: StringStream): string | null {
  if (stream.match(/"[^"]*"/)) return "string";
  if (stream.match(/"[^"]*/)) return "unterminatedString";
  if (stream.match(/^(-|\+)?\d+(\.\d+)?/)) return "number";
  if (stream.match(keywordsRe)) return "keyword";
  if (stream.match(mathFunctionsRe)) return "mathFunction";
  if (stream.match(sampleFunctionsRe)) return "sampleFunction";
  if (stream.match(/^[a-zA-Z_][a-zA-Z0-9_]*/)) return "variable";
  if (stream.match(/^(==|!=|<=|>=|<|>|~=)/)) return "relation";
  if (stream.match(/^(=|!|~)/)) return "miscOperator"; // recognize relations while typing; not valid syntax per se
  if (stream.match(/^(\+|-|\*|\/|\^|\(|\)|,|\.)/)) return "miscOperator";
  stream.next();
  return null;
}
