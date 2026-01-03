import { useEffect } from "react";
import { useLogSelection, useSampleData } from "./hooks";
import { useStore } from "./store";

/**
 * Hook that handles polling for running samples.
 * When a sample is in a running state, this hook polls for updates.
 */
export function useSamplePolling() {
  const sampleData = useSampleData();
  const pollSample = useStore((state) => state.sampleActions.pollSample);
  const logSelection = useLogSelection();

  // Extract sample properties to avoid object reference issues
  const sampleId = logSelection.sample?.id;
  const sampleEpoch = logSelection.sample?.epoch;

  useEffect(() => {
    if (
      sampleData.running &&
      logSelection.logFile &&
      sampleId !== undefined &&
      sampleEpoch !== undefined
    ) {
      pollSample(logSelection.logFile, sampleId, sampleEpoch);
    }
  }, [
    logSelection.logFile,
    sampleId,
    sampleEpoch,
    pollSample,
    sampleData.running,
  ]);
}
