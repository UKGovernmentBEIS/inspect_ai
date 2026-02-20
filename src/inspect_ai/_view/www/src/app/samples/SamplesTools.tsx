import { FC } from "react";
import { Fragment } from "react/jsx-runtime";
import { useScores, useSelectedScores } from "../../state/hooks";
import { useStore } from "../../state/store";
import { SampleFilter } from "./sample-tools/sample-filter/SampleFilter";
import { SelectScorer } from "./sample-tools/SelectScorer";

interface SampleToolsProps {}

export const SampleTools: FC<SampleToolsProps> = () => {
  const scores = useScores();
  const selectedScores = useSelectedScores();
  const setSelectedScores = useStore(
    (state) => state.logActions.setSelectedScores,
  );

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
