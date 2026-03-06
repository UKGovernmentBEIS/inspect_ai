import { useEffect } from "react";
import { SampleSummary } from "../client/api/types";
import { createLogger } from "../utils/logger";
import { useLogSelection } from "./hooks";
import { getSamplePolling } from "./samplePollingInstance";
import { useStore } from "./store";

const log = createLogger("useSamplePolling");

/**
 * Hook that handles polling for running samples.
 * When a sample is in a running state (completed === false), this hook starts polling for updates.
 * Contains the polling start logic that was previously in sampleSlice.pollSample.
 */
export function usePollSample() {
  const logSelection = useLogSelection();
  const loadedLog = useStore((state) => state.log.loadedLog);

  // Extract sample properties to avoid object reference issues
  const sampleId = logSelection.sample?.id;
  const sampleEpoch = logSelection.sample?.epoch;
  const sampleCompleted = logSelection.sample?.completed;

  useEffect(() => {
    // Only start polling for running (non-completed) samples
    if (
      logSelection.logFile &&
      sampleId !== undefined &&
      sampleEpoch !== undefined &&
      sampleCompleted === false &&
      loadedLog
    ) {
      log.debug(`Starting poll for running sample: ${sampleId}-${sampleEpoch}`);
      // Create a minimal SampleSummary object for polling
      const sampleSummary: SampleSummary = {
        id: sampleId,
        epoch: sampleEpoch,
      } as SampleSummary;
      getSamplePolling().startPolling(logSelection.logFile, sampleSummary);
    }
  }, [logSelection.logFile, sampleId, sampleEpoch, sampleCompleted, loadedLog]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      getSamplePolling().stopPolling();
    };
  }, []);
}
