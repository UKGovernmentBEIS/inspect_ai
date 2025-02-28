import { FC } from "react";
import { Fragment } from "react/jsx-runtime";
import { SampleSummary } from "../api/types";
import { useLogContext } from "../contexts/LogContext";
import { ScoreFilter, ScoreLabel } from "../types";
import { EpochFilter } from "./sample-tools/EpochFilter";
import { SampleFilter } from "./sample-tools/sample-filter/SampleFilter";
import { SelectScorer } from "./sample-tools/SelectScorer";
import { SortFilter } from "./sample-tools/SortFilter";

interface SampleToolsProps {
  samples: SampleSummary[];
}

export const SampleTools: FC<SampleToolsProps> = ({ samples }) => {
  const logContext = useLogContext();
  const epochs = logContext.state.selectedLogSummary?.eval.config.epochs || 1;
  return (
    <Fragment>
      <SampleFilter
        samples={samples}
        scoreFilter={logContext.state.filter}
        setScoreFilter={(filter: ScoreFilter) => {
          logContext.dispatch({ type: "SET_FILTER", payload: filter });
        }}
      />
      {logContext.scores.length > 1 ? (
        <SelectScorer
          scores={logContext.scores}
          score={logContext.state.score}
          setScore={(score: ScoreLabel) => {
            logContext.dispatch({ type: "SET_SCORE", payload: score });
          }}
        />
      ) : undefined}
      {epochs > 1 ? (
        <EpochFilter
          epoch={logContext.state.epoch}
          setEpoch={(epoch: string) => {
            logContext.dispatch({ type: "SET_EPOCH", payload: epoch });
          }}
          epochs={epochs}
        />
      ) : undefined}
      <SortFilter
        sort={logContext.state.sort}
        setSort={(sort: string) => {
          logContext.dispatch({ type: "SET_SORT", payload: sort });
        }}
        epochs={epochs}
      />
    </Fragment>
  );
};
