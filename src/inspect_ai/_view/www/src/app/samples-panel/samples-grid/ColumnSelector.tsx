import { ColDef } from "ag-grid-community";
import { FC, useMemo } from "react";
import { PopOver } from "../../../components/PopOver";
import { getFieldKey } from "./hooks";
import { SampleRow } from "./types";

interface ColumnSelectorProps {
  showing: boolean;
  setShowing: (showing: boolean) => void;
  columns: ColDef<SampleRow>[];
  onVisibilityChange: (visibility: Record<string, boolean>) => void;
  positionEl: HTMLElement | null;
}

export const ColumnSelector: FC<ColumnSelectorProps> = ({
  showing,
  setShowing,
  columns,
  onVisibilityChange,
  positionEl,
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
    return (
      <div key={field} style={{ marginBottom: "0.5rem" }}>
        <label
          style={{ display: "flex", alignItems: "center", cursor: "pointer" }}
        >
          <input
            type="checkbox"
            checked={currentVisibility[field]}
            onChange={() => handleToggle(field)}
            style={{ marginRight: "0.5rem", cursor: "pointer" }}
          />
          <span>{col.headerName || field}</span>
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
      hoverDelay={0}
      styles={{ width: "500px" }}
    >
      <div style={{ maxHeight: "calc(100vh - 4rem)", overflowY: "auto" }}>
        <div>
          <div style={{ display: "flex", gap: "2rem" }}>
            <b>Base</b>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button
                type="button"
                className="btn btn-link btn-sm"
                style={{ padding: 0, textDecoration: "none" }}
                onClick={handleSelectAllBase}
              >
                All
              </button>
              |
              <button
                type="button"
                className="btn btn-link btn-sm"
                style={{ padding: 0, textDecoration: "none" }}
                onClick={handleDeselectAllBase}
              >
                None
              </button>
            </div>
          </div>
          <div style={{ columns: 2 }}>
            {columnGroups.base.map((col) => renderColumnCheckbox(col))}
          </div>
        </div>

        {columnGroups.scores.length > 0 && (
          <div>
            <div style={{ display: "flex", gap: "2rem" }}>
              <b>Scorers</b>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button
                  type="button"
                  className="btn btn-link btn-sm"
                  style={{ padding: 0, textDecoration: "none" }}
                  onClick={handleSelectAllScores}
                >
                  All
                </button>
                |
                <button
                  type="button"
                  className="btn btn-link btn-sm"
                  style={{ padding: 0, textDecoration: "none" }}
                  onClick={handleDeselectAllScores}
                >
                  None
                </button>
              </div>
            </div>
            <div style={{ columns: 2 }}>
              {columnGroups.scores.map((col) => renderColumnCheckbox(col))}
            </div>
          </div>
        )}
      </div>
    </PopOver>
  );
};
