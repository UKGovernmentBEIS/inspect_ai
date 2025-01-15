import { SampleSummary } from "../../api/Types";
import { kScoreTypeCategorical, kScoreTypeNumeric } from "../../constants";
import { ScoreFilter } from "../../Types.mjs";
import { isNumeric } from "../../utils/type";
import { SamplesDescriptor } from "../SamplesDescriptor.mjs";

/**
 * Gets a filter function for the specified type
 */
export const filterFnForType = (
  filter: ScoreFilter,
):
  | ((
      descriptor: SamplesDescriptor,
      sample: SampleSummary,
      value: string,
    ) => boolean)
  | undefined => {
  if (filter.type) {
    return filterFnsForType[filter.type];
  } else {
    return undefined;
  }
};

const filterCategory = (
  descriptor: SamplesDescriptor,
  sample: SampleSummary,
  value: string,
): boolean => {
  const score = descriptor.selectedScore(sample);
  if (typeof score.value === "string") {
    return score.value.toLowerCase() === value?.toLowerCase();
  } else if (typeof score.value === "object") {
    return JSON.stringify(score.value) == value;
  } else {
    return String(score.value) === value;
  }
};

const filterText = (
  descriptor: SamplesDescriptor,
  sample: SampleSummary,
  value: string,
): boolean => {
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
          fn: (score: number, val: number) => {
            return score >= val;
          },
        },
        {
          prefix: "<=",
          fn: (score: number, val: number) => {
            return score <= val;
          },
        },
        {
          prefix: ">",
          fn: (score: number, val: number) => {
            return score > val;
          },
        },
        {
          prefix: "<",
          fn: (score: number, val: number) => {
            return score < val;
          },
        },
        {
          prefix: "=",
          fn: (score: number, val: number) => {
            return score === val;
          },
        },
        {
          prefix: "!=",
          fn: (score: number, val: number) => {
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
          // TODO: This isn't great since scores can be more complex
          const scoreNum = Number(score.value);
          return filter.fn(scoreNum, num);
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
 */
const filterFnsForType: Record<
  string,
  (
    descriptor: SamplesDescriptor,
    sample: SampleSummary,
    value: string,
  ) => boolean
> = {
  [kScoreTypeCategorical]: filterCategory,
  [kScoreTypeNumeric]: filterText,
};
