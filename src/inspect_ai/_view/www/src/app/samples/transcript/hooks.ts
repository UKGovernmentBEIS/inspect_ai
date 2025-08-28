import { useCallback, useMemo } from "react";
import {
  Event,
  Event1,
  Event10,
  Event11,
  Event12,
  Event16,
  Event2,
  Event3,
  Event4,
  Event5,
  Event6,
  Event7,
  Event8,
  Event9,
} from "../../../@types/log";
import { kDefaultExcludeEvents } from "../../../state/sampleSlice";
import { useStore } from "../../../state/store";

export type AllEventTypes =
  | Event
  | Event1
  | Event2
  | Event3
  | Event4
  | Event5
  | Event6
  | Event7
  | Event8
  | Event9
  | Event10
  | Event11
  | Event12
  | Event16;

const eventTypes: Record<AllEventTypes, string> = {
  sample_init: "Sample Init",
  sample_limit: "Sample Limit",
  sandbox: "Sandbox",
  state: "State",
  store: "Store",
  model: "Model",
  tool: "Tool",
  approval: "Approval",
  input: "Input",
  score: "Score",
  error: "Error",
  logger: "Logger",
  info: "Info",
  subtask: "Subtask",
} as const;

export const useTranscriptFilter = () => {
  const filtered = useStore((state) => state.sample.eventFilter.filteredTypes);
  const setFilteredEventTypes = useStore(
    (state) => state.sampleActions.setFilteredEventTypes,
  );

  const filterEventType = useCallback(
    (type: AllEventTypes, isFiltered: boolean) => {
      const newFiltered = new Set(filtered);
      if (isFiltered) {
        newFiltered.delete(type);
      } else {
        newFiltered.add(type);
      }
      setFilteredEventTypes(Array.from(newFiltered));
    },
    [filtered],
  );

  const setDebugFilter = useCallback(() => {
    setFilteredEventTypes([]);
  }, [setFilteredEventTypes]);

  const setDefaultFilter = useCallback(() => {
    setFilteredEventTypes([...kDefaultExcludeEvents]);
  }, [setFilteredEventTypes]);

  const isDefaultFilter = useMemo(() => {
    return (
      filtered.length === kDefaultExcludeEvents.length &&
      [...filtered].every((type) => kDefaultExcludeEvents.includes(type))
    );
  }, [filtered]);

  const isDebugFilter = useMemo(() => {
    return filtered.length === 0;
  }, [filtered]);

  const arrangedEventTypes = useCallback((columns: number = 1) => {
    const keys = Object.keys(eventTypes) as AllEventTypes[];

    // Sort keys alphabetically with default disabled keys at the end
    const sortedKeys = keys.sort((a, b) => {
      const aIsDefault = kDefaultExcludeEvents.includes(a);
      const bIsDefault = kDefaultExcludeEvents.includes(b);

      // If one is in default exclude set and the other isn't, default goes to end
      if (aIsDefault && !bIsDefault) return 1;
      if (!aIsDefault && bIsDefault) return -1;

      // Both are in same category (both default or both not default), sort alphabetically
      return eventTypes[a].localeCompare(eventTypes[b]);
    });

    if (columns === 1) {
      return sortedKeys;
    }

    // Arrange for multi-column layout with proper reading order
    const itemsPerColumn = Math.ceil(sortedKeys.length / columns);
    const columnArrays: AllEventTypes[][] = [];

    // Split into columns
    for (let col = 0; col < columns; col++) {
      const start = col * itemsPerColumn;
      const end = Math.min(start + itemsPerColumn, sortedKeys.length);
      columnArrays.push(sortedKeys.slice(start, end));
    }

    // Interleave items from all columns
    const arrangedKeys: AllEventTypes[] = [];
    const maxItemsInColumn = Math.max(...columnArrays.map((col) => col.length));

    for (let row = 0; row < maxItemsInColumn; row++) {
      for (let col = 0; col < columns; col++) {
        if (row < columnArrays[col].length) {
          arrangedKeys.push(columnArrays[col][row]);
        }
      }
    }

    return arrangedKeys;
  }, []);

  return {
    filtered,
    isDefaultFilter,
    isDebugFilter,
    setDefaultFilter,
    setDebugFilter,
    filterEventType,
    eventTypes,
    arrangedEventTypes,
  };
};
