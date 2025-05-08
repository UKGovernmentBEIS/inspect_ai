import {
  Completion,
  CompletionContext,
  CompletionResult,
  CompletionSection,
} from "@codemirror/autocomplete";
import { EditorView } from "codemirror";
import {
  kScoreTypeBoolean,
  kScoreTypeCategorical,
  kScoreTypeNumeric,
  kScoreTypeOther,
  kScoreTypePassFail,
} from "../../../../constants";
import { SampleFilterItem } from "../filters";
import {
  KEYWORDS,
  MATH_FUNCTIONS,
  SAMPLE_FUNCTIONS,
  SAMPLE_VARIABLES,
} from "./language";
import { Token, tokenize } from "./tokenize";

interface CompletionOptions {
  autocompleteInTheMiddle?: boolean;
  enforceOrder?: boolean;
  autoSpaceAfter?: boolean;
  includeDefault?: boolean;
}

interface CanonicalNameCompletionProps {
  autoSpaceIf?: (item: SampleFilterItem) => boolean;
}

const isLiteral = (token: Token): boolean =>
  ["string", "unterminatedString", "number"].includes(token?.type);

const isLogicalOp = (token: Token): boolean =>
  ["and", "or", "not"].includes(token?.text);

const autocompleteImmediatelyAfter = (token: Token): boolean =>
  ["(", "."].includes(token?.text);

const applyWithCall = (
  view: EditorView,
  completion: Completion,
  from: number,
  to: number,
): void => {
  view.dispatch({
    changes: { from, to, insert: `${completion.label}()` },
    selection: { anchor: from + completion.label.length + 1 },
  });
};

const makeKeywordCompletion = (k: string): Completion => ({
  label: k,
  type: "keyword",
  boost: -20,
});

const makeMathFunctionCompletion = ([label, info]: [
  string,
  string,
]): Completion => ({
  label,
  type: "function",
  info,
  apply: applyWithCall,
  boost: -10,
});

const makeSampleFunctionCompletion = ([label, info]: [
  string,
  string,
]): Completion => ({
  label,
  type: "function",
  info,
  apply: applyWithCall,
  boost: 0,
});

const makeSampleVariableCompletion = ([label, info]: [
  string,
  string,
]): Completion => ({
  label,
  type: "variable",
  info,
  boost: 10,
});

const makeLiteralCompletion = (k: string): Completion => ({
  label: k,
  type: "text",
  boost: 20,
});

const makeCanonicalNameCompletion = (
  item: SampleFilterItem,
  { autoSpaceIf = () => false }: CanonicalNameCompletionProps = {},
): Completion => ({
  label: item.canonicalName + (autoSpaceIf(item) ? " " : ""),
  type: "variable",
  info: item.tooltip,
  boost: 30,
});

const makeMemberAccessCompletion = (item: SampleFilterItem): Completion => ({
  label: item.qualifiedName?.split(".")[1] || "",
  type: "variable",
  info: item.tooltip,
  boost: 40,
});

const getMemberScoreItems = (
  filterItems: SampleFilterItem[],
  scorer: string,
): SampleFilterItem[] =>
  filterItems.filter((item) => item?.qualifiedName?.startsWith(`${scorer}.`));

/**
 * Generates completions for the filter expression. The main goal is to make the
 * sample filter intuitive for beginners and to provide a smooth experience for
 * simple cases. To this end, we proactively try to suggest the next step of the
 * expression, in a wizard-style fashion. This logic is primarily intended to
 * support unsophisticated expressions of the form
 *   SUBEXPR and/or SUBEXPR or/not SUBEXPR ...
 * where each SUBEXPR is
 *   VARIABLE ==/!=/</>/in/... VALUE
 * and VALUE is a literal (string, number, etc.)
 * It does support some expressions more complex than that, but the completion
 * algorithm is not intended to be comprehensive. This is why we usually add
 * default completions to the list in case our guess was off.
 */
export function getCompletions(
  context: CompletionContext,
  filterItems: SampleFilterItem[],
): CompletionResult | null {
  const keywordCompletionItems = KEYWORDS.map(makeKeywordCompletion);
  const mathFunctionCompletionItems = MATH_FUNCTIONS.map(
    makeMathFunctionCompletion,
  );
  const sampleFunctionCompletionItems = SAMPLE_FUNCTIONS.map(
    makeSampleFunctionCompletion,
  );
  const sampleVariableCompletionItems = SAMPLE_VARIABLES.map(
    makeSampleVariableCompletion,
  );
  const variableCompletionItems = filterItems.map((item) =>
    makeCanonicalNameCompletion(item),
  );

  const defaultCompletionItems = [
    ...keywordCompletionItems,
    ...mathFunctionCompletionItems,
    ...sampleFunctionCompletionItems,
    ...sampleVariableCompletionItems,
    ...variableCompletionItems,
  ];

  const doc = context.state.doc;
  const input = doc.toString().slice(0, context.pos);
  const tokens = tokenize(input);
  const lastToken = tokens[tokens.length - 1];
  const isCompletionInsideToken =
    lastToken &&
    context.pos === lastToken.to &&
    !autocompleteImmediatelyAfter(lastToken);
  const currentTokenIndex = isCompletionInsideToken
    ? tokens.length - 1
    : tokens.length;

  const prevToken = (index: number): Token => tokens[currentTokenIndex - index];
  const currentToken = prevToken(0);
  const completionStart = currentToken ? currentToken.from : context.pos;
  const completingAtEnd = context.pos === doc.length;

  const findFilterItem = (endIndex: number): SampleFilterItem | undefined => {
    if (prevToken(endIndex)?.type !== "variable") return undefined;

    let name = prevToken(endIndex).text;
    let i = endIndex;

    while (prevToken(i + 1)?.text === ".") {
      if (prevToken(i + 2)?.type === "variable") {
        name = `${prevToken(i + 2).text}.${name}`;
        i += 2;
      } else {
        break;
      }
    }

    return filterItems.find((item) => item.canonicalName === name);
  };

  const makeCompletions = (
    priorityCompletions: Completion[],
    {
      autocompleteInTheMiddle = false,
      enforceOrder = false,
      autoSpaceAfter = false,
      includeDefault = true,
    }: CompletionOptions = {},
  ): CompletionResult | null => {
    if (!autocompleteInTheMiddle && !completingAtEnd && !context.explicit) {
      return null;
    }

    const priorityCompletionsOrdered = enforceOrder
      ? priorityCompletions.map((c, idx) => ({ ...c, boost: -idx }))
      : priorityCompletions;

    const priorityCompletionsAdjusted = autoSpaceAfter
      ? priorityCompletionsOrdered.map((c) =>
          !c.apply && !c.label.endsWith(" ")
            ? { ...c, label: `${c.label} ` }
            : c,
        )
      : priorityCompletionsOrdered;

    if (!includeDefault) {
      return {
        from: completionStart,
        options: priorityCompletionsAdjusted,
      };
    }

    const miscSection: CompletionSection = {
      name: "misc",
      header: () => {
        const element = document.createElement("hr");
        element.style.display = "list-item";
        element.style.margin = "2px 0";
        return element;
      },
    };

    const priorityLabels = new Set(
      priorityCompletions.map((c) => c.label.trim()),
    );
    const defaultCompletionsAdjusted = defaultCompletionItems
      .filter((c) => !priorityLabels.has(c.label.trim()))
      .map((c) => ({ ...c, section: miscSection }));

    return {
      from: completionStart,
      options: [...priorityCompletionsAdjusted, ...defaultCompletionsAdjusted],
    };
  };

  const defaultCompletions = () => makeCompletions([]);
  const noCompletions = () => (context.explicit ? defaultCompletions() : null);

  const newExpressionCompletions = () =>
    makeCompletions([
      ...filterItems.map((item) =>
        makeCanonicalNameCompletion(item, {
          autoSpaceIf: (item) =>
            completingAtEnd && item.scoreType !== kScoreTypeBoolean,
        }),
      ),
      ...sampleVariableCompletionItems,
      ...sampleFunctionCompletionItems,
    ]);

  const variableCompletions = () => makeCompletions(variableCompletionItems);

  const memberAccessCompletions = (items: SampleFilterItem[]) =>
    makeCompletions(items.map(makeMemberAccessCompletion), {
      autocompleteInTheMiddle: true,
      includeDefault: false,
    });

  const logicalOpCompletions = () =>
    makeCompletions(["and", "or"].map(makeKeywordCompletion), {
      enforceOrder: true,
      autoSpaceAfter: completingAtEnd,
    });

  const descreteRelationCompletions = () =>
    makeCompletions(["==", "!=", "in", "not in"].map(makeKeywordCompletion), {
      enforceOrder: true,
      autoSpaceAfter: completingAtEnd,
    });

  const continuousRelationCompletions = () =>
    makeCompletions(
      ["<", "<=", ">", ">=", "==", "!="].map(makeKeywordCompletion),
      { enforceOrder: true, autoSpaceAfter: completingAtEnd },
    );

  const customRelationCompletions = () =>
    makeCompletions(
      ["<", "<=", ">", ">=", "==", "!=", "~="].map(makeKeywordCompletion),
      { enforceOrder: true, autoSpaceAfter: completingAtEnd },
    );

  const rhsCompletions = (options: string[]) =>
    makeCompletions(options.map(makeLiteralCompletion));

  // Handle specific completion scenarios
  if (!prevToken(1)) return newExpressionCompletions();

  // Member access
  if (prevToken(1)?.text === ".") {
    const scorer = prevToken(2)?.text;
    if (scorer) {
      return memberAccessCompletions(getMemberScoreItems(filterItems, scorer));
    }
  }

  // Function call or bracketed expression start
  if (prevToken(1)?.text === "(") {
    if (prevToken(2)?.type === "mathFunction") return variableCompletions();
    if (prevToken(2)?.type === "sampleFunction") return noCompletions();
    return newExpressionCompletions();
  }

  // Function call or bracketed expression end
  // Don't try to guess: too unpredictable. Could continue with an arithmetic
  // operator (if constructing a complex expression), with a comparison (if
  // comparing function call result to something) or with a logical connector
  // (if a new subexpression is starting). Very hard to figure out what is
  // going on without an AST, which we don't have here.
  if (prevToken(1)?.text === ")") return noCompletions();

  // Variable type-based relation suggestions
  if (prevToken(1)?.type === "variable") {
    const scoreType = findFilterItem(1)?.scoreType || "";

    switch (scoreType) {
      case kScoreTypePassFail:
      case kScoreTypeCategorical:
        return descreteRelationCompletions();
      case kScoreTypeNumeric:
        return continuousRelationCompletions();
      case kScoreTypeOther:
        return customRelationCompletions();
      case kScoreTypeBoolean:
        return logicalOpCompletions();
      default:
        return noCompletions();
    }
  }

  // RHS comparison suggestions
  if (prevToken(1)?.type === "relation") {
    const item = findFilterItem(2);
    if (item?.categories?.length) {
      return rhsCompletions(item.categories);
    }
    return variableCompletions();
  }

  // Post-subexpression connector suggestions
  if (isLiteral(prevToken(1)) && prevToken(2)?.type === "relation") {
    return logicalOpCompletions();
  }

  // New subexpression after logical connector
  if (isLogicalOp(prevToken(1))) return newExpressionCompletions();

  // Something unusual is going on. We don't have any good guesses, but the user
  // can trigger completion manually with Ctrl+Space if they want.
  return noCompletions();
}
