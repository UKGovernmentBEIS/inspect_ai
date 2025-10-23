interface SampleHeaderProps {
  input?: boolean;
  target?: boolean;
  answer?: boolean;
  limit?: boolean;
  retries?: boolean;
  scoreLabels?: string[];
  gridColumnsTemplate: string;
}
import clsx from "clsx";
import { FC } from "react";
import styles from "./SampleHeader.module.css";

export const SampleHeader: FC<SampleHeaderProps> = ({
  input = true,
  target = true,
  answer = true,
  limit = true,
  retries = false,
  scoreLabels = ["Score"],
  gridColumnsTemplate,
}) => (
  <div
    className={clsx(
      styles.header,
      "text-size-smallestest",
      "text-style-label",
      "text-style-secondary",
    )}
    style={{ gridTemplateColumns: gridColumnsTemplate }}
  >
    <div>Id</div>
    <div>{input ? "Input" : ""}</div>
    <div>{target ? "Target" : ""}</div>
    <div>{answer ? "Answer" : ""}</div>
    <div>{limit ? "Limit" : ""}</div>
    <div>{retries ? "Retries" : ""}</div>
    {scoreLabels.map((label, i) => (
      <div
        key={`score-header-${i}`}
        className={clsx(styles.center, styles.shrinkable)}
      >
        {label}
      </div>
    ))}
  </div>
);
