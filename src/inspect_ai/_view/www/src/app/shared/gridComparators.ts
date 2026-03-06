import type { IRowNode } from "ag-grid-community";

/**
 * Creates a comparator that ensures folders are always displayed first,
 * regardless of sort order, and then applies the provided comparison function
 * for non-folder items.
 *
 * @param compareFn - Function to compare two values (can use items if needed)
 * @returns A comparator function suitable for ag-grid ColDef
 */
export function createFolderFirstComparator<T extends { type?: string }>(
  compareFn: (valueA: unknown, valueB: unknown, itemA: T, itemB: T) => number,
) {
  return (
    valueA: unknown,
    valueB: unknown,
    nodeA: IRowNode<T>,
    nodeB: IRowNode<T>,
  ): number => {
    const itemA = nodeA.data;
    const itemB = nodeB.data;
    if (!itemA || !itemB) return 0;

    // Always put folders first
    if (itemA.type !== itemB.type) {
      return itemA.type === "folder" ? -1 : 1;
    }

    // Both are the same type, use the provided comparison function
    return compareFn(valueA, valueB, itemA, itemB);
  };
}

/**
 * Common comparison functions for use with createFolderFirstComparator
 */
export const comparators = {
  /** Compare values as numbers */
  number: (a: unknown, b: unknown) => {
    return Number(a || 0) - Number(b || 0);
  },

  /** Compare values as dates */
  date: (a: unknown, b: unknown) => {
    const timeA = a ? new Date(a as string | number | Date).getTime() : 0;
    const timeB = b ? new Date(b as string | number | Date).getTime() : 0;
    return timeA - timeB;
  },
};
