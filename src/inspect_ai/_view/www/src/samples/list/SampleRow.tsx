import clsx from "clsx";
import { FC, ReactNode, useCallback } from "react";
import { SampleSummary } from "../../api/types";
import { useAppContext } from "../../AppContext";
import { MarkdownDiv } from "../../components/MarkdownDiv";
import { arrayToString, inputString } from "../../utils/format";
import { SampleErrorView } from "../error/SampleErrorView";
import styles from "./SampleRow.module.css";

interface SampleRowProps {
  id: string;
  index: number;
  sample: SampleSummary;
  answer: string;
  completed: boolean;
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
  completed,
  scoreRendered,
  gridColumnsTemplate,
  height,
  selected,
  showSample,
}) => {
  const appContext = useAppContext();
  const handleClick = useCallback(() => {
    if (completed || appContext.capabilities.streamSampleData) {
      showSample(index);
    }
  }, [index, showSample, completed]);

  return (
    <div
      id={`sample-${id}`}
      onClick={handleClick}
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
        ) : completed ? (
          scoreRendered
        ) : (
          <Spinner />
        )}
      </div>
    </div>
  );
};

const Spinner: React.FC = () => {
  return (
    <div className={clsx("spinner-border", styles.spinner)} role="status">
      <span className={clsx("visually-hidden")}>Running...</span>
    </div>
  );
};
