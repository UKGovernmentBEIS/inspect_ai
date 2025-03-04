import { FC } from "react";
import { Fragment } from "react/jsx-runtime";
import { SampleSummary } from "../api/types";
import { useLogStore, useScores } from "../state/logStore";
import { ScoreFilter, ScoreLabel } from "../types";
import { EpochFilter } from "./sample-tools/EpochFilter";
import { SampleFilter } from "./sample-tools/sample-filter/SampleFilter";
import { SelectScorer } from "./sample-tools/SelectScorer";
import { SortFilter } from "./sample-tools/SortFilter";

interface SampleToolsProps {
  samples: SampleSummary[];
}

export const SampleTools: FC<SampleToolsProps> = ({ samples }) => {
  const selectedLogSummary = useLogStore((state) => state.selectedLogSummary);

  const filter = useLogStore((state) => state.filter);
  const setFilter = useLogStore((state) => state.setFilter);

  const scores = useScores();
  const score = useLogStore((state) => state.score);
  const setScore = useLogStore((state) => state.setScore);
  const epoch = useLogStore((state) => state.epoch);
  const setEpoch = useLogStore((state) => state.setEpoch);
  const sort = useLogStore((state) => state.sort);
  const setSort = useLogStore((state) => state.setSort);

  const epochs = selectedLogSummary?.eval.config.epochs || 1;
  return (
    <Fragment>
      <SampleFilter
        samples={samples}
        scoreFilter={filter}
        setScoreFilter={(filter: ScoreFilter) => {
          setFilter(filter);
        }}
      />
      {scores?.length > 1 ? (
        <SelectScorer
          scores={scores}
          score={score}
          setScore={(score: ScoreLabel) => {
            setScore(score);
          }}
        />
      ) : undefined}
      {epochs > 1 ? (
        <EpochFilter
          epoch={epoch}
          setEpoch={(epoch: string) => {
            setEpoch(epoch);
          }}
          epochs={epochs}
        />
      ) : undefined}
      <SortFilter
        sort={sort}
        setSort={(sort: string) => {
          setSort(sort);
        }}
        epochs={epochs}
      />
    </Fragment>
  );
};
