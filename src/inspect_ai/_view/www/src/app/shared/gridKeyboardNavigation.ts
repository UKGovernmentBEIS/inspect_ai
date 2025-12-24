import type { IRowNode } from "ag-grid-community";
import type { AgGridReact } from "ag-grid-react";
import type { RefObject } from "react";

interface KeyboardNavOptions<T> {
  gridRef: RefObject<AgGridReact<T> | null>;
  onOpenRow: (rowNode: IRowNode<T>, event: KeyboardEvent) => void;
  pageJump?: number;
}

// Shared keyboard navigation handler for AG Grid lists.
export const createGridKeyboardHandler = <T>({
  gridRef,
  onOpenRow,
  pageJump = 10,
}: KeyboardNavOptions<T>) => {
  return (e: KeyboardEvent) => {
    const api = gridRef.current?.api;
    if (!api) {
      return;
    }

    const activeElement = document.activeElement;
    if (
      activeElement &&
      (activeElement.tagName === "INPUT" ||
        activeElement.tagName === "TEXTAREA" ||
        activeElement.tagName === "SELECT")
    ) {
      return;
    }

    const selectedRows = api.getSelectedNodes();
    const totalRows = api.getDisplayedRowCount();

    let currentRowIndex = -1;
    if (selectedRows.length > 0 && selectedRows[0].rowIndex !== null) {
      currentRowIndex = selectedRows[0].rowIndex;
    }

    let targetRowIndex: number | null = null;

    switch (e.key) {
      case "ArrowUp":
        e.preventDefault();
        if (e.metaKey || e.ctrlKey) {
          targetRowIndex = 0;
        } else {
          targetRowIndex = currentRowIndex === -1 ? 0 : currentRowIndex - 1;
          targetRowIndex = Math.max(0, targetRowIndex);
        }
        break;

      case "ArrowDown":
        e.preventDefault();
        if (e.metaKey || e.ctrlKey) {
          targetRowIndex = totalRows - 1;
        } else {
          targetRowIndex = currentRowIndex === -1 ? 0 : currentRowIndex + 1;
          targetRowIndex = Math.min(totalRows - 1, targetRowIndex);
        }
        break;

      case "Home":
        e.preventDefault();
        targetRowIndex = 0;
        break;

      case "End":
        e.preventDefault();
        targetRowIndex = totalRows - 1;
        break;

      case "PageUp":
        e.preventDefault();
        targetRowIndex =
          currentRowIndex === -1 ? 0 : Math.max(0, currentRowIndex - pageJump);
        break;

      case "PageDown":
        e.preventDefault();
        targetRowIndex =
          currentRowIndex === -1
            ? 0
            : Math.min(totalRows - 1, currentRowIndex + pageJump);
        break;

      case "Enter":
      case " ":
        e.preventDefault();
        if (currentRowIndex !== -1) {
          const rowNode = api.getDisplayedRowAtIndex(currentRowIndex);
          if (rowNode?.data) {
            onOpenRow(rowNode, e);
          }
        }
        return;

      default:
        return;
    }

    if (targetRowIndex !== null && targetRowIndex !== currentRowIndex) {
      const targetNode = api.getDisplayedRowAtIndex(targetRowIndex);
      if (targetNode) {
        targetNode.setSelected(true, true);
        api.ensureIndexVisible(targetRowIndex, "middle");
      }
    }
  };
};
