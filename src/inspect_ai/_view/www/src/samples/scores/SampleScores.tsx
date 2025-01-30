import { Fragment } from "react";
import { SampleSummary } from "../../api/types";
import { SamplesDescriptor } from "../descriptor/samplesDescriptor";

import styles from "./SampleScores.module.css";

interface SampleScoresProps {
  sample: SampleSummary;
  sampleDescriptor: SamplesDescriptor;
  scorer: string;
}

export const SampleScores: React.FC<SampleScoresProps> = ({
  sample,
  sampleDescriptor,
  scorer,
}) => {
  const scores = scorer
    ? sampleDescriptor.evalDescriptor
        .scorerDescriptor(sample, { scorer, name: scorer })
        .scores()
    : sampleDescriptor.selectedScorerDescriptor(sample).scores();

  if (scores.length === 1) {
    return scores[0].rendered();
  } else {
    const rows = scores.map((score) => {
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
