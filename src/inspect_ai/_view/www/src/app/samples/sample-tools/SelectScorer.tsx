import clsx from "clsx";
import { ScoreLabel } from "../../../app/types";

import { ChangeEvent, FC, useCallback, useMemo } from "react";
import styles from "./SelectScorer.module.css";

interface SelectScorerProps {
  scores: ScoreLabel[];
  score?: ScoreLabel;
  setScore: (score: ScoreLabel) => void;
}

export const SelectScorer: FC<SelectScorerProps> = ({
  scores,
  score,
  setScore,
}) => {
  const scorers = useMemo(() => {
    return scores.reduce((accum, scorer) => {
      if (
        !accum.find((sc) => {
          return scorer.scorer === sc.scorer;
        })
      ) {
        accum.push(scorer);
      }
      return accum;
    }, [] as ScoreLabel[]);
  }, [scores]);

  if (scorers.length === 1) {
    // There is only a single scorer in play, just show the list of available scores
    return (
      <div className={styles.flex}>
        <span
          className={clsx(
            "select-scorer-label",
            "text-size-smaller",
            "text-style-label",
            "text-style-secondary",
            styles.label,
          )}
        >
          Score:
        </span>
        <ScoreSelector
          scores={scores}
          selectedScore={score}
          setSelectedScore={setScore}
        />
      </div>
    );
  } else {
    // selected scorer

    const scorerScores = scores.filter((sc) => {
      return score && sc.scorer === score.scorer;
    });

    // There are multiple scorers, so show a scorer selector and a r
    return (
      <div className={styles.flex}>
        <span
          className={clsx(
            "select-scorer-label",
            "text-size-smaller",
            "text-style-label",
            "text-style-secondary",
            styles.label,
            styles.secondLabel,
          )}
        >
          Scorer:
        </span>
        <ScorerSelector
          scorers={scorers}
          selectedScore={score}
          setSelectedScore={setScore}
        />
        {scorerScores.length > 1 ? (
          <ScoreSelector
            className={clsx(styles.secondSel)}
            scores={scorerScores}
            selectedScore={score}
            setSelectedScore={setScore}
          />
        ) : undefined}
      </div>
    );
  }
};

interface ScoreSelectorProps {
  scores: ScoreLabel[];
  selectedScore?: ScoreLabel;
  setSelectedScore: (score: ScoreLabel) => void;
  className?: string | string[];
}

const ScoreSelector: FC<ScoreSelectorProps> = ({
  scores,
  selectedScore,
  setSelectedScore,
  className,
}) => {
  const handleChange = useCallback(
    (e: ChangeEvent<HTMLSelectElement>) => {
      const sel = e.target as HTMLSelectElement;
      setSelectedScore(scores[sel.selectedIndex]);
    },
    [setSelectedScore, scores],
  );

  const index = scores.findIndex((sc) => {
    return (
      selectedScore &&
      sc.name === selectedScore.name &&
      sc.scorer === selectedScore.scorer
    );
  });

  return (
    <select
      className={clsx(
        "form-select",
        "form-select-sm",
        "text-size-smaller",
        className,
      )}
      aria-label=".select-scorer-label"
      value={scores[index].name}
      onChange={handleChange}
    >
      {scores.map((score) => {
        return (
          <option key={score.name} value={score.name}>
            {score.name}
          </option>
        );
      })}
    </select>
  );
};

interface ScorerSelectorProps {
  scorers: ScoreLabel[];
  selectedScore?: ScoreLabel;
  setSelectedScore: (score: ScoreLabel) => void;
}

const ScorerSelector: FC<ScorerSelectorProps> = ({
  scorers,
  selectedScore,
  setSelectedScore,
}) => {
  const handleChange = useCallback(
    (e: ChangeEvent<HTMLSelectElement>) => {
      const sel = e.target as HTMLSelectElement;
      setSelectedScore(scorers[sel.selectedIndex]);
    },
    [setSelectedScore, scorers],
  );

  const index = scorers.findIndex((sc) => {
    return selectedScore && sc.scorer === selectedScore.scorer;
  });

  return (
    <select
      className={clsx("form-select", "form-select-sm", "text-size-smaller")}
      aria-label=".epoch-filter-label"
      value={scorers[index].scorer}
      onChange={handleChange}
    >
      {scorers.map((scorer) => {
        return (
          <option key={scorer.scorer} value={scorer.scorer}>
            {scorer.scorer}
          </option>
        );
      })}
    </select>
  );
};
