import { FC } from "react";
import { Fragment } from "react/jsx-runtime";
import { SampleSummary } from "../api/types";
import { useScore, useScores } from "../state/hooks";
import { useStore } from "../state/store";
import { EpochFilter } from "./sample-tools/EpochFilter";
import { SampleFilter } from "./sample-tools/sample-filter/SampleFilter";
import { SelectScorer } from "./sample-tools/SelectScorer";
import { SortFilter } from "./sample-tools/SortFilter";

interface SampleToolsProps {
  samples: SampleSummary[];
}

export const SampleTools: FC<SampleToolsProps> = ({ samples }) => {
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);

  const filter = useStore((state) => state.log.filter);
  const setFilter = useStore((state) => state.logActions.setFilter);

  const scores = useScores();
  const score = useScore();
  const setScore = useStore((state) => state.logActions.setScore);
  const epoch = useStore((state) => state.log.epoch);
  const setEpoch = useStore((state) => state.logActions.setEpoch);
  const sort = useStore((state) => state.log.sort);
  const setSort = useStore((state) => state.logActions.setSort);

  const epochs = selectedLogSummary?.eval.config.epochs || 1;
  return (
    <Fragment>
      <SampleFilter
        samples={samples}
        scoreFilter={filter}
        setScoreFilter={setFilter}
      />
      {scores?.length > 1 ? (
        <SelectScorer scores={scores} score={score} setScore={setScore} />
      ) : undefined}
      {epochs > 1 ? (
        <EpochFilter epoch={epoch} setEpoch={setEpoch} epochs={epochs} />
      ) : undefined}
      <SortFilter sort={sort} setSort={setSort} epochs={epochs} />
    </Fragment>
  );
};

interface ScoreFilterToolsProps {}

export const ScoreFilterTools: FC<ScoreFilterToolsProps> = () => {
  const scores = useScores();
  const score = useScore();
  const setScore = useStore((state) => state.logActions.setScore);
  if (scores.length <= 1) {
    return undefined;
  }
  return <SelectScorer scores={scores} score={score} setScore={setScore} />;
};
