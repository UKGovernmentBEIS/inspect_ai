import clsx from "clsx";
import { Value2 } from "../../../../@types/log";
import { ScoreDescriptor, SelectedScore } from "../types";
import styles from "./BooleanScoreDescriptor.module.css";

export const booleanScoreDescriptor = (): ScoreDescriptor => {
  return {
    scoreType: "boolean",
    compare: (a: SelectedScore, b: SelectedScore) => {
      return Number(a.value) - Number(b.value);
    },
    render: (score: Value2) => {
      return (
        <span
          className={clsx(
            styles.circle,
            "text-size-small",
            score ? styles.green : styles.red,
          )}
        >
          {String(score)}
        </span>
      );
    },
  };
};
