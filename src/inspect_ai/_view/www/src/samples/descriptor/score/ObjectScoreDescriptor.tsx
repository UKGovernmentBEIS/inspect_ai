import clsx from "clsx";
import { JSX } from "react";
import { kScoreTypeObject } from "../../../constants";
import { Value2 } from "../../../types/log";
import { formatPrettyDecimal } from "../../../utils/format";
import { isNumeric } from "../../../utils/type";
import { ScoreDescriptor } from "../types";
import styles from "./ObjectScoreDescriptor.module.css";

export const objectScoreDescriptor = (values: Value2[]): ScoreDescriptor => {
  const buckets = values.map((val) => {
    return JSON.stringify(val);
  });
  const vals = new Set(buckets);
  let categories = undefined;
  if (vals.size < 10) {
    categories = Array.from(vals).map((val) => {
      return {
        val,
        text: val,
      };
    });
  }

  return {
    scoreType: kScoreTypeObject,
    categories,
    compare: () => {
      return 0;
    },
    render: (score) => {
      if (score === null || score === undefined) {
        return "[null]";
      }

      const scores: JSX.Element[] = [];
      const keys = Object.keys(score);
      keys.forEach((key, index) => {
        if (typeof score !== "object" || Array.isArray(score)) {
          throw new Error(
            "Unexpected us of object score descriptor for non-score object",
          );
        }
        const value = score[key];
        const formattedValue =
          value && isNumeric(value)
            ? formatPrettyDecimal(
                typeof value === "number"
                  ? value
                  : parseFloat(value === true ? "1" : value),
              )
            : String(value);
        scores.push(
          <div
            className={clsx(
              styles.container,
              index + 1 < keys.length ? styles.padded : undefined,
            )}
          >
            <div className={clsx(styles.key, "text-size-smaller")}>{key}</div>
            <div className={clsx(styles.value, "text-size-title")}>
              {formattedValue}
            </div>
          </div>,
        );
      });

      return scores;
    },
  };
};
