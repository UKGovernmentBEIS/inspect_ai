import { ScoreFilter, ScoreLabel } from "../Types.mjs";
import { EpochFilter } from "./sample-tools/EpochFilter";
import { SampleFilter } from "./sample-tools/sample-filter/SampleFilter";
import { SelectScorer } from "./sample-tools/SelectScorer";
import { SortFilter } from "./sample-tools/SortFilter";
import { SamplesDescriptor } from "./SamplesDescriptor.mjs";

interface SampleToolsProps {
  epoch: string;
  setEpoch: (epoch: string) => void;
  epochs: number;
  filter: ScoreFilter;
  setScoreFilter: (filter: ScoreFilter) => void;
  sort: string;
  setSort: (sort: string) => void;
  score: ScoreLabel;
  setScore: (score: ScoreLabel) => void;
  scores: ScoreLabel[];
  sampleDescriptor: SamplesDescriptor;
}

export const SampleTools: React.FC<SampleToolsProps> = ({
  epoch,
  setEpoch,
  epochs,
  filter,
  setScoreFilter,
  sort,
  setSort,
  score,
  setScore,
  scores,
  sampleDescriptor,
}) => {
  const tools = [];

  tools.push(
    <SampleFilter
      evalDescriptor={sampleDescriptor.evalDescriptor}
      filter={filter}
      setScoreFilter={setScoreFilter}
    />,
  );

  if (scores.length > 1) {
    tools.push(
      <SelectScorer scores={scores} score={score} setScore={setScore} />,
    );
  }

  if (epochs > 1) {
    tools.push(
      <EpochFilter epoch={epoch} setEpoch={setEpoch} epochs={epochs} />,
    );
  }

  tools.push(<SortFilter sort={sort} setSort={setSort} epochs={epochs} />);

  return tools;
};
