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
        className={clsx(
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary",
        )}
      >
        Metadata
      </div>

      {Object.keys(evalSample.scores || {}).map((scorer) => {
        const scorerDescriptor = evalDescriptor.scorerDescriptor(evalSample, {
          scorer,
          name: scorer,
        });
        const explanation =
          scorerDescriptor.explanation() || "(No Explanation)";
        const answer = scorerDescriptor.answer();
        const metadata = scorerDescriptor.metadata();

        return (
          <>
            <div className={clsx("text-size-base text-style-label")}>
              {scorer}
            </div>
            <div>{answer}</div>
            <div>
              <SampleScores
                sample={evalSample as any as SampleSummary}
                scorer={scorer}
              />
            </div>
            <div className={clsx("text-size-smaller")}>{explanation}</div>
            <div>
              <MetaDataGrid entries={metadata} />
            </div>
          </>
        );
      })}
    </div>
  );
};
