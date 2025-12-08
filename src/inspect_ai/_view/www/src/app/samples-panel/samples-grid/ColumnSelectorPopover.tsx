import { ColDef } from "ag-grid-community";
import { clsx } from "clsx";
import { FC, useMemo } from "react";
import { PopOver } from "../../../components/PopOver";
import { ApplicationIcons } from "../../appearance/icons";
import styles from "./ColumnSelectorPopover.module.css";
import { getFieldKey } from "./hooks";
import { SampleRow } from "./types";

interface ColumnSelectorPopoverProps {
  showing: boolean;
  setShowing: (showing: boolean) => void;
  columns: ColDef<SampleRow>[];
  onVisibilityChange: (visibility: Record<string, boolean>) => void;
  positionEl: HTMLElement | null;
  filteredFields?: string[];
}

export const ColumnSelectorPopover: FC<ColumnSelectorPopoverProps> = ({
  showing,
  setShowing,
  columns,
  onVisibilityChange,
  positionEl,
  filteredFields = [],
}) => {
  // Get current visibility directly from columns
  const currentVisibility = useMemo(
    () =>
      columns.reduce<Record<string, boolean>>(
        (acc, col) => ({ ...acc, [getFieldKey(col)]: !col.hide }),
        {},
      ),
    [columns],
  );

  const handleToggle = (field: string) => {
    onVisibilityChange({
      ...currentVisibility,
      [field]: !currentVisibility[field],
    });
  };

  // Group columns by category - merge optional into base for this dialog
  const columnGroups = useMemo(() => {
    return {
      base: columns.filter((col) => !getFieldKey(col).startsWith("score_")),
      scores: columns.filter((col) => getFieldKey(col).startsWith("score_")),
    };
  }, [columns]);

  const handleSelectAllBase = () => {
    onVisibilityChange({
      ...currentVisibility,
      ...Object.fromEntries(
        columnGroups.base.map((col) => [getFieldKey(col), true]),
      ),
    });
  };
  const handleDeselectAllBase = () => {
    onVisibilityChange({
      ...currentVisibility,
      ...Object.fromEntries(
        columnGroups.base.map((col) => [getFieldKey(col), false]),
      ),
    });
  };
  const handleSelectAllScores = () => {
    onVisibilityChange({
      ...currentVisibility,
      ...Object.fromEntries(
        columnGroups.scores.map((col) => [getFieldKey(col), true]),
      ),
    });
  };
  const handleDeselectAllScores = () => {
    onVisibilityChange({
      ...currentVisibility,
      ...Object.fromEntries(
        columnGroups.scores.map((col) => [getFieldKey(col), false]),
      ),
    });
  };

  const renderColumnCheckbox = (col: ColDef<SampleRow>) => {
    const field = getFieldKey(col);
    const hasFilter = filteredFields.includes(field);
    return (
      <div
        key={field}
        className={styles.checkboxWrapper}
        title={
          hasFilter
            ? "Unselecting will remove an active filter on this column"
            : undefined
        }
      >
        <label className={styles.label}>
          <input
            type="checkbox"
            checked={currentVisibility[field]}
            onChange={() => handleToggle(field)}
            className={styles.checkbox}
          />
          <span>{col.headerName || field}</span>
          {hasFilter && (
            <i className={`${ApplicationIcons.filter} ${styles.filterIcon}`} />
          )}
        </label>
      </div>
    );
  };

  return (
    <PopOver
      id="column-selector-popover"
      isOpen={showing}
      setIsOpen={setShowing}
      positionEl={positionEl}
      placement="bottom-start"
      showArrow={false}
      hoverDelay={-1}
      className={styles.popover}
    >
      <div className={clsx(styles.scrollableContainer, "text-size-small")}>
        <div className={clsx(styles.section)}>
          <div className={styles.headerRow}>
            <b>Base</b>
            <div className={clsx(styles.buttonContainer, "text-size-small")}>
              <a
                className={clsx(styles.button, "text-size-small")}
                onClick={handleSelectAllBase}
              >
                All
              </a>
              |
              <a
                className={clsx(styles.button)}
                onClick={handleDeselectAllBase}
              >
                None
              </a>
            </div>
          </div>
          <div className={styles.columnsLayout}>
            {columnGroups.base.map((col) => renderColumnCheckbox(col))}
          </div>
        </div>

        {columnGroups.scores.length > 0 && (
          <div>
            <div className={styles.headerRow}>
              <b>Scorers</b>
              <div className={styles.buttonContainer}>
                <a
                  className={clsx(styles.button)}
                  onClick={handleSelectAllScores}
                >
                  All
                </a>
                |
                <a
                  className={clsx(styles.button)}
                  onClick={handleDeselectAllScores}
                >
                  None
                </a>
              </div>
            </div>
            <div className={styles.columnsLayout}>
              {columnGroups.scores.map((col) => renderColumnCheckbox(col))}
            </div>
          </div>
        )}
      </div>
    </PopOver>
  );
};
