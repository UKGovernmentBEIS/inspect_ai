import { compileExpression } from "filtrex";
import {
  kScoreTypeBoolean,
  kScoreTypeCategorical,
  kScoreTypeNumeric,
  kScoreTypePassFail,
} from "../../constants.mjs";
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
 * @param {import("../../samples/SamplesDescriptor.mjs").ScoreDescriptor} descriptor
 * @returns {boolean}
 */
const isFilteringSupportedForScore = (descriptor) => {
  if (!descriptor) {
    return false;
  }
  return [
    kScoreTypePassFail,
    kScoreTypeCategorical,
    kScoreTypeNumeric,
    kScoreTypeBoolean,
  ].includes(descriptor.scoreType);
};

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
 * @property {string} canonicalName - The canonical name of the score.
 * @property {string} tooltip - The informational tooltip for the score.
 * @property {boolean} isFilterable - Whether the score can be used in a filter expression.
 * @property {string[]} suggestions - Suggested expressions for the score.
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
   * @param {string} canonicalName
   * @param {import("../../Types.mjs").ScoreLabel} scoreLabel
   */
  const addScore = (canonicalName, scoreLabel) => {
    const descriptor = evalDescriptor.scoreDescriptor(scoreLabel);
    if (!descriptor || !isFilteringSupportedForScore(descriptor)) {
      items.push({
        canonicalName,
        tooltip: undefined,
        isFilterable: false,
        suggestions: [],
      });
      return;
    }
    var tooltip = `${canonicalName}: ${descriptor.scoreType}`;
    var suggestions = [];
    if (descriptor.min !== undefined || descriptor.max !== undefined) {
      const rounded = (num) => {
        // Additional round-trip to remove trailing zeros.
        return parseFloat(num.toPrecision(3)).toString();
      };
      tooltip += `\nrange: ${rounded(descriptor.min)} to ${rounded(descriptor.max)}`;
    }
    if (descriptor.categories) {
      tooltip += `\ncategories: ${descriptor.categories.map((cat) => cat.val).join(", ")}`;
      suggestions = [
        canonicalName,
        ...descriptor.categories.map(
          (cat) => `${canonicalName} == ${valueToString(cat.val)}`,
        ),
      ];
    }
    items.push({ canonicalName, tooltip, isFilterable: true, suggestions });
  };

  for (const { name, scorer } of evalDescriptor.scores) {
    const canonicalName =
      name !== scorer && bannedShortNames.has(name)
        ? `${scorer}.${name}`
        : name;
    addScore(canonicalName, { name, scorer });
  }
  return items;
};

/**
 * @param {import("../../Types.mjs").ScoreFilter} filter
 * @param {string} fragment
 * @returns {import("../../Types.mjs").ScoreFilter}
 */
export const addFragmentToFilter = (filter, fragment) => {
  var value = filter.value || "";
  if (value.trim() && !value.endsWith(" ")) {
    value = `${value} `;
  }
  if (value.trim() && !value.match(/ +(or|and) *$/)) {
    value = `${value}and `;
  }
  value += fragment;
  return { value };
};

/**
 * TODO: Add case-insensitive string comparison.
 * TODO: Pass EvalSample instead of SampleSummary and allow full-text message search.
 *
 * @param {import("../../samples/SamplesDescriptor.mjs").EvalDescriptor} evalDescriptor
 * @param {import("../../api/Types.mjs").SampleSummary} sample
 * @param {string} value
 * @returns {{matches: boolean, error: FilterError | undefined}}
 */
export const filterExpression = (evalDescriptor, sample, value) => {
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
    const expression = compileExpression(value, { extraFunctions });
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
        const match = regex.exec(value);
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

    return {
      matches: false,
      error: {
        message: error.message,
        severity: "error",
      },
    };
  }
};
