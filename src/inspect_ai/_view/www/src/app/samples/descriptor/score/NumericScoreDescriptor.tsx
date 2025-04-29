import { Value2 } from "../../../../@types/log";
import { kScoreTypeNumeric } from "../../../../constants";
import { formatDecimalNoTrailingZeroes } from "../../../../utils/format";
import { compareWithNan } from "../../../../utils/numeric";
import { ScoreDescriptor } from "../types";

export const numericScoreDescriptor = (values: Value2[]): ScoreDescriptor => {
  const onlyNumeric = values.filter((val) => {
    return typeof val === "number";
  });

  return {
    scoreType: kScoreTypeNumeric,
    min: Math.min(...onlyNumeric),
    max: Math.max(...onlyNumeric),
    compare: (a, b) => {
      if (typeof a.value === "number" && typeof b.value === "number") {
        return compareWithNan(a.value, b.value);
      } else {
        console.warn("Comparing non-numerics using a numeric score descriptor");
        return 0;
      }
    },
    render: (score) => {
      return formatDecimalNoTrailingZeroes(Number(score));
    },
  };
};
