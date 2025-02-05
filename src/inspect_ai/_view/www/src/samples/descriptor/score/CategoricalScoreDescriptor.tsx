import { kScoreTypeCategorical } from "../../../constants";
import { Value2 } from "../../../types/log";
import { ScoreDescriptor } from "../types";

export const categoricalScoreDescriptor = (
  values: Value2[],
): ScoreDescriptor => {
  return {
    scoreType: kScoreTypeCategorical,
    categories: values,
    compare: (a, b) => {
      return String(a).localeCompare(String(b));
    },
    render: (score) => {
      return String(score);
    },
  };
};
