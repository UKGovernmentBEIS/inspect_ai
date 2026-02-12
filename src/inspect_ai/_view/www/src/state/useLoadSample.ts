import { useCallback, useEffect } from "react";
import { createLogger } from "../utils/logger";
import { useLogSelection, usePrevious, useSampleData } from "./hooks";
import { getSamplePolling } from "./samplePollingInstance";
import { resolveSample } from "./sampleUtils";
import { useStore } from "./store";

// List of virtuoso list keys that should be cleared when sample changes
const SAMPLE_LIST_KEYS = ["transcript-tree"];

const log = createLogger("useSampleLoader");

/**
 * Hook that handles loading samples based on the current log selection.
 * Contains the full sample loading logic that was previously in sampleSlice.loadSample.
 */
export function useLoadSample() {
  const sampleData = useSampleData();
  const logSelection = useLogSelection();

  // Get store state and actions
  const api = useStore((state) => state.api);
  const sampleActions = useStore((state) => state.sampleActions);
  const clearListPosition = useStore(
    (state) => state.appActions.clearListPosition,
  );
  const getSelectedSample = useStore(
    (state) => state.sampleActions.getSelectedSample,
  );

  // Extract sample properties to avoid object reference issues
  const sampleId = logSelection.sample?.id;
  const sampleEpoch = logSelection.sample?.epoch;
  const sampleCompleted = logSelection.sample?.completed;

  // Track changes over time
  const currentSampleCompleted =
    sampleCompleted !== undefined ? sampleCompleted : true;
  const prevCompleted = usePrevious(currentSampleCompleted);
  const prevLogFile = usePrevious<string | undefined>(logSelection.logFile);
  const prevSampleId = usePrevious(sampleId);
  const prevSampleNeedsReload = usePrevious<number>(
    sampleData.sampleNeedsReload,
  );

  const loadSample = useCallback(
    async (
      logFile: string,
      id: number | string,
      epoch: number,
      completed?: boolean,
    ) => {
      // Skip if already loading this exact sample
      const currentId = sampleData.selectedSampleIdentifier;
      const isSameSample =
        currentId?.id === id &&
        currentId?.epoch === epoch &&
        currentId?.logFile === logFile;
      const isLoading =
        sampleData.status === "loading" || sampleData.status === "streaming";

      if (isSameSample && isLoading) {
        return;
      }

      // Clear scroll positions for sample-related virtuoso lists
      // This ensures the new sample starts at the top instead of restoring
      // the previous sample's scroll position
      for (const key of SAMPLE_LIST_KEYS) {
        clearListPosition(key);
      }

      // Set the identifier first
      sampleActions.setSampleIdentifier(logFile, id, epoch);
      sampleActions.setSampleError(undefined);
      sampleActions.setSampleStatus("loading");

      try {
        if (completed !== false) {
          log.debug(`LOADING COMPLETED SAMPLE: ${id}-${epoch}`);
          // Stop any existing polling when loading a completed sample
          getSamplePolling().stopPolling();

          // Fetch the sample from the API
          const sample = await api?.get_log_sample(logFile, id, epoch);
          log.debug(`LOADED COMPLETED SAMPLE: ${id}-${epoch}`);

          if (sample) {
            // Clear collapsed events if the sample changed
            if (
              currentId?.id !== sample.id ||
              currentId?.epoch !== sample.epoch ||
              currentId?.logFile !== logFile
            ) {
              sampleActions.clearCollapsedEvents();
            }
            const migratedSample = resolveSample(sample);
            sampleActions.setSelectedSample(migratedSample, logFile);
            sampleActions.setSampleStatus("ok");
          } else {
            sampleActions.setSampleStatus("error");
            throw new Error(
              "Unable to load sample - an unknown error occurred",
            );
          }
        } else {
          log.debug(`PREPARING FOR POLLING RUNNING SAMPLE: ${id}-${epoch}`);
          // Clear the previous sample so component uses runningEvents instead
          // of old sample.events. Polling will be started by useSamplePolling.
          sampleActions.clearSampleForPolling(logFile, id, epoch);
          getSamplePolling().stopPolling();
        }
      } catch (e) {
        sampleActions.setSampleError(e as Error);
        sampleActions.setSampleStatus("error");
      }
    },
    [
      api,
      clearListPosition,
      sampleActions,
      sampleData.selectedSampleIdentifier,
      sampleData.status,
    ],
  );

  useEffect(() => {
    if (
      logSelection.logFile &&
      sampleId !== undefined &&
      sampleEpoch !== undefined
    ) {
      // Check if the current selection matches what's already loaded
      // AND that we actually have the sample data (not just the identifier).
      // This is important for VSCode reloads where the identifier may be
      // persisted but the actual sample data (stored in a ref) is lost.
      const identifierMatches =
        sampleData.selectedSampleIdentifier?.id === sampleId &&
        sampleData.selectedSampleIdentifier?.epoch === sampleEpoch &&
        sampleData.selectedSampleIdentifier?.logFile === logSelection.logFile;
      const hasSampleData = getSelectedSample() !== undefined;
      const isCurrentSampleLoaded = identifierMatches && hasSampleData;

      // Check if we're currently loading
      const isLoading =
        sampleData.status === "loading" || sampleData.status === "streaming";

      // Is there an error?
      const isError = sampleData.status === "error";

      // Check if this is a meaningful change (not just initial render)
      const logFileChanged =
        prevLogFile !== undefined && prevLogFile !== logSelection.logFile;
      const sampleIdChanged =
        prevSampleId !== undefined && prevSampleId !== sampleId;
      const completedChanged =
        prevCompleted !== undefined && currentSampleCompleted !== prevCompleted;
      const needsReloadChanged =
        prevSampleNeedsReload !== undefined &&
        prevSampleNeedsReload !== sampleData.sampleNeedsReload;

      // Only load if:
      // 1. The current sample is not already loaded AND not currently loading, OR
      // 2. Something meaningful changed (log file, sample ID, completed status, or reload flag)
      const shouldLoad =
        (!isCurrentSampleLoaded && !isLoading && !isError) ||
        logFileChanged ||
        sampleIdChanged ||
        completedChanged ||
        needsReloadChanged;

      if (shouldLoad) {
        void loadSample(
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
    sampleData.getSelectedSample,
    prevLogFile,
    prevSampleId,
    prevCompleted,
    prevSampleNeedsReload,
    loadSample,
    getSelectedSample,
  ]);
}
