import { FC } from "react";
import { SampleSummary } from "../../../client/api/types";

import { getScoreDescriptorForValues } from "../descriptor/score/ScoreDescriptor";

interface SampleScoresProps {
  sample: SampleSummary;
  scorer: string;
}

export const SampleScores: FC<SampleScoresProps> = ({ sample, scorer }) => {
  const scoreData = sample.scores?.[scorer];
  if (!scoreData) {
    return undefined;
  }

  const scorerDescriptor = getScoreDescriptorForValues(
    [scoreData.value],
    [typeof scoreData.value],
  );
  return scorerDescriptor?.render(scoreData.value);
};
