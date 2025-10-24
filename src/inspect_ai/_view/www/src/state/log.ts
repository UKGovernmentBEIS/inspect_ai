import { useCallback } from "react";
import { useStore } from "./store";

export const useUnloadLog = () => {
  const clearSelectedLogDetails = useStore(
    (state) => state.logActions.clearSelectedLogDetails,
  );
  const clearSelectedLogFile = useStore(
    (state) => state.logsActions.clearSelectedLogFile,
  );
  const clearLog = useStore((state) => state.logActions.clearLog);

  const unloadLog = useCallback(() => {
    clearSelectedLogDetails();
    clearSelectedLogFile();
    clearLog();
  }, [clearLog, clearSelectedLogDetails, clearSelectedLogFile]);
  return { unloadLog };
};
