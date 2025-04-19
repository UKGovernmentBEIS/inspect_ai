import clsx from "clsx";
import { FC, Fragment } from "react";
import { EvalSample } from "../../../@types/log";
import { SampleSummary } from "../../../client/api/types";
import { EmptyPanel } from "../../../components/EmptyPanel";
import { MarkdownDiv } from "../../../components/MarkdownDiv";
import { useEvalDescriptor } from "../../../state/hooks";
import { MetaDataGrid } from "../../content/MetaDataGrid";
import { SampleScores } from "./SampleScores";
import styles from "./SampleScoresGrid.module.css";

interface SampleScoresGridProps {
  evalSample: EvalSample;
  className?: string | string[];
}

export const SampleScoresGrid: FC<SampleScoresGridProps> = ({
  evalSample,
  className,
}) => {
  const evalDescriptor = useEvalDescriptor();
  if (!evalDescriptor) {
    return <EmptyPanel>No Sample Selected</EmptyPanel>;
  }
  return (
    <div className={clsx(className, styles.container)}>
      <div
        className={clsx(
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary",
        )}
      >
        Scorer
      </div>
      <div
        className={clsx(
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary",
        )}
      >
        Answer
      </div>
      <div
        className={clsx(
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary",
        )}
      >
        Score
      </div>
      <div
        className={clsx(
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary",
        )}
      >
        Explanation
      </div>
      <div
        className={clsx(styles.separator, styles.fullWidth, styles.headerSep)}
      ></div>

      {Object.keys(evalSample.scores || {}).map((scorer) => {
        if (!evalSample.scores) {
          return undefined;
        }
        const scoreData = evalSample.scores[scorer];
        const explanation = scoreData.explanation || "(No Explanation)";
        const answer = scoreData.answer;
        let metadata = scoreData.metadata || {};

        return (
          <Fragment key={`${scorer}-row`}>
            <div className={clsx("text-size-base", styles.cell)}>{scorer}</div>
            <div className={clsx(styles.cell, "text-size-base")}>{answer}</div>
            <div className={clsx(styles.cell, "text-size-base")}>
              <SampleScores
                sample={evalSample as any as SampleSummary}
                scorer={scorer}
              />
            </div>
            <div className={clsx("text-size-base", styles.cell)}>
              <MarkdownDiv markdown={explanation} />
            </div>

            {Object.keys(metadata).length > 0 ? (
              <Fragment key={`${scorer}-metadata`}>
                <div
                  className={clsx(
                    "text-size-smaller",
                    "text-style-label",
                    "text-style-secondary",
                    styles.fullWidth,
                  )}
                >
                  Metadata
                </div>
                <div className={clsx(styles.fullWidth)}>
                  <MetaDataGrid entries={metadata} />
                </div>
                <div
                  className={clsx(
                    styles.separator,
                    styles.separatorPadded,
                    styles.fullWidth,
                  )}
                ></div>
              </Fragment>
            ) : undefined}
          </Fragment>
        );
      })}
    </div>
  );
};
