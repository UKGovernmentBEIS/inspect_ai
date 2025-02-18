import clsx from "clsx";
import { FC, ReactNode } from "react";
import { SampleSummary } from "../../api/types";
import { MarkdownDiv } from "../../components/MarkdownDiv";
import { arrayToString, inputString } from "../../utils/format";
import { SampleErrorView } from "../error/SampleErrorView";
import styles from "./SampleRow.module.css";

interface SampleRowProps {
  id: string;
  index: number;
  sample: SampleSummary;
  answer: string;
  scoreRendered: ReactNode;
  gridColumnsTemplate: string;
  height: number;
  selected: boolean;
  showSample: (index: number) => void;
}

export const SampleRow: FC<SampleRowProps> = ({
  id,
  index,
  sample,
  answer,
  scoreRendered,
  gridColumnsTemplate,
  height,
  selected,
  showSample,
}) => {
  return (
    <div
      id={`sample-${id}`}
      onClick={() => {
        showSample(index);
      }}
      className={clsx(
        styles.grid,
        "text-size-base",
        selected ? styles.selected : undefined,
      )}
      style={{
        height: `${height}px`,
        gridTemplateRows: `${height - 28}px`,
        gridTemplateColumns: gridColumnsTemplate,
      }}
    >
      <div className={clsx("sample-id", "three-line-clamp", styles.cell)}>
        {sample.id}
      </div>
      <div
        className={clsx(
          "sample-input",
          "three-line-clamp",
          styles.cell,
          styles.wrapAnywhere,
        )}
      >
        {inputString(sample.input).join(" ")}
      </div>
      <div className={clsx("sample-target", "three-line-clamp", styles.cell)}>
        <MarkdownDiv
          markdown={arrayToString(sample?.target)}
          className={clsx("no-last-para-padding", styles.noLeft)}
        />
      </div>
      <div className={clsx("sample-answer", "three-line-clamp", styles.cell)}>
        {sample ? (
          <MarkdownDiv
            markdown={answer || ""}
            className={clsx("no-last-para-padding", styles.noLeft)}
          />
        ) : (
          ""
        )}
      </div>
      <div
        className={clsx(
          "sample-limit",
          "text-size-small",
          "three-line-clamp",
          styles.cell,
        )}
      >
        {sample.limit}
      </div>

      <div className={clsx("text-size-small", styles.cell, styles.score)}>
        {sample.error ? (
          <SampleErrorView message={sample.error} />
        ) : (
          scoreRendered
        )}
      </div>
    </div>
  );
};
