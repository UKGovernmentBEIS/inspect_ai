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
  sample: SampleSummary;
  answer: string;
  completed: boolean;
  scoresRendered: ReactNode[];
  gridColumnsTemplate: string;
  height: number;
  selected: boolean;
  showSample: () => void;
  sampleUrl?: string;
}

const kMaxRowTextSize = 1024 * 5;

export const SampleRow: FC<SampleRowProps> = ({
  id,
  sample,
  answer,
  completed,
  scoresRendered,
  gridColumnsTemplate,
  height,
  selected,
  showSample,
  sampleUrl,
}) => {
  const streamSampleData = useStore(
    (state) => state.capabilities.streamSampleData,
  );

  // Determine if this sample can be viewed (completed or streaming)
  const isViewable = completed || streamSampleData;

  // This is used to screen out content when the sample dialog is open
  // this allows the sample list to retain precise state (since it remains loaded)
  // while not causing text content to be present in the DOM
  const showingSampleDialog = useStore((state) => state.app.dialogs.sample);

  if (
    !completed &&
    scoresRendered.length === 0 &&
    Object.keys(sample.scores || {}).length === 0
  ) {
    scoresRendered = [null];
  }
  const scoreColumnContent = scoresRendered.map((scoreRendered, i) => {
    if (!showingSampleDialog && sample.error) {
      return <SampleErrorView message={sample.error} />;
    } else if (completed) {
      return scoreRendered;
    } else if (i === scoresRendered.length - 1) {
      return <PulsingDots subtle={false} />;
    } else {
      return undefined;
    }
  });

  const rowContent = (
    <div
      id={`sample-${id}`}
      className={clsx(
        styles.grid,
        "text-size-base",
        selected ? styles.selected : undefined,
        !isViewable && !sampleUrl ? styles.disabled : undefined,
      )}
      style={{
        height: `${height}px`,
        gridTemplateRows: `${height - 28}px`,
        gridTemplateColumns: gridColumnsTemplate,
      }}
    >
      <div className={clsx("sample-id", "three-line-clamp", styles.cell)}>
        {!showingSampleDialog ? sample.id : undefined}
      </div>
      <div
        className={clsx(
          "sample-input",
          "three-line-clamp",
          styles.cell,
          styles.wrapAnywhere,
        )}
      >
        {!showingSampleDialog ? (
          <RenderedText
            markdown={inputString(sample.input)
              .join(" ")
              .slice(0, kMaxRowTextSize)}
            forceRender={true}
            omitMedia={true}
          />
        ) : undefined}
      </div>
      <div className={clsx("sample-target", "three-line-clamp", styles.cell)}>
        {sample?.target && !showingSampleDialog ? (
          <RenderedText
            markdown={arrayToString(sample.target).slice(0, kMaxRowTextSize)}
            className={clsx("no-last-para-padding", styles.noLeft)}
            forceRender={true}
            omitMedia={true}
          />
        ) : undefined}
      </div>
      <div className={clsx("sample-answer", "three-line-clamp", styles.cell)}>
        {sample && !showingSampleDialog ? (
          <RenderedText
            markdown={(answer || "").slice(0, kMaxRowTextSize)}
            className={clsx("no-last-para-padding", styles.noLeft)}
            forceRender={true}
            omitMedia={true}
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
        {!showingSampleDialog ? sample.limit : undefined}
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
        {!showingSampleDialog && sample.retries && sample.retries > 0
          ? sample.retries
          : undefined}
      </div>
      {scoreColumnContent.map((scoreColumnContent, i) => (
        <div
          key={`score-${i}`}
          className={clsx("text-size-small", styles.cell, styles.score)}
        >
          {scoreColumnContent}
        </div>
      ))}
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
