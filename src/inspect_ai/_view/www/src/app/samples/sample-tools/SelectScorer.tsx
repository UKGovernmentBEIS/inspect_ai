import clsx from "clsx";
import { ScoreLabel } from "../../../app/types";

import { FC, useCallback, useMemo, useRef, useState } from "react";
import { PopOver } from "../../../components/PopOver";
import styles from "./SelectScorer.module.css";

interface SelectScorerProps {
  scores: ScoreLabel[];
  selectedScores?: ScoreLabel[];
  setSelectedScores?: (scores: ScoreLabel[]) => void;
}

export const SelectScorer: FC<SelectScorerProps> = ({
  scores,
  selectedScores,
  setSelectedScores,
}) => {
  const [showing, setShowing] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const selectedKeys = useMemo(() => {
    return new Set(selectedScores?.map((s) => `${s.scorer}.${s.name}`));
  }, [selectedScores]);

  const selectedCount = selectedKeys.size;
  const buttonText =
    selectedCount === 1
      ? selectedScores?.[0]?.name || "Score"
      : `${selectedCount} Scores`;

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
      <button
        ref={buttonRef}
        className={clsx(
          "btn",
          "btn-sm",
          "btn-outline-secondary",
          styles.button,
        )}
        onClick={() => setShowing(!showing)}
      >
        {buttonText}
      </button>
      <PopOver
        id="score-selector-popover"
        positionEl={buttonRef.current}
        isOpen={showing}
        setIsOpen={setShowing}
        placement="bottom-start"
        hoverDelay={-1}
      >
        <ScoreCheckboxes
          scores={scores}
          selectedKeys={selectedKeys}
          setSelectedScores={setSelectedScores}
        />
      </PopOver>
    </div>
  );
};

interface ScoreCheckboxesProps {
  scores: ScoreLabel[];
  selectedKeys?: Set<string>;
  setSelectedScores?: (scores: ScoreLabel[]) => void;
}

const ScoreCheckboxes: FC<ScoreCheckboxesProps> = ({
  scores,
  selectedKeys,
  setSelectedScores,
}) => {
  const handleToggle = useCallback(
    (scoreToToggle: ScoreLabel, currentlyChecked: boolean) => {
      if (!setSelectedScores) return;

      const key = `${scoreToToggle.scorer}.${scoreToToggle.name}`;
      const current = new Set(selectedKeys);

      if (currentlyChecked) {
        current.delete(key);
      } else {
        current.add(key);
      }

      const next = scores.filter((s) => current.has(`${s.scorer}.${s.name}`));
      const fallback = next.length > 0 ? next : [scores[0]];
      setSelectedScores(fallback);
    },
    [setSelectedScores, scores, selectedKeys],
  );

  return (
    <div className={clsx(styles.grid, "text-size-smaller")}>
      {scores.map((sc) => {
        const key = `${sc.scorer}.${sc.name}`;
        const isChecked = selectedKeys ? selectedKeys.has(key) : false;
        return (
          <div
            key={key}
            className={clsx(styles.row)}
            onClick={() => handleToggle(sc, isChecked)}
          >
            <input
              type="checkbox"
              checked={isChecked}
              onChange={(e) => {
                e.stopPropagation();
                handleToggle(sc, isChecked);
              }}
            />
            {sc.name}
          </div>
        );
      })}
    </div>
  );
};
