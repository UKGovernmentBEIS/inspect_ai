import { ColDef } from "ag-grid-community";
import { FC, useMemo, useState, useEffect, useCallback } from "react";
import { Modal } from "../../../components/Modal";
import { getFieldKey } from "./hooks";
import { SampleRow } from "./types";
import styles from "./ColumnSelector.module.css";

interface ColumnSelectorProps {
  showing: boolean;
  setShowing: (showing: boolean) => void;
  columns: ColDef<SampleRow>[];
  onVisibilityChange: (visibility: Record<string, boolean>) => void;
}

export const ColumnSelector: FC<ColumnSelectorProps> = ({
  showing,
  setShowing,
  columns,
  onVisibilityChange,
}) => {
  const initLocalVisibility = useCallback(
    () =>
      columns.reduce<Record<string, boolean>>(
        (acc, col) => ({ ...acc, [getFieldKey(col)]: !col.hide }),
        {},
      ),
    [columns],
  );
  const [localVisibility, setLocalVisibility] = useState<
    Record<string, boolean>
  >({});
  useEffect(() => {
    showing && setLocalVisibility(initLocalVisibility());
  }, [showing, initLocalVisibility]);

  const handleToggle = (field: string) => {
    setLocalVisibility((prev) => ({
      ...prev,
      [field]: !prev[field],
    }));
  };

  const handleApply = () => {
    onVisibilityChange(localVisibility);
    setShowing(false);
  };

  const handleCancel = () => {
    setLocalVisibility(initLocalVisibility());
    setShowing(false);
  };

  // Group columns by category - merge optional into base for this dialog
  const columnGroups = useMemo(() => {
    return {
      base: columns.filter((col) => !getFieldKey(col).startsWith("score_")),
      scores: columns.filter((col) => getFieldKey(col).startsWith("score_")),
    };
  }, [columns]);

  const handleSelectAllBase = () => {
    setLocalVisibility((prev) => ({
      ...prev,
      ...Object.fromEntries(
        columnGroups.base.map((col) => [getFieldKey(col), true]),
      ),
    }));
  };
  const handleDeselectAllBase = () => {
    setLocalVisibility((prev) => ({
      ...prev,
      ...Object.fromEntries(
        columnGroups.base.map((col) => [getFieldKey(col), false]),
      ),
    }));
  };
  const handleSelectAllScores = () => {
    setLocalVisibility((prev) => ({
      ...prev,
      ...Object.fromEntries(
        columnGroups.scores.map((col) => [getFieldKey(col), true]),
      ),
    }));
  };
  const handleDeselectAllScores = () => {
    setLocalVisibility((prev) => ({
      ...prev,
      ...Object.fromEntries(
        columnGroups.scores.map((col) => [getFieldKey(col), false]),
      ),
    }));
  };

  const renderColumnCheckbox = (col: ColDef<SampleRow>) => {
    const field = getFieldKey(col);
    return (
      <div key={field} className={styles.checkboxItem}>
        <label className={styles.checkboxLabel}>
          <input
            type="checkbox"
            checked={localVisibility[field]}
            onChange={() => handleToggle(field)}
            className={styles.checkboxInput}
          />
          <span>{col.headerName || field}</span>
        </label>
      </div>
    );
  };

  return (
    <Modal
      id="column-selector-modal"
      title="Choose Columns"
      showing={showing}
      setShowing={setShowing}
      hideFooter
      className={styles.modal}
    >
      <div className={styles.scrollableContent}>
        <div className={styles.columnGroup}>
          <div className={styles.columnHeaderRow}>
            <h6 className={styles.columnHeader}>Base Columns</h6>
            <div className={styles.buttonGroup}>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={handleSelectAllBase}
              >
                Select All
              </button>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={handleDeselectAllBase}
              >
                Deselect All
              </button>
            </div>
          </div>
          {columnGroups.base.map((col) => renderColumnCheckbox(col))}
        </div>

        {columnGroups.scores.length > 0 && (
          <div className={styles.columnGroup}>
            <div className={styles.columnHeaderRow}>
              <h6 className={styles.columnHeader}>Score Columns</h6>
              <div className={styles.buttonGroup}>
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  onClick={handleSelectAllScores}
                >
                  Select All
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  onClick={handleDeselectAllScores}
                >
                  Deselect All
                </button>
              </div>
            </div>
            {columnGroups.scores.map((col) => renderColumnCheckbox(col))}
          </div>
        )}
      </div>

      <div className={styles.footerButtons}>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={handleCancel}
        >
          Cancel
        </button>
        <button type="button" className="btn btn-primary" onClick={handleApply}>
          Apply
        </button>
      </div>
    </Modal>
  );
};
