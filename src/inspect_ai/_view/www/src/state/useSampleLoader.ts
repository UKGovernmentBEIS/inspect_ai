import { useEffect } from "react";
import { useLogSelection, usePrevious, useSampleData } from "./hooks";
import { useStore } from "./store";

/**
 * Hook that handles loading samples based on the current log selection.
 * Prevents duplicate loads by checking if the sample is already loaded or currently loading.
 */
export function useSampleLoader() {
  const sampleData = useSampleData();
  const loadSample = useStore((state) => state.sampleActions.loadSample);
  const logSelection = useLogSelection();

  // Extract sample properties to avoid object reference issues
  const sampleId = logSelection.sample?.id;
  const sampleEpoch = logSelection.sample?.epoch;
  const sampleCompleted = logSelection.sample?.completed;

  // Track changes over time
  const currentSampleCompleted =
    sampleCompleted !== undefined ? sampleCompleted : true;
  const prevCompleted = usePrevious(currentSampleCompleted);
  const prevLogFile = usePrevious<string | undefined>(logSelection.logFile);
  const prevSampleNeedsReload = usePrevious<number>(
    sampleData.sampleNeedsReload,
  );

  useEffect(() => {
    if (
      logSelection.logFile &&
      sampleId !== undefined &&
      sampleEpoch !== undefined
    ) {
      // Check if the current selection matches what's already loaded
      const isCurrentSampleLoaded =
        sampleData.selectedSampleIdentifier?.id === sampleId &&
        sampleData.selectedSampleIdentifier?.epoch === sampleEpoch &&
        sampleData.selectedSampleIdentifier?.logFile === logSelection.logFile;

      // Check if we're currently loading
      const isLoading =
        sampleData.status === "loading" || sampleData.status === "streaming";

      // Is there an error?
      const isError = sampleData.status === "error";

      // Check if this is a meaningful change (not just initial render)
      const logFileChanged =
        prevLogFile !== undefined && prevLogFile !== logSelection.logFile;
      const completedChanged =
        prevCompleted !== undefined && currentSampleCompleted !== prevCompleted;
      const needsReloadChanged =
        prevSampleNeedsReload !== undefined &&
        prevSampleNeedsReload !== sampleData.sampleNeedsReload;

      // Only load if:
      // 1. The current sample is not already loaded AND not currently loading, OR
      // 2. Something meaningful changed
      const shouldLoad =
        (!isCurrentSampleLoaded && !isLoading && !isError) ||
        logFileChanged ||
        completedChanged ||
        needsReloadChanged;

      if (shouldLoad) {
        loadSample(
          logSelection.logFile,
          sampleId,
          sampleEpoch,
          sampleCompleted,
        );
      }
    }
  }, [
    logSelection.logFile,
    sampleId,
    sampleEpoch,
    sampleCompleted,
    currentSampleCompleted,
    sampleData.selectedSampleIdentifier,
    sampleData.status,
    sampleData.sampleNeedsReload,
    prevLogFile,
    prevCompleted,
    prevSampleNeedsReload,
    loadSample,
  ]);
}
