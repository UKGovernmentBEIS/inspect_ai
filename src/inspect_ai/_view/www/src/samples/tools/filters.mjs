import { kScoreTypeCategorical, kScoreTypeNumeric } from "../../constants.mjs";
import { isNumeric } from "../../utils/Type.mjs";

/**
 * Gets a filter function for the specified type
 *
 * @param {import("../../Types.mjs").ScoreFilter} filter - The parameters for the component.
 * @returns {(descriptor: import("../SamplesDescriptor.mjs").SamplesDescriptor, sample: import("../../api/Types.mjs").SampleSummary, value: string) => boolean | undefined} the function
 */
export const filterFnForType = (filter) => {
  if (filter.type) {
    return filterFnsForType[filter.type];
  } else {
    return undefined;
  }
};

/**
 * @type{(descriptor: import("../SamplesDescriptor.mjs").SamplesDescriptor, sample: import("../../api/Types.mjs").SampleSummary, value: string) => boolean}
 */
const filterCategory = (descriptor, sample, value) => {
  const score = descriptor.selectedScore(sample);
  if (typeof score.value === "string") {
    return score.value.toLowerCase() === value?.toLowerCase();
  } else if (typeof score.value === "object") {
    return JSON.stringify(score.value) == value;
  } else {
    return String(score.value) === value;
  }
};

/**
 * @type{(descriptor: import("../SamplesDescriptor.mjs").SamplesDescriptor, sample: import("../../api/Types.mjs").SampleSummary, value: string) => boolean}
 */
const filterText = (descriptor, sample, value) => {
  const score = descriptor.selectedScore(sample);
  if (!value) {
    return true;
  } else {
    if (isNumeric(value)) {
      if (typeof score.value === "number") {
        return score.value === Number(value);
      } else {
        return Number(score.value) === Number(value);
      }
    } else {
      const filters = [
        {
          prefix: ">=",
          fn: (score, val) => {
            return score >= val;
          },
        },
        {
          prefix: "<=",
          fn: (score, val) => {
            return score <= val;
          },
        },
        {
          prefix: ">",
          fn: (score, val) => {
            return score > val;
          },
        },
        {
          prefix: "<",
          fn: (score, val) => {
            return score < val;
          },
        },
        {
          prefix: "=",
          fn: (score, val) => {
            return score === val;
          },
        },
        {
          prefix: "!=",
          fn: (score, val) => {
            return score !== val;
          },
        },
      ];

      for (const filter of filters) {
        if (value?.startsWith(filter.prefix)) {
          const val = value.slice(filter.prefix.length).trim();
          if (!val) {
            return true;
          }

          const num = Number(val);
          return filter.fn(score.value, num);
        }
      }
      if (typeof score.value === "string") {
        return score.value.toLowerCase() === value?.toLowerCase();
      } else {
        return String(score.value) === value;
      }
    }
  }
};

/**
 * A dictionary that maps filter types to their respective filter functions.
 *
 * @type {Record<string, (descriptor, sample, value) => boolean>}
 */
const filterFnsForType = {
  [kScoreTypeCategorical]: filterCategory,
  [kScoreTypeNumeric]: filterText,
};
