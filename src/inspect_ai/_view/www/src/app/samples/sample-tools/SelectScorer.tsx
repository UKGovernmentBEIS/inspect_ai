import clsx from "clsx";
import { ScoreLabel } from "../../../app/types";

import { FC, useCallback, useMemo, useRef, useState } from "react";
import { PopOver } from "../../../components/PopOver";
import { ToolButton } from "../../../components/ToolButton";
import { ApplicationIcons } from "../../appearance/icons";
import styles from "./SelectScorer.module.css";

interface SelectScorerProps {
  scores: ScoreLabel[];
  selectedScores?: ScoreLabel[];
  setSelectedScores: (scores: ScoreLabel[]) => void;
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
  const label =
    selectedCount === 0
      ? "Score"
      : selectedCount === 1
        ? selectedScores?.[0]?.name || "Score"
        : `${selectedCount} Scores`;

  const allScoresSelected = selectedCount === scores.length;

  return (
    <div style={{ display: "flex" }}>
      <span
        className={clsx(
          "sample-filter-label",
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary",
          styles.label,
        )}
      >
        Scorers:
      </span>
      <ToolButton
        label={label}
        icon={ApplicationIcons.metrics}
        onClick={() => setShowing(!showing)}
        ref={buttonRef}
        className={clsx(styles.bodyColorButton)}
      />
      <PopOver
        id="score-selector-popover"
        positionEl={buttonRef.current}
        isOpen={showing}
        setIsOpen={setShowing}
        placement="bottom-start"
        hoverDelay={-1}
        styles={{
          padding: "3px 5px",
        }}
      >
        <div className={clsx(styles.links, "text-size-smaller")}>
          <a
            className={clsx(
              styles.link,
              !allScoresSelected ? styles.selected : undefined,
            )}
            onClick={() => {
              if (scores.length > 0) {
                setSelectedScores([scores[0]]);
              }
            }}
          >
            Default
          </a>
          |
          <a
            className={clsx(
              styles.link,
              allScoresSelected ? styles.selected : undefined,
            )}
            onClick={() => {
              setSelectedScores(scores);
            }}
          >
            All
          </a>
        </div>
        <div className={styles.container}>
          <ScoreCheckboxes
            scores={scores}
            selectedKeys={selectedKeys}
            setSelectedScores={setSelectedScores}
          />
        </div>
      </PopOver>
    </div>
  );
};

interface ScoreCheckboxesProps {
  scores: ScoreLabel[];
  selectedKeys?: Set<string>;
  setSelectedScores: (scores: ScoreLabel[]) => void;
}

const ScoreCheckboxes: FC<ScoreCheckboxesProps> = ({
  scores,
  selectedKeys,
  setSelectedScores,
}) => {
  const handleToggle = useCallback(
    (scoreToToggle: ScoreLabel, currentlyChecked: boolean) => {
      const key = `${scoreToToggle.scorer}.${scoreToToggle.name}`;
      const current = new Set(selectedKeys);

      if (currentlyChecked) {
        current.delete(key);
      } else {
        current.add(key);
      }

      const next = scores.filter((s) => current.has(`${s.scorer}.${s.name}`));
      setSelectedScores(next);
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
