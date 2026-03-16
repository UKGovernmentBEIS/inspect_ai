import { useEffect } from "react";
import { useSamplesRouteParams } from "../app/routing/url";
import { useLogs } from "./hooks";
import { useStore } from "./store";

// Load the log file and select the sample
export const useLoadLog = () => {
  const {
    samplesPath: routeLogPath,
    sampleId,
    epoch,
  } = useSamplesRouteParams();
  const { loadLogs } = useLogs();
  const initLogDir = useStore((state) => state.logsActions.initLogDir);
  const selectSample = useStore((state) => state.logActions.selectSample);
  const logs = useStore((state) => state.logs.logs);
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const logDir = useStore((state) => state.logs.logDir);
  const setSelectedLogFile = useStore(
    (state) => state.logsActions.setSelectedLogFile,
  );

  useEffect(() => {
    const exec = async () => {
      if (routeLogPath && sampleId && epoch) {
        if (!logDir) {
          await initLogDir();
        }

        // Load the log file
        if (!logs.some((log) => log.name.endsWith(routeLogPath))) {
          await loadLogs(routeLogPath);
        }

        if (selectedLogFile !== routeLogPath) {
          setSelectedLogFile(routeLogPath);
        }

        // Select the specific sample
        const targetEpoch = parseInt(epoch, 10);
        selectSample(sampleId, targetEpoch, routeLogPath);
      }
    };

    exec();
  }, [
    routeLogPath,
    sampleId,
    epoch,
    loadLogs,
    setSelectedLogFile,
    selectSample,
    initLogDir,
    logDir,
    logs,
    selectedLogFile,
  ]);
};
