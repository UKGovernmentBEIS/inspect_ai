import { compileExpression } from "filtrex";
import { SampleSummary } from "../../api/types";
import { kScoreTypeBoolean } from "../../constants";
import { ScoreLabel } from "../../types";
import { Scores1 } from "../../types/log";
import { inputString } from "../../utils/format";
import { EvalDescriptor, ScoreDescriptor } from "../descriptor/types";

export interface FilterError {
  from: number;
  to: number;
  message: string;
  severity: "warning" | "error";
}

export interface ScoreFilterItem {
  shortName?: string;
  qualifiedName?: string;
  canonicalName: string;
  tooltip?: string;
  categories: string[];
  scoreType: string;
}

/**
 * Coerces a value to the type expected by the score.
 */
const coerceValue = (value: unknown, descriptor: ScoreDescriptor): unknown => {
  if (descriptor && descriptor.scoreType === kScoreTypeBoolean) {
    return Boolean(value);
  } else {
    return value;
  }
};

// Whether a particular value is filter-able
const isFilteringSupportedForValue = (value: unknown): boolean =>
  ["string", "number", "boolean"].includes(typeof value) || value === null;

/**
 * Returns the names of scores that are not allowed to be used as short names in
 * filter expressions because they are not unique. This should be applied only to
 * the nested scores, not to the top-level scorer names.
 */
const bannedShortScoreNames = (scores: ScoreLabel[]): Set<string> => {
  const used: Set<string> = new Set();
  const banned: Set<string> = new Set();
  for (const { scorer, name } of scores) {
    banned.add(scorer);
    if (used.has(name)) {
      banned.add(name);
    } else {
      used.add(name);
    }
  }
  return banned;
};

// Pseudo-variables added to all filter expressions. These are not needed in most cases.
// Normally one could check a boolean value `foo` by simply typing `foo` or `not foo`.
// However, some evals use tristate values that can be true, false or null. This is where
// these constants come in handy.
const filterExpressionConstants: Record<string, unknown> = {
  True: true,
  False: false,
  None: null,
};

/**
 * Generates a dictionary of variables that can be used in the filter expression.
 * High-level scorer metrics can be accessed by name directly.
 * Child metrics are accessed using dot notation (e.g. `scorer_name.score_name`) or
 * directly by name when it is unique.
 */
const scoreVariables = (
  evalDescriptor: EvalDescriptor,
  sampleScores: Scores1,
): Record<string, unknown> => {
  const bannedShortNames = bannedShortScoreNames(evalDescriptor.scores);
  const variables: Record<string, unknown> = {};

  const addScore = (
    variableName: string,
    scoreLabel: ScoreLabel,
    value: unknown,
  ): void => {
    const coercedValue = coerceValue(
      value,
      evalDescriptor.scoreDescriptor(scoreLabel),
    );
    if (isFilteringSupportedForValue(coercedValue)) {
      variables[variableName] = coercedValue;
    }
  };

  for (const [scorer, score] of Object.entries(sampleScores || {})) {
    addScore(scorer, { scorer, name: scorer }, score.value);
    if (typeof score.value === "object") {
      for (const [name, value] of Object.entries(score.value)) {
        addScore(`${scorer}.${name}`, { scorer, name }, value);
        if (!bannedShortNames.has(name)) {
          addScore(name, { scorer, name }, value);
        }
      }
    }
  }
  return variables;
};

const sampleVariables = (sample: SampleSummary): Record<string, unknown> => {
  return {
    has_error: !!sample.error,
  };
};

/**
 * Generates a dictionary of variables that can be used in the filter expression.
 * High-level scorer metrics can be accessed by name directly.
 * Child metrics are accessed using dot notation (e.g. `scorer_name.score_name`) or
 * directly by name when it is unique.
 */
export const scoreFilterItems = (
  evalDescriptor: EvalDescriptor,
): ScoreFilterItem[] => {
  const items: ScoreFilterItem[] = [];
  const bannedShortNames = bannedShortScoreNames(evalDescriptor.scores);
  const valueToString = (value: unknown) =>
    typeof value === "string" ? `"${value}"` : String(value);

  const addScore = (
    scoreLabel: ScoreLabel,
    shortName?: string,
    qualifiedName?: string,
  ) => {
    const canonicalName = shortName || qualifiedName;
    if (!canonicalName) {
      throw new Error("Unable to create a canonical name for a score");
    }
    const descriptor = evalDescriptor.scoreDescriptor(scoreLabel);
    const scoreType = descriptor?.scoreType;
    if (!descriptor) {
      items.push({
        shortName,
        qualifiedName,
        canonicalName,
        tooltip: undefined,
        categories: [],
        scoreType,
      });
      return;
    }
    var tooltip = `${canonicalName}: ${descriptor.scoreType}`;
    var categories: string[] = [];
    if (descriptor.min !== undefined || descriptor.max !== undefined) {
      const rounded = (num: number) => {
        // Additional round-trip to remove trailing zeros.
        return parseFloat(num.toPrecision(3)).toString();
      };
      tooltip += `\nrange: ${rounded(descriptor.min || 0)} to ${rounded(descriptor.max || 0)}`;
    }
    if (descriptor.categories) {
      categories = descriptor.categories.map((cat) => {
        const val = (cat as Record<string, unknown>).val;
        return valueToString(val);
      });
      tooltip += `\ncategories: ${categories.join(" ")}`;
    }
    items.push({
      shortName,
      qualifiedName,
      canonicalName,
      tooltip,
      categories,
      scoreType,
    });
  };

  for (const { name, scorer } of evalDescriptor.scores) {
    const hasShortName = name === scorer || !bannedShortNames.has(name);
    const hasQualifiedName = name !== scorer;
    const shortName = hasShortName ? name : undefined;
    const qualifiedName = hasQualifiedName ? `${scorer}.${name}` : undefined;
    addScore({ name, scorer }, shortName, qualifiedName);
  }
  return items;
};

// TODO: Add case-insensitive string comparison.
export const filterExpression = (
  evalDescriptor: EvalDescriptor,
  sample: SampleSummary,
  filterValue: string,
) => {
  try {
    const inputContains = (regex: string): boolean => {
      return inputString(sample.input).some((msg) =>
        msg.match(new RegExp(regex, "i")),
      );
    };
    const targetContains = (regex: string): boolean => {
      let targets = Array.isArray(sample.target)
        ? sample.target
        : [sample.target];
      return targets.some((target) => target.match(new RegExp(regex, "i")));
    };
    const errorContains = (regex: string): boolean => {
      return !!sample.error?.match(new RegExp(regex, "i"));
    };

    const extraFunctions = {
      input_contains: inputContains,
      target_contains: targetContains,
      error_contains: errorContains,
    };
    const mySampleVariables = sampleVariables(sample);
    const vars = {
      ...mySampleVariables,
      ...scoreVariables(evalDescriptor, sample.scores),
    };
    const resolveVariable = (name: string, get: (name: string) => any) => {
      // Sample variables (like has_error) always exist.
      if (name in mySampleVariables) {
        return get(name);
      }
      // Score variables exist only if the sample completed successfully.
      return sample.error ? undefined : get(name);
    };
    const expression = compileExpression(filterValue, {
      extraFunctions,
      constants: filterExpressionConstants,
      customProp: resolveVariable,
    });
    const result = expression(vars);
    if (typeof result === "boolean") {
      return { matches: result, error: undefined };
    } else if (result instanceof Error) {
      throw result;
    } else {
      throw new TypeError(
        `Filter expression returned a non-boolean value: ${result}`,
      );
    }
  } catch (error) {
    if (error instanceof ReferenceError) {
      const errorObj = error as any as Record<string, unknown>;
      const propertyName: string = (errorObj["propertyName"] as string) || "";
      if (propertyName) {
        const regex = new RegExp(`\\b${propertyName}\\b`);
        const match = regex.exec(filterValue);
        if (match) {
          return {
            matches: false,
            error: {
              from: match.index,
              to: match.index + propertyName.length,
              message: error.message,
              severity: "warning",
            },
          };
        }
      }
    }

    const message = error instanceof Error ? error.message : "";
    if (
      message.startsWith("Parse error") ||
      message.startsWith("Lexical error")
    ) {
      // Filterex uses formatting like this:
      //   foo and
      //   ----^
      const from = message.match(/^(-*)\^$/m)?.[1]?.length;
      return {
        matches: false,
        error: {
          from: from,
          message: "Syntax error",
          severity: "error",
        },
      };
    }

    return {
      matches: false,
      error: {
        message: message,
        severity: "error",
      },
    };
  }
};

export const filterSamples = (
  evalDescriptor: EvalDescriptor,
  samples: SampleSummary[],
  filterValue: string,
): { result: SampleSummary[]; error: FilterError | undefined } => {
  var error = undefined;
  const result = samples.filter((sample) => {
    if (filterValue) {
      const { matches, error: sampleError } = filterExpression(
        evalDescriptor,
        sample,
        filterValue,
      );
      error ||= sampleError;
      return matches;
    } else {
      return true;
    }
  });
  return { result, error };
};
