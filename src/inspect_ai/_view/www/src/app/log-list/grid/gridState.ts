import type { GridState } from "ag-grid-community";

export const computeInitialLogGridState = (
  gridState: GridState | undefined,
  previousPath: string | undefined,
  currentPath?: string,
): GridState | undefined => {
  if (previousPath !== undefined && previousPath !== currentPath) {
    const result = gridState ? { ...gridState } : undefined;
    if (result && "filter" in result) {
      delete (result as { filter?: unknown }).filter;
    }
    return result;
  }
  return gridState;
};

