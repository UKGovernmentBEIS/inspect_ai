import clsx from "clsx";
import { MarkdownDiv } from "../components/MarkdownDiv";
import { EvalSample } from "../types/log";
import { arrayToString, inputString } from "../utils/format";
import { SamplesDescriptor } from "./descriptor/samplesDescriptor";
import { FlatSampleError } from "./error/FlatSampleErrorView";

import { ReactNode } from "react";
import styles from "./SampleSummaryView.module.css";

interface SampleSummaryViewProps {
  parent_id: string;
  sample: EvalSample;
  sampleDescriptor: SamplesDescriptor;
}

interface SummaryColumn {
  label: string;
  value: string | ReactNode;
  size: string;
  center?: boolean;
  clamp?: boolean;
}

/**
 * Component to display a sample with relevant context and visibility control.
 */
export const SampleSummaryView: React.FC<SampleSummaryViewProps> = ({
  parent_id,
  sample,
  sampleDescriptor,
}) => {
  const input =
    sampleDescriptor?.messageShape.normalized.input > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.normalized.input)
      : 0;
  const target =
    sampleDescriptor?.messageShape.normalized.target > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.normalized.target)
      : 0;
  const answer =
    sampleDescriptor?.messageShape.normalized.answer > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.normalized.answer)
      : 0;
  const limitSize =
    sampleDescriptor?.messageShape.normalized.limit > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.normalized.limit)
      : 0;
  const idSize = Math.max(
    2,
    Math.min(10, sampleDescriptor?.messageShape.raw.id),
  );

  const scoreInput = inputString(sample.input);
  if (sample.choices && sample.choices.length > 0) {
    scoreInput.push("");
    scoreInput.push(
      ...sample.choices.map((choice, index) => {
        return `${String.fromCharCode(65 + index)}) ${choice}`;
      }),
    );
  }

  // The columns for the sample
  const columns: SummaryColumn[] = [];
  columns.push({
    label: "Id",
    value: sample.id,
    size: `${idSize}em`,
  });

  columns.push({
    label: "Input",
    value: scoreInput,
    size: `${input}fr`,
    clamp: true,
  });

  if (sample.target) {
    columns.push({
      label: "Target",
      value: (
        <MarkdownDiv
          markdown={arrayToString(arrayToString(sample?.target || "none"))}
          className={clsx("no-last-para-padding", styles.target)}
        />
      ),
      size: `${target}fr`,
      clamp: true,
    });
  }

  const fullAnswer =
    sample && sampleDescriptor
      ? sampleDescriptor.selectedScorerDescriptor(sample).answer()
      : undefined;
  if (fullAnswer) {
    columns.push({
      label: "Answer",
      value: sample ? (
        <MarkdownDiv
          markdown={fullAnswer}
          className={clsx("no-last-para-padding", styles.answer)}
        />
      ) : (
        ""
      ),
      size: `${answer}fr`,
      clamp: true,
    });
  }

  if (sample?.limit && limitSize > 0) {
    columns.push({
      label: "Limit",
      value: sample.limit.type,
      size: `${limitSize}fr`,
      center: true,
    });
  }

  columns.push({
    label: "Score",
    value: sample.error ? (
      <FlatSampleError message={sample.error.message} />
    ) : (
      // TODO: Cleanup once the PR lands which makes sample / sample summary share common interface
      sampleDescriptor?.selectedScore(sample)?.render() || ""
    ),
    size: "minmax(2em, auto)",
    center: true,
  });

  return (
    <div
      id={`sample-heading-${parent_id}`}
      className={clsx(styles.grid, "text-size-base")}
      style={{
        gridTemplateColumns: `${columns
          .map((col) => {
            return col.size;
          })
          .join(" ")}`,
      }}
    >
      {columns.map((col, idx) => {
        return (
          <div
            key={`sample-summ-lbl-${idx}`}
            className={clsx(
              "text-style-label",
              "text-style-secondary",
              "text-size-base",
              col.center ? styles.centerLabel : undefined,
            )}
          >
            {col.label}
          </div>
        );
      })}
      {columns.map((col, idx) => {
        return (
          <div
            key={`sample-summ-val-${idx}`}
            className={clsx(
              styles.wrap,
              col.clamp ? "three-line-clamp" : undefined,
              col.center ? styles.centerLabel : undefined,
            )}
          >
            {col.value}
          </div>
        );
      })}
    </div>
  );
};
