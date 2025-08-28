import clsx from "clsx";
import { FC, ReactNode } from "react";
import { SampleSummary } from "../../../client/api/types";
import { PulsingDots } from "../../../components/PulsingDots";
import { useStore } from "../../../state/store";
import { arrayToString, inputString } from "../../../utils/format";
import { isVscode } from "../../../utils/vscode";
import { RenderedText } from "../../content/RenderedText";
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
  showSample: () => void;
  sampleUrl?: string;
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
  showSample,
  sampleUrl,
}) => {
  const streamSampleData = useStore(
    (state) => state.capabilities.streamSampleData,
  );
  const selectedSampleIndex = useStore(
    (state) => state.log.selectedSampleIndex,
  );
  // Determine if this sample can be viewed (completed or streaming)
  const isViewable = completed || streamSampleData;

  const rowContent = (
    <div
      id={`sample-${id}`}
      className={clsx(
        styles.grid,
        "text-size-base",
        selectedSampleIndex === index ? styles.selected : undefined,
        !isViewable && !sampleUrl ? styles.disabled : undefined,
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
        <RenderedText
          markdown={inputString(sample.input).join(" ")}
          forceRender={true}
        />
      </div>
      <div className={clsx("sample-target", "three-line-clamp", styles.cell)}>
        {sample?.target ? (
          <RenderedText
            markdown={arrayToString(sample.target)}
            className={clsx("no-last-para-padding", styles.noLeft)}
            forceRender={true}
          />
        ) : undefined}
      </div>
      <div className={clsx("sample-answer", "three-line-clamp", styles.cell)}>
        {sample ? (
          <RenderedText
            markdown={answer || ""}
            className={clsx("no-last-para-padding", styles.noLeft)}
            forceRender={true}
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
      <div
        className={clsx(
          "sample-retries",
          "text-size-small",
          "three-line-clamp",
          styles.cell,
          styles.centered,
        )}
      >
        {sample.retries && sample.retries > 0 ? sample.retries : undefined}
      </div>
      <div className={clsx("text-size-small", styles.cell, styles.score)}>
        {sample.error ? (
          <SampleErrorView message={sample.error} />
        ) : completed ? (
          scoreRendered
        ) : (
          <PulsingDots subtle={false} />
        )}
      </div>
    </div>
  );

  // If no sample URL available or not viewable, render as div
  if (!sampleUrl || !isViewable) {
    return <div className={styles.disabledRow}>{rowContent}</div>;
  }

  // VS code doesn't support navigating links
  if (isVscode()) {
    return (
      <div onClick={showSample} className={styles.sampleLink}>
        {rowContent}
      </div>
    );
  }

  // Render as a proper link
  return (
    <a href={sampleUrl} className={styles.sampleLink}>
      {rowContent}
    </a>
  );
};
