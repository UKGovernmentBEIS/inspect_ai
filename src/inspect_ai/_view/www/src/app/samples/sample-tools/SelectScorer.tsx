import clsx from "clsx";
import { ScoreLabel } from "../../../app/types";

import { ChangeEvent, FC, useCallback } from "react";
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
  const scorers = scores.reduce((accum, scorer) => {
    if (
      !accum.find((sc) => {
        return scorer.scorer === sc.scorer;
      })
    ) {
      accum.push(scorer);
    }
    return accum;
  }, [] as ScoreLabel[]);

  const handleSelectScore = useCallback(
    (index: number) => {
      setScore(scores[index]);
    },
    [setScore, scores],
  );

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
          selectedIndex={scoreIndex(scores, score)}
          setSelectedIndex={handleSelectScore}
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
          selectedIndex={scorerIndex(scorers, score)}
          setSelectedIndex={handleSelectScore}
        />
        {scorerScores.length > 1 ? (
          <ScoreSelector
            className={clsx(styles.secondSel)}
            scores={scorerScores}
            selectedIndex={scoreIndex(scorerScores, score)}
            setSelectedIndex={handleSelectScore}
          />
        ) : undefined}
      </div>
    );
  }
};

interface ScoreSelectorProps {
  scores: ScoreLabel[];
  selectedIndex: number;
  setSelectedIndex: (index: number) => void;
  className?: string | string[];
}

const ScoreSelector: FC<ScoreSelectorProps> = ({
  scores,
  selectedIndex,
  setSelectedIndex,
  className,
}) => {
  const handleChange = useCallback(
    (e: ChangeEvent<HTMLSelectElement>) => {
      const sel = e.target as HTMLSelectElement;
      setSelectedIndex(sel.selectedIndex);
    },
    [setSelectedIndex],
  );

  return (
    <select
      className={clsx(
        "form-select",
        "form-select-sm",
        "text-size-smaller",
        className,
      )}
      aria-label=".select-scorer-label"
      value={scores[selectedIndex].name}
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
  selectedIndex: number;
  setSelectedIndex: (index: number) => void;
}

const ScorerSelector: FC<ScorerSelectorProps> = ({
  scorers,
  selectedIndex,
  setSelectedIndex,
}) => {
  const handleChange = useCallback(
    (e: ChangeEvent<HTMLSelectElement>) => {
      const sel = e.target as HTMLSelectElement;
      setSelectedIndex(sel.selectedIndex);
    },
    [setSelectedIndex],
  );

  return (
    <select
      className={clsx("form-select", "form-select-sm", "text-size-smaller")}
      aria-label=".epoch-filter-label"
      value={scorers[selectedIndex].scorer}
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

const scoreIndex = (scores: ScoreLabel[], score?: ScoreLabel) =>
  scores.findIndex((sc) => {
    return score && sc.name === score.name && sc.scorer === score.scorer;
  });

const scorerIndex = (scores: ScoreLabel[], score?: ScoreLabel) =>
  scores.findIndex((sc) => {
    return score && sc.scorer === score.scorer;
  });
