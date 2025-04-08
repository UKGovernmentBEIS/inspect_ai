import clsx from "clsx";
import { Value2 } from "../../../../@types/log";
import { kScoreTypePassFail } from "../../../../constants";
import { ScoreDescriptor, SelectedScore } from "../types";
import styles from "./PassFailScoreDescriptor.module.css";

export const passFailScoreDescriptor = (values: Value2[]): ScoreDescriptor => {
  const categories = [];
  if (values.includes("C")) {
    categories.push({
      val: "C",
      text: "Correct",
    });
  }
  if (values.includes("P")) {
    categories.push({
      val: "P",
      text: "Partial",
    });
  }
  if (values.includes("I")) {
    categories.push({
      val: "I",
      text: "Incorrect",
    });
  }
  if (values.includes("N")) {
    categories.push({
      val: "N",
      text: "Refusal",
    });
  }
  const order = ["C", "P", "I", "N"];

  return {
    scoreType: kScoreTypePassFail,
    categories,
    render: (score: Value2) => {
      if (score === "C") {
        return (
          <span
            className={clsx("text-size-small", styles.circle, styles.green)}
          >
            C
          </span>
        );
      } else if (score === "I") {
        return (
          <span className={clsx("text-size-small", styles.circle, styles.red)}>
            I
          </span>
        );
      } else if (score === "P") {
        return (
          <span
            className={clsx("text-size-small", styles.circle, styles.orange)}
          >
            P
          </span>
        );
      } else if (score === "N") {
        return (
          <span className={clsx("text-size-small", styles.circle, styles.red)}>
            N
          </span>
        );
      } else {
        return String(score);
      }
    },
    compare: (a: SelectedScore, b: SelectedScore) => {
      if (typeof a.value !== "string" || typeof b.value !== "string") {
        throw new Error(
          "Unexpectedly using the pass fail scorer on non-string values",
        );
      }
      const sort = order.indexOf(a.value || "") - order.indexOf(b.value || "");
      return sort;
    },
  };
};
