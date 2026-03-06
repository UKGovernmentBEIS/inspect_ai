import { Value2 } from "../../../../@types/log";
import { kScoreTypeList } from "../../../../constants";
import { formatPrettyDecimal } from "../../../../utils/format";
import { isNumeric } from "../../../../utils/type";
import { ScoreDescriptor, SelectedScore } from "../types";

export const listScoreDescriptor = (_values: Value2[]): ScoreDescriptor => {
  return {
    scoreType: kScoreTypeList,
    filterable: false,
    compare: (a: SelectedScore, b: SelectedScore) => {
      return (a.value as any as []).length - (b.value as any as []).length;
    },
    render: (score) => {
      if (score === null || score === undefined) {
        return "[null]";
      }

      const formattedScores: string[] = [];
      (score as []).forEach((value) => {
        if (!Array.isArray(score)) {
          throw new Error(
            "Unexpected use of list score descriptor for non-lisß object",
          );
        }
        const formattedValue =
          value && isNumeric(value)
            ? formatPrettyDecimal(
                typeof value === "number"
                  ? value
                  : parseFloat(value === true ? "1" : value),
              )
            : String(value);
        formattedScores.push(formattedValue);
      });

      return <div key={`score-value`}>[{formattedScores.join(", ")}]</div>;
    },
  };
};
