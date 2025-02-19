import { Fragment } from "react/jsx-runtime";
import { ScoreFilter, ScoreLabel } from "../types";
import { SamplesDescriptor } from "./descriptor/samplesDescriptor";
import { EpochFilter } from "./sample-tools/EpochFilter";
import { SampleFilter } from "./sample-tools/sample-filter/SampleFilter";
import { SelectScorer } from "./sample-tools/SelectScorer";
import { SortFilter } from "./sample-tools/SortFilter";

interface SampleToolsProps {
  epoch: string;
  setEpoch: (epoch: string) => void;
  epochs: number;
  scoreFilter: ScoreFilter;
  setScoreFilter: (filter: ScoreFilter) => void;
  sort: string;
  setSort: (sort: string) => void;
  score?: ScoreLabel;
  setScore: (score: ScoreLabel) => void;
  scores: ScoreLabel[];
  sampleDescriptor: SamplesDescriptor;
}

export const SampleTools: React.FC<SampleToolsProps> = ({
  epoch,
  setEpoch,
  epochs,
  scoreFilter,
  setScoreFilter,
  sort,
  setSort,
  score,
  setScore,
  scores,
  sampleDescriptor,
}) => {
  return (
    <Fragment>
      <SampleFilter
        evalDescriptor={sampleDescriptor.evalDescriptor}
        scoreFilter={scoreFilter}
        setScoreFilter={setScoreFilter}
      />
      {scores.length > 1 ? (
        <SelectScorer scores={scores} score={score} setScore={setScore} />
      ) : undefined}
      {epochs > 1 ? (
        <EpochFilter epoch={epoch} setEpoch={setEpoch} epochs={epochs} />
      ) : undefined}
      <SortFilter sort={sort} setSort={setSort} epochs={epochs} />
    </Fragment>
  );
};
