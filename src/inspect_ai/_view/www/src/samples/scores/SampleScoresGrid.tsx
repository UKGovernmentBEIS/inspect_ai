import clsx from "clsx";
import { FC } from "react";
import { SampleSummary } from "../../api/types";
import { EmptyPanel } from "../../components/EmptyPanel";
import { MetaDataGrid } from "../../metadata/MetaDataGrid";
import { useEvalDescriptor } from "../../state/hooks";
import { EvalSample } from "../../types/log";
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
          <>
            <div className={clsx("text-size-base", styles.cell)}>{scorer}</div>
            <div className={clsx(styles.cell, "text-size-base")}>{answer}</div>
            <div className={clsx(styles.cell, "text-size-base")}>
              <SampleScores
                sample={evalSample as any as SampleSummary}
                scorer={scorer}
              />
            </div>
            <div className={clsx("text-size-base", styles.cell)}>
              {explanation}
            </div>

            {Object.keys(metadata).length > 0 ? (
              <>
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
              </>
            ) : undefined}
          </>
        );
      })}
    </div>
  );
};
