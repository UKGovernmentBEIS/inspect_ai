import type { GridState } from "ag-grid-community";

import { computeInitialLogGridState } from "./gridState";

describe("computeInitialLogGridState", () => {
  it("returns the existing grid state when no previous path exists", () => {
    const gridState = { columnState: [] } as unknown as GridState;

    const result = computeInitialLogGridState(gridState, undefined, "path/a");

    expect(result).toBe(gridState);
  });

  it("returns the existing grid state when path has not changed", () => {
    const gridState = { columnState: [] } as unknown as GridState;

    const result = computeInitialLogGridState(gridState, "path/a", "path/a");

    expect(result).toBe(gridState);
  });

  it("removes filters when the path changes", () => {
    const gridState = {
      filter: { field: "value" },
      columnState: [],
    } as unknown as GridState;

    const result = computeInitialLogGridState(gridState, "path/a", "path/b");

    expect(result).not.toBe(gridState);
    expect(result).toEqual({ columnState: [] });
    expect(gridState).toHaveProperty("filter");
  });
});

