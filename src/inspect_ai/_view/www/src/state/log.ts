import { useCallback } from "react";
import { useStore } from "./store";

export const useUnloadLog = () => {
  const clearSelectedLogDetails = useStore(
    (state) => state.logActions.clearSelectedLogDetails,
  );
  const setSelectedLogIndex = useStore(
    (state) => state.logsActions.setSelectedLogIndex,
  );
  const clearLog = useStore((state) => state.logActions.clearLog);

  const unloadLog = useCallback(() => {
    clearSelectedLogDetails();
    setSelectedLogIndex(-1);
    clearLog();
  }, [clearLog, clearSelectedLogDetails, setSelectedLogIndex]);
  return { unloadLog };
};
