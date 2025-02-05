import clsx from "clsx";
import { SampleSummary } from "../../api/types";
import { MarkdownDiv } from "../../components/MarkdownDiv";
import { arrayToString, inputString } from "../../utils/format";
import { SamplesDescriptor } from "../descriptor/samplesDescriptor";
import { SampleErrorView } from "../error/SampleErrorView";
import styles from "./SampleRow.module.css";

interface SampleRowProps {
  id: string;
  index: number;
  sample: SampleSummary;
  sampleDescriptor: SamplesDescriptor;
  gridColumnsTemplate: string;
  height: number;
  selected: boolean;
  showSample: (index: number) => void;
}

export const SampleRow: React.FC<SampleRowProps> = ({
  id,
  index,
  sample,
  sampleDescriptor,
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
            markdown={sampleDescriptor
              ?.selectedScorerDescriptor(sample)
              .answer()}
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
          sampleDescriptor?.selectedScore(sample)?.render()
        )}
      </div>
    </div>
  );
};
