import clsx from "clsx";
import {
  EvalSample,
  ProvenanceData,
  Target,
  TotalTime,
  WorkingTime,
} from "../../@types/log";
import { arrayToString, formatTime, inputString } from "../../utils/format";
import { truncateMarkdown } from "../../utils/markdown";
import { FlatSampleError } from "./error/FlatSampleErrorView";

import { FC, ReactNode } from "react";
import { SampleSummary } from "../../client/api/types";
import { useSampleDescriptor, useSelectedScores } from "../../state/hooks";
import { RenderedText } from "../content/RenderedText";
import styles from "./SampleSummaryView.module.css";
import { SamplesDescriptor } from "./descriptor/samplesDescriptor";

const kMaxCellTextLength = 256;
interface SampleSummaryViewProps {
  parent_id: string;
  sample: SampleSummary | EvalSample;
}

interface SummaryColumn {
  label: string;
  value: string | ReactNode;
  size: string;
  center?: boolean;
  clamp?: boolean;
  title?: string;
}

interface SampleFields {
  id: string | number;
  input: string[];
  target: Target;
  answer?: string;
  limit?: string;
  retries?: number;
  working_time?: WorkingTime;
  total_time?: TotalTime;
  error?: string;
}

function isEvalSample(
  sample: SampleSummary | EvalSample,
): sample is EvalSample {
  return "store" in sample;
}

const resolveSample = (
  sample: SampleSummary | EvalSample,
  sampleDescriptor: SamplesDescriptor,
): SampleFields => {
  const input = inputString(sample.input);
  if (isEvalSample(sample) && sample.choices && sample.choices.length > 0) {
    input.push("");
    input.push(
      ...sample.choices.map((choice, index) => {
        return `${String.fromCharCode(65 + index)}) ${choice}`;
      }),
    );
  }

  const target = sample.target;
  const answer =
    sample && sampleDescriptor
      ? sampleDescriptor.selectedScorerDescriptor(sample)?.answer()
      : undefined;
  const limit = isEvalSample(sample) ? sample.limit?.type : undefined;
  const working_time = isEvalSample(sample) ? sample.working_time : undefined;
  const total_time = isEvalSample(sample) ? sample.total_time : undefined;
  const error = isEvalSample(sample) ? sample.error?.message : undefined;
  const retries = isEvalSample(sample)
    ? sample.error_retries?.length
    : sample.retries;

  return {
    id: sample.id,
    input,
    target,
    answer,
    limit,
    retries,
    working_time,
    total_time,
    error,
  };
};

/**
 * Component to display a sample with relevant context and visibility control.
 */
export const SampleSummaryView: FC<SampleSummaryViewProps> = ({
  parent_id,
  sample,
}) => {
  const sampleDescriptor = useSampleDescriptor();
  const selectedScores = useSelectedScores();
  if (!sampleDescriptor) {
    return undefined;
  }
  const fields = resolveSample(sample, sampleDescriptor);

  const limitSize =
    sampleDescriptor?.messageShape.normalized.limit > 0
      ? Math.max(0.15, sampleDescriptor.messageShape.normalized.limit)
      : 0;
  const retrySize =
    sampleDescriptor?.messageShape.normalized.retries > 0 ? 6 : 0;
  const idSize = Math.max(
    2,
    Math.min(10, sampleDescriptor?.messageShape.raw.id),
  );

  // The columns for the sample
  const columns: SummaryColumn[] = [];
  columns.push({
    label: "Id",
    value: fields.id,
    size: `${idSize}em`,
  });

  columns.push({
    label: "Input",
    value: (
      <RenderedText
        markdown={truncateMarkdown(fields.input.join(" "), kMaxCellTextLength)}
      />
    ),
    size: `minmax(auto, 5fr)`,
  });

  if (fields.target) {
    columns.push({
      label: "Target",
      value: (
        <RenderedText
          markdown={truncateMarkdown(
            arrayToString(fields?.target || "none"),
            kMaxCellTextLength,
          )}
          className={clsx("no-last-para-padding", styles.target)}
        />
      ),
      size: `minmax(auto, 3fr)`,
      clamp: true,
    });
  }

  if (fields.answer) {
    columns.push({
      label: "Answer",
      value: sample ? (
        <RenderedText
          markdown={truncateMarkdown(fields.answer || "", kMaxCellTextLength)}
          className={clsx("no-last-para-padding", styles.answer)}
        />
      ) : (
        ""
      ),
      size: `minmax(auto, 5fr)`,
      clamp: true,
    });
  }

  const toolTip = (working_time?: WorkingTime) => {
    if (working_time === undefined || working_time === null) {
      return undefined;
    }
    return `Working time: ${formatTime(working_time)}`;
  };

  if (fields.total_time) {
    columns.push({
      label: "Time",
      value: formatTime(fields.total_time),
      size: `fit-content(10rem)`,
      center: true,
      title: toolTip(fields.working_time),
    });
  }

  if (fields?.limit && limitSize > 0) {
    columns.push({
      label: "Limit",
      value: fields.limit,
      size: `fit-content(10rem)`,
      center: true,
    });
  }

  if (fields?.retries && retrySize > 0) {
    columns.push({
      label: "Retries",
      value: fields.retries,
      size: `fit-content(${retrySize}rem)`,
      center: true,
    });
  }

  if (selectedScores && selectedScores.length > 0) {
    selectedScores.forEach((scoreLabel) => {
      columns.push({
        label: selectedScores.length === 1 ? "Score" : scoreLabel.name,
        value: fields.error ? (
          <FlatSampleError message={fields.error} />
        ) : (
          sampleDescriptor?.evalDescriptor
            .score(sample, scoreLabel)
            ?.render() || ""
        ),
        size: "fit-content(15em)",
        center: true,
      });
    });
  } else {
    columns.push({
      label: "Score",
      value: fields.error ? <FlatSampleError message={fields.error} /> : "",
      size: "fit-content(15em)",
      center: true,
    });
  }

  // Check if sample is invalidated (only available on full EvalSample)
  const invalidation: ProvenanceData | null | undefined = isEvalSample(sample)
    ? sample.invalidation
    : undefined;

  return (
    <div id={`sample-heading-${parent_id}`}>
      <div
        className={clsx(styles.grid, "text-size-base")}
        style={{
          gridTemplateColumns: `${invalidation ? "auto " : ""}${columns
            .map((col) => {
              return col.size;
            })
            .join(" ")}`,
        }}
      >
        {invalidation && (
          <div
            className={clsx(
              "text-style-label",
              "text-style-secondary",
              "text-size-smallest",
            )}
            data-unsearchable={true}
          />
        )}
        {columns.map((col, idx) => {
          return (
            <div
              key={`sample-summ-lbl-${idx}`}
              className={clsx(
                "text-style-label",
                "text-style-secondary",
                "text-size-smallest",
                col.title ? styles.titled : undefined,
                col.center ? styles.centerLabel : undefined,
              )}
              title={col.title}
              data-unsearchable={true}
            >
              {col.label}
            </div>
          );
        })}
        {invalidation && <InvalidationChip invalidation={invalidation} />}
        {columns.map((col, idx) => {
          return (
            <div
              key={`sample-summ-val-${idx}`}
              className={clsx(
                styles.value,
                styles.wrap,
                col.clamp ? "three-line-clamp" : undefined,
                col.center ? styles.centerValue : undefined,
              )}
              data-unsearchable={true}
            >
              {col.value}
            </div>
          );
        })}
      </div>
    </div>
  );
};

/**
 * Chip component to display invalidation status inline in the header.
 */
const InvalidationChip: FC<{ invalidation: ProvenanceData }> = ({
  invalidation,
}) => {
  const formatTimestamp = (timestamp: string) => {
    try {
      return new Date(timestamp).toLocaleString();
    } catch {
      return timestamp;
    }
  };

  const tooltipParts = [];
  if (invalidation.author) {
    tooltipParts.push(`By: ${invalidation.author}`);
  }
  if (invalidation.timestamp) {
    tooltipParts.push(`On: ${formatTimestamp(invalidation.timestamp)}`);
  }
  if (invalidation.reason) {
    tooltipParts.push(`Reason: ${invalidation.reason}`);
  }

  return (
    <div
      className={styles.invalidationChip}
      title={tooltipParts.join("\n")}
    >
      <span className={styles.invalidationChipIcon}>⚠</span>
      <span>Invalidated</span>
    </div>
  );
};
