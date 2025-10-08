import { FC } from "react";
import { Fragment } from "react/jsx-runtime";
import { useScores, useSelectedScores } from "../../state/hooks";
import { useStore } from "../../state/store";
import { EpochFilter } from "./sample-tools/EpochFilter";
import { SampleFilter } from "./sample-tools/sample-filter/SampleFilter";
import { SelectScorer } from "./sample-tools/SelectScorer";
import { SortFilter } from "./sample-tools/SortFilter";

interface SampleToolsProps {}

export const SampleTools: FC<SampleToolsProps> = () => {
  const selectedLogDetails = useStore((state) => state.log.selectedLogDetails);

  const scores = useScores();
  const selectedScores = useSelectedScores();
  const setSelectedScores = useStore(
    (state) => state.logActions.setSelectedScores,
  );
  const epoch = useStore((state) => state.log.epoch);
  const setEpoch = useStore((state) => state.logActions.setEpoch);
  const sort = useStore((state) => state.log.sort);
  const setSort = useStore((state) => state.logActions.setSort);

  const epochs = selectedLogDetails?.eval.config.epochs || 1;
  return (
    <Fragment>
      <SampleFilter />
      {scores?.length > 1 ? (
        <SelectScorer
          scores={scores}
          selectedScores={selectedScores}
          setSelectedScores={setSelectedScores}
        />
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
  const selectedScores = useSelectedScores();
  const setSelectedScores = useStore(
    (state) => state.logActions.setSelectedScores,
  );
  if (scores.length <= 1) {
    return undefined;
  }
  return (
    <SelectScorer
      scores={scores}
      selectedScores={selectedScores}
      setSelectedScores={setSelectedScores}
    />
  );
};
