import { useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useFilteredSamples } from "../../state/hooks";
import { useStore } from "../../state/store";
import { directoryRelativeUrl } from "../../utils/uri";

export const useLogNavigation = () => {
  const navigate = useNavigate();
  const { logPath } = useParams<{ logPath: string }>();
  const logs = useStore((state) => state.logs.logs);
  const loadedLog = useStore((state) => state.log.loadedLog);

  const selectTab = useCallback(
    (tabId: string) => {
      // Only update URL if we have a loaded log
      if (loadedLog && logPath) {
        // We already have the logPath from params, just navigate to the tab
        navigate(`/logs/${logPath}/${tabId}`);
      } else if (loadedLog) {
        // Fallback to constructing the path if needed
        const logPathSegment = directoryRelativeUrl(loadedLog, logs.log_dir);
        navigate(`/logs/${logPathSegment}/${tabId}`);
      }
    },
    [loadedLog, logPath, logs.log_dir, navigate],
  );

  return {
    selectTab,
  };
};

/**
 * Hook that provides sample navigation utilities with proper URL handling
 * for use across the application
 */
export const useSampleNavigation = () => {
  const navigate = useNavigate();

  // The log directory
  const logDirectory = useStore((state) => state.logs.logs.log_dir);

  // The log
  const { logPath, tabId, sampleTabId } = useParams<{
    logPath?: string;
    tabId?: string;
    sampleTabId?: string;
  }>();

  // Get the store access values directly in the hook
  const getSelectedLogFile = useStore(
    (state) => state.logsActions.getSelectedLogFile,
  );

  // Helper function to resolve the log path for URLs
  const resolveLogPath = useCallback(() => {
    // If we have a logPath from URL params, use that
    if (logPath) {
      return logPath;
    }

    // Otherwise use the selected log file
    const selectedLogFile = getSelectedLogFile();

    if (selectedLogFile) {
      return directoryRelativeUrl(selectedLogFile, logDirectory);
    }

    return undefined;
  }, [logPath, getSelectedLogFile, logDirectory]);

  // The samples
  const sampleSummaries = useFilteredSamples();

  // Sample hooks
  const selectedSampleIndex = useStore(
    (state) => state.log.selectedSampleIndex,
  );
  const selectSample = useStore((state) => state.logActions.selectSample);
  const setShowingSampleDialog = useStore(
    (state) => state.appActions.setShowingSampleDialog,
  );

  // Navigate to a specific sample with index
  const showSample = useCallback(
    (index: number, specifiedSampleTabId?: string) => {
      if (sampleSummaries && index >= 0 && index < sampleSummaries.length) {
        const sample = sampleSummaries[index];
        const resolvedPath = resolveLogPath();

        if (resolvedPath) {
          // Update internal state
          selectSample(index);
          setShowingSampleDialog(true);

          // Use specified sampleTabId if provided, otherwise use current sampleTabId from URL params
          const currentSampleTabId = specifiedSampleTabId || sampleTabId;

          // Navigate to the sample URL
          navigate(
            currentSampleTabId
              ? `/logs/${resolvedPath}/${tabId || "samples"}/sample/${sample.id}/${sample.epoch}/${currentSampleTabId}`
              : `/logs/${resolvedPath}/${tabId || "samples"}/sample/${sample.id}/${sample.epoch}`,
          );
        }
      }
    },
    [
      sampleSummaries,
      resolveLogPath,
      selectSample,
      setShowingSampleDialog,
      navigate,
      tabId,
      sampleTabId,
    ],
  );

  // Navigate to the next sample
  const nextSample = useCallback(() => {
    const itemsCount = sampleSummaries.length;
    const next = Math.min(selectedSampleIndex + 1, itemsCount - 1);
    if (next > -1) {
      showSample(next, sampleTabId);
    }
  }, [selectedSampleIndex, showSample, sampleTabId]);

  // Navigate to the previous sample
  const previousSample = useCallback(() => {
    const prev = selectedSampleIndex - 1;
    if (prev > -1) {
      showSample(prev, sampleTabId);
    }
  }, [selectedSampleIndex, showSample, sampleTabId]);

  // Get a sample URL for a specific sample
  const getSampleUrl = useCallback(
    (
      sampleId: string | number,
      epoch: string | number,
      specificSampleTabId?: string,
    ) => {
      const resolvedPath = resolveLogPath();
      if (resolvedPath) {
        const currentSampleTabId = specificSampleTabId || sampleTabId;
        return currentSampleTabId
          ? `/logs/${resolvedPath}/${tabId || "samples"}/sample/${sampleId}/${epoch}/${currentSampleTabId}`
          : `/logs/${resolvedPath}/${tabId || "samples"}/sample/${sampleId}/${epoch}`;
      }
      return undefined;
    },
    [resolveLogPath, tabId, sampleTabId],
  );

  // Navigate back from sample dialog
  const clearSampleUrl = useCallback(() => {
    const resolvedPath = resolveLogPath();
    if (resolvedPath) {
      navigate(`/logs/${resolvedPath}/${tabId || "samples"}`);
    }
  }, [resolveLogPath, navigate, tabId]);

  return {
    showSample,
    nextEnabled: selectedSampleIndex < sampleSummaries.length - 1,
    nextSample,
    previousEnabled: selectedSampleIndex > 0,
    previousSample,
    getSampleUrl,
    clearSampleUrl,
  };
};
