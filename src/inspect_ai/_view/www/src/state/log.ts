import { useCallback } from "react";
import { useStore } from "./store";

export const useUnloadLog = () => {
  const clearSelectedLogSummary = useStore(
    (state) => state.logActions.clearSelectedLogSummary,
  );
  const setSelectedLogIndex = useStore(
    (state) => state.logsActions.setSelectedLogIndex,
  );
  const clearLog = useStore((state) => state.logActions.clearLog);

  const unloadLog = useCallback(() => {
    clearSelectedLogSummary();
    setSelectedLogIndex(-1);
    clearLog();
  }, [clearLog, clearSelectedLogSummary, setSelectedLogIndex]);
  return { unloadLog };
};
