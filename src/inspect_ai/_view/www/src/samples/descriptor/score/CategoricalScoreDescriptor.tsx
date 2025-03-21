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
      return String(a.value).localeCompare(String(b.value));
    },
    render: (score) => {
      return String(score);
    },
  };
};
