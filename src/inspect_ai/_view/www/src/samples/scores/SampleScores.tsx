import { FC, Fragment } from "react";
import { SampleSummary } from "../../api/types";

import { useSampleDescriptor } from "../../state/logStore";
import styles from "./SampleScores.module.css";

interface SampleScoresProps {
  sample: SampleSummary;
  scorer: string;
}

export const SampleScores: FC<SampleScoresProps> = ({ sample, scorer }) => {
  const samplesDescriptor = useSampleDescriptor();
  const scores = scorer
    ? samplesDescriptor?.evalDescriptor
        .scorerDescriptor(sample, { scorer, name: scorer })
        .scores()
    : samplesDescriptor?.selectedScorerDescriptor(sample)?.scores();

  if (scores?.length === 1) {
    return scores[0].rendered();
  } else {
    const rows = scores?.map((score) => {
      return (
        <Fragment>
          <div style={{ opacity: "0.7" }}>{score.name}</div>
          <div>{score.rendered()}</div>
        </Fragment>
      );
    });
    return <div className={styles.grid}>{rows}</div>;
  }
};
