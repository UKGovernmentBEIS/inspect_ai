import {
  Completion,
  CompletionContext,
  CompletionResult,
  CompletionSection,
  startCompletion,
} from "@codemirror/autocomplete";
import { EditorView } from "codemirror";
import { SampleSummary } from "../../../../client/api/types";
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
  kSampleIdVariable,
  kSampleMetadataVariable,
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

const applyWithDot = (
  view: EditorView,
  completion: Completion,
  from: number,
  to: number,
): void => {
  view.dispatch({
    changes: { from, to, insert: `${completion.label}.` },
    selection: { anchor: from + completion.label.length + 1 },
  });
  // trigger completion
  setTimeout(() => startCompletion(view), 0);
};

const applyWithSpace = (
  view: EditorView,
  completion: Completion,
  from: number,
  to: number,
): void => {
  view.dispatch({
    changes: { from, to, insert: `${completion.label} ` },
    selection: { anchor: from + completion.label.length + 1 },
  });
  // trigger completion
  setTimeout(() => startCompletion(view), 0);
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
  apply:
    label === kSampleMetadataVariable
      ? applyWithDot
      : label === kSampleIdVariable
        ? applyWithSpace
        : undefined,
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

const getSampleIds = (samples: SampleSummary[]): Set<string | number> => {
  const ids = new Set<string | number>();
  for (const sample of samples) {
    ids.add(sample.id);
  }
  return ids;
};

const getMetadataPropertyValues = (
  samples: SampleSummary[],
  propertyPath: string,
): Set<any> => {
  const values = new Set<any>();
  for (const sample of samples) {
    if (sample.metadata) {
      const value = getNestedProperty(sample.metadata, propertyPath);
      if (value !== undefined && value !== null) {
        values.add(value);
      }
    }
  }
  return values;
};

const getNestedProperty = (obj: any, path: string): any => {
  const keys = path.split(".");
  let current = obj;
  for (const key of keys) {
    if (current && typeof current === "object" && key in current) {
      current = current[key];
    } else {
      return undefined;
    }
  }
  return current;
};

const buildMetadataPath = (
  tokens: Token[],
  currentTokenIndex: number,
): string | null => {
  // Walk backwards to build the metadata path
  // For "metadata." return ""
  // For "metadata.config." return "config"
  // For "metadata.config.timeout." return "config.timeout"

  const parts: string[] = [];

  // Start after the first dot
  let index = 2;

  // Look for the metadata root by walking backwards
  while (index <= currentTokenIndex) {
    const token = tokens[currentTokenIndex - index];

    if (token?.text === kSampleMetadataVariable) {
      // Found metadata root, return the path
      return parts.reverse().join(".");
    } else if (token?.type === "variable") {
      // Found a variable token, add to path
      parts.push(token.text);
      // Skip the expected dot
      index++;
      if (tokens[currentTokenIndex - index]?.text === ".") {
        // Move past the dot
        index++;
      } else {
        // No dot, not a valid path
        break;
      }
    } else {
      // Hit non-variable, non-metadata token
      break;
    }
  }

  // Didn't find metadata root
  return null;
};

const getMetadataKeysForPath = (
  samples: SampleSummary[],
  parentPath: string,
): Set<string> => {
  const keys = new Set<string>();
  for (const sample of samples) {
    if (sample.metadata) {
      const parentObj = parentPath
        ? getNestedProperty(sample.metadata, parentPath)
        : sample.metadata;
      if (
        parentObj &&
        typeof parentObj === "object" &&
        !Array.isArray(parentObj)
      ) {
        for (const key of Object.keys(parentObj)) {
          keys.add(key);
        }
      }
    }
  }
  return keys;
};

const buildMetadataPropertyPath = (
  tokens: Token[],
  currentTokenIndex: number,
): string | null => {
  // Walk backwards to build the full metadata property path
  // e.g., for "metadata.difficulty ==" we want to return "difficulty"
  // e.g., for "metadata.config.timeout ==" we want to return "config.timeout"
  const parts: string[] = [];

  // Start after the dot
  let index = 2;

  // Collect the property path by walking backwards
  while (index <= currentTokenIndex) {
    const token = tokens[currentTokenIndex - index];
    if (!token) break;

    if (token.type === "variable") {
      if (token.text === kSampleMetadataVariable) {
        // Found the metadata root, return the path
        return parts.reverse().join(".");
      } else {
        parts.push(token.text);
      }
    } else if (token.text !== ".") {
      // Hit a non-dot, non-variable token, not a metadata path
      break;
    }
    index++;
  }

  return null;
};

const isMetadataProperty = (
  tokens: Token[],
  currentTokenIndex: number,
): boolean => {
  // Check if the current variable is part of a metadata property access
  // e.g., for "metadata.difficulty" return true

  // For metadata.difficulty, tokens are: [metadata, ., difficulty]
  // currentTokenIndex points after difficulty, so prevToken(1) = difficulty
  // We need to check if we can trace back to metadata

  // Start by looking at prevToken(2) which should be "."
  let index = 2;

  // Walk backwards looking for metadata root
  while (index <= currentTokenIndex) {
    const token = tokens[currentTokenIndex - index];
    if (!token) break;

    if (token.text === kSampleMetadataVariable) {
      return true;
    } else if (token.text === "." || token.type === "variable") {
      index++;
    } else {
      break; // Hit a non-metadata token
    }
  }

  return false;
};

const makeMetadataKeyCompletion = (key: string): Completion => ({
  label: key,
  type: "property",
  info: `Metadata property: ${key}`,
  boost: 25,
});

const makeSampleIdCompletion = (id: string | number): Completion => ({
  label: typeof id === "string" ? `"${id}"` : String(id),
  type: "text",
  info: `Sample ID: ${id}`,
  boost: 25,
});

const makeMetadataValueCompletion = (value: any): Completion => {
  let label: string;
  if (typeof value === "string") {
    label = `"${value}"`;
  } else if (typeof value === "boolean") {
    // Use filter expression constants for booleans
    label = value ? "True" : "False";
  } else if (value === null) {
    label = "None";
  } else {
    label = String(value);
  }

  return {
    label,
    type: "text",
    info: `Metadata value: ${value}`,
    boost: 25,
  };
};

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
  samples?: SampleSummary[],
): CompletionResult | null {
  const keywordCompletionItems = KEYWORDS.map(makeKeywordCompletion);
  const mathFunctionCompletionItems = MATH_FUNCTIONS.map(
    makeMathFunctionCompletion,
  );
  const sampleFunctionCompletionItems = SAMPLE_FUNCTIONS.map(
    makeSampleFunctionCompletion,
  );
  // Filter sample variables based on available data
  const availableSampleVariables = SAMPLE_VARIABLES.filter(([label]) => {
    if (label === kSampleMetadataVariable) {
      // Only include metadata if at least one sample has metadata
      return (
        samples &&
        samples.some(
          (sample) =>
            sample.metadata && Object.keys(sample.metadata).length > 0,
        )
      );
    }
    return true;
  });

  const sampleVariableCompletionItems = availableSampleVariables.map(
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

  const discreteRelationCompletions = () =>
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
    const varName = prevToken(2)?.text;

    // Check if this is metadata property access (metadata.* or metadata.*.*)
    const metadataPath = buildMetadataPath(tokens, currentTokenIndex);
    if (metadataPath !== null && samples) {
      // Get completions for the current metadata path
      const metadataKeys = Array.from(
        getMetadataKeysForPath(samples, metadataPath),
      );
      const metadataCompletions = metadataKeys.map(makeMetadataKeyCompletion);
      return makeCompletions(metadataCompletions, {
        autocompleteInTheMiddle: true,
        includeDefault: false,
      });
    } else if (varName) {
      return memberAccessCompletions(getMemberScoreItems(filterItems, varName));
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
    const varName = prevToken(1)?.text;

    // Check if this is a metadata property access (metadata.property or metadata.nested.property)
    if (isMetadataProperty(tokens, currentTokenIndex)) {
      // This is metadata.property - provide custom relation completions
      return customRelationCompletions();
    }

    // Handle sample variables specially
    if (varName === "epoch") {
      return continuousRelationCompletions();
    }
    if (varName === kSampleIdVariable) {
      return discreteRelationCompletions();
    }
    if (varName === kSampleMetadataVariable) {
      return customRelationCompletions();
    }
    if (varName === "has_error" || varName === "has_retries") {
      return logicalOpCompletions();
    }

    // Handle score variables
    const scoreType = findFilterItem(1)?.scoreType || "";
    switch (scoreType) {
      case kScoreTypePassFail:
      case kScoreTypeCategorical:
        return discreteRelationCompletions();
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
    const varName = prevToken(2)?.text;

    // Check if this is a metadata property comparison (relation after metadata.property or metadata.nested.property)
    const metadataPropertyPath = buildMetadataPropertyPath(
      tokens,
      currentTokenIndex,
    );
    if (metadataPropertyPath !== null && samples) {
      // This is metadata.property == ... - provide value completions for this property
      const metadataValues = Array.from(
        getMetadataPropertyValues(samples, metadataPropertyPath),
      );

      // Get the current query for prefix filtering
      const currentQuery = currentToken?.text || "";

      // Pre-filter values to only show prefix matches
      const filteredValues = currentQuery
        ? metadataValues.filter((value) => {
            const label =
              typeof value === "string"
                ? `"${value}"`
                : typeof value === "boolean"
                  ? value
                    ? "True"
                    : "False"
                  : value === null
                    ? "None"
                    : String(value);
            return label.toLowerCase().startsWith(currentQuery.toLowerCase());
          })
        : metadataValues;

      const metadataValueCompletions = filteredValues.map(
        makeMetadataValueCompletion,
      );
      return makeCompletions(metadataValueCompletions, {
        includeDefault: false,
      });
    }

    // Sample ID completions
    if (varName === kSampleIdVariable && samples) {
      const sampleIds = Array.from(getSampleIds(samples));

      // Get the current query for prefix filtering
      const currentQuery = currentToken?.text || "";

      // Pre-filter IDs to only show prefix matches
      const filteredIds = currentQuery
        ? sampleIds.filter((id) => {
            const label = typeof id === "string" ? `"${id}"` : String(id);
            return label.toLowerCase().startsWith(currentQuery.toLowerCase());
          })
        : sampleIds;

      const sampleIdCompletions = filteredIds.map(makeSampleIdCompletion);
      return makeCompletions(sampleIdCompletions, {
        includeDefault: false,
      });
    }

    // Epoch value completions (suggest actual epoch numbers from loaded samples)
    if (varName === "epoch" && samples) {
      const epochValues = Array.from(
        new Set(samples.map((s) => s.epoch).filter((e) => e !== undefined)),
      ).sort((a, b) => a - b);
      const epochCompletions = epochValues.map((e) =>
        makeLiteralCompletion(String(e)),
      );
      return makeCompletions(epochCompletions, {
        includeDefault: epochCompletions.length === 0,
      });
    }

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
