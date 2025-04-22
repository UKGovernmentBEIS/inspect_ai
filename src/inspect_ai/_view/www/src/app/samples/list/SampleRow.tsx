import clsx from "clsx";
import { FC, ReactNode } from "react";
import { SampleSummary } from "../../../client/api/types";
import { MarkdownDiv } from "../../../components/MarkdownDiv";
import { PulsingDots } from "../../../components/PulsingDots";
import { useStore } from "../../../state/store";
import { arrayToString, inputString } from "../../../utils/format";
import { useSampleNavigation } from "../../routing/navigationHooks";
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
}) => {
  const streamSampleData = useStore(
    (state) => state.capabilities.streamSampleData,
  );
  const selectedSampleIndex = useStore(
    (state) => state.log.selectedSampleIndex,
  );
  // Determine if this sample can be viewed (completed or streaming)
  const isViewable = completed || streamSampleData;

  // Get sample navigation utilities
  const sampleNavigation = useSampleNavigation();

  // Use sample navigation hook to get sample URL
  const sampleUrl = isViewable
    ? sampleNavigation.getSampleUrl(sample.id, sample.epoch)
    : undefined;

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
        <MarkdownDiv markdown={inputString(sample.input).join(" ")} />
      </div>
      <div className={clsx("sample-target", "three-line-clamp", styles.cell)}>
        {sample?.target ? (
          <MarkdownDiv
            markdown={arrayToString(sample.target)}
            className={clsx("no-last-para-padding", styles.noLeft)}
          />
        ) : undefined}
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
          <PulsingDots />
        )}
      </div>
    </div>
  );

  // Render the row content either as a link or directly
  return (
    <div
      onClick={
        isViewable ? () => sampleNavigation.showSample(index) : undefined
      }
    >
      {rowContent}
    </div>
  );
};
