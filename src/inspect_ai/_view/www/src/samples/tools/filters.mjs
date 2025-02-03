import { compileExpression } from "filtrex";
import { kScoreTypeBoolean } from "../../constants.mjs";
import { inputString } from "../../utils/Format.mjs";

/**
 * @typedef {Object} FilterError
 * @property {number=} from - The start of the error.
 * @property {number=} to - The end of the error.
 * @property {string} message - The error message.
 * @property {"warning" | "error"} severity - The severity of the error.
 */

/**
 * Coerces a value to the type expected by the score.
 *
 * @param {any} value
 * @param {import("../../samples/SamplesDescriptor.mjs").ScoreDescriptor} descriptor
 * @returns {any}
 */
const coerceValue = (value, descriptor) => {
  if (descriptor && descriptor.scoreType === kScoreTypeBoolean) {
    return Boolean(value);
  } else {
    return value;
  }
};

/**
 * @param {any} value
 * @returns {boolean}
 */
const isFilteringSupportedForValue = (value) =>
  ["string", "number", "boolean"].includes(typeof value);

/**
 * Returns the names of scores that are not allowed to be used as short names in
 * filter expressions because they are not unique. This should be applied only to
 * the nested scores, not to the top-level scorer names.
 *
 * @param {import("../../Types.mjs").ScoreLabel[]} scores
 * @returns {Set<string>}
 */
const bannedShortScoreNames = (scores) => {
  const used = new Set();
  const banned = new Set();
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

/**
 * Generates a dictionary of variables that can be used in the filter expression.
 * High-level scorer metrics can be accessed by name directly.
 * Child metrics are accessed using dot notation (e.g. `scorer_name.score_name`) or
 * directly by name when it is unique.
 *
 * @param {import("../../samples/SamplesDescriptor.mjs").EvalDescriptor} evalDescriptor
 * @param {import("../../types/log").Scores1} sampleScores
 * @returns {Object<string, any>}
 */
const scoreVariables = (evalDescriptor, sampleScores) => {
  const bannedShortNames = bannedShortScoreNames(evalDescriptor.scores);
  const variables = {};

  /**
   * @param {import("../../Types.mjs").ScoreLabel} scoreLabel
   * @param {any} value
   */
  const addScore = (variableName, scoreLabel, value) => {
    const coercedValue = coerceValue(
      value,
      evalDescriptor.scoreDescriptor(scoreLabel),
    );
    if (isFilteringSupportedForValue(coercedValue)) {
      variables[variableName] = coercedValue;
    }
  };

  for (const [scorer, score] of Object.entries(sampleScores)) {
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

/**
 * @typedef {Object} ScoreFilterItem
 * @property {string | undefined} shortName - The short name of the score, if doesn't conflict with other short names.
 * @property {string | undefined} qualifiedName - The `scorer.score` name for children of complex scorers.
 * @property {string} canonicalName - The canonical name: either `shortName` or `qualifiedName` (at least one must exist).
 * @property {string} tooltip - The informational tooltip for the score.
 * @property {string[]} categories - Category values for categorical scores.
 * @property {string} scoreType - The type of the score (e.g., 'numeric', 'categorical', 'boolean').
 */

/**
 * Generates a dictionary of variables that can be used in the filter expression.
 * High-level scorer metrics can be accessed by name directly.
 * Child metrics are accessed using dot notation (e.g. `scorer_name.score_name`) or
 * directly by name when it is unique.
 *
 * @param {import("../../samples/SamplesDescriptor.mjs").EvalDescriptor} evalDescriptor
 * @returns {ScoreFilterItem[]}
 */
export const scoreFilterItems = (evalDescriptor) => {
  /** @type {ScoreFilterItem[]} */
  const items = [];
  const bannedShortNames = bannedShortScoreNames(evalDescriptor.scores);
  const valueToString = (value) =>
    typeof value === "string" ? `"${value}"` : String(value);

  /**
   * @param {string | undefined} shortName
   * @param {string | undefined} qualifiedName
   * @param {import("../../Types.mjs").ScoreLabel} scoreLabel
   */
  const addScore = (shortName, qualifiedName, scoreLabel) => {
    const canonicalName = shortName || qualifiedName;
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
    var categories = [];
    if (descriptor.min !== undefined || descriptor.max !== undefined) {
      const rounded = (num) => {
        // Additional round-trip to remove trailing zeros.
        return parseFloat(num.toPrecision(3)).toString();
      };
      tooltip += `\nrange: ${rounded(descriptor.min)} to ${rounded(descriptor.max)}`;
    }
    if (descriptor.categories) {
      tooltip += `\ncategories: ${descriptor.categories.map((cat) => cat.val).join(", ")}`;
      categories = descriptor.categories.map((cat) => valueToString(cat.val));
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
    addScore(shortName, qualifiedName, { name, scorer });
  }
  return items;
};

/**
 * TODO: Add case-insensitive string comparison.
 *
 * @param {import("../../samples/SamplesDescriptor.mjs").EvalDescriptor} evalDescriptor
 * @param {import("../../api/Types.mjs").SampleSummary} sample
 * @param {string} filterValue
 * @returns {{matches: boolean, error: FilterError | undefined}}
 */
export const filterExpression = (evalDescriptor, sample, filterValue) => {
  try {
    /** @type {(regex: string) => boolean} */
    const inputContains = (regex) => {
      return inputString(sample.input).some((msg) =>
        msg.match(new RegExp(regex, "i")),
      );
    };
    /** @type {(regex: string) => boolean} */
    const targetContains = (regex) => {
      let targets = Array.isArray(sample.target)
        ? sample.target
        : [sample.target];
      return targets.some((target) => target.match(new RegExp(regex, "i")));
    };

    const extraFunctions = {
      input_contains: inputContains,
      target_contains: targetContains,
    };
    const expression = compileExpression(filterValue, { extraFunctions });
    const vars = scoreVariables(evalDescriptor, sample.scores);
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
      const propertyName = error["propertyName"];
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
    if (
      error.message.startsWith("Parse error") ||
      error.message.startsWith("Lexical error")
    ) {
      // Filterex uses formatting like this:
      //   foo and
      //   ----^
      const from = error.message.match(/^(-*)\^$/m)?.[1]?.length;
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
        message: error.message,
        severity: "error",
      },
    };
  }
};

/**
 * @param {import("../../samples/SamplesDescriptor.mjs").EvalDescriptor} evalDescriptor
 * @param {import("../../api/Types.mjs").SampleSummary[]} samples
 * @param {string} filterValue
 * @returns {{result: import("../../api/Types.mjs").SampleSummary[], error: FilterError | undefined}}
 */
export const filterSamples = (evalDescriptor, samples, filterValue) => {
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
