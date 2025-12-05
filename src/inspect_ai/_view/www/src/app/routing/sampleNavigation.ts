import { useCallback, useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useFilteredSamples } from "../../state/hooks";
import { useStore } from "../../state/store";
import { directoryRelativeUrl } from "../../utils/uri";
import { sampleIdsEqual } from "../shared/sample";
import {
  logSamplesUrl,
  logsUrl,
  logsUrlRaw,
  samplesSampleUrl,
  useLogRouteParams,
} from "./url";

export const useLogNavigation = () => {
  const navigate = useNavigate();
  const { logPath } = useLogRouteParams();
  const logDir = useStore((state) => state.logs.logDir);
  const loadedLog = useStore((state) => state.log.loadedLog);

  const selectTab = useCallback(
    (tabId: string) => {
      // Only update URL if we have a loaded log
      if (loadedLog && logPath) {
        // We already have the logPath from params, just navigate to the tab
        const url = logsUrlRaw(logPath, tabId);
        navigate(url);
      } else if (loadedLog) {
        // Fallback to constructing the path if needed
        const url = logsUrl(loadedLog, logDir, tabId);
        navigate(url);
      }
    },
    [loadedLog, logPath, logDir, navigate],
  );

  return {
    selectTab,
  };
};

export const useSampleUrl = () => {
  const { logPath, sampleTabId } = useLogRouteParams();

  const logDirectory = useStore((state) => state.logs.logDir);

  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);

  // Helper function to resolve the log path for URLs
  const resolveLogPath = useCallback(() => {
    // If we have a logPath from URL params, use that
    if (logPath) {
      return logPath;
    }

    if (selectedLogFile) {
      return directoryRelativeUrl(selectedLogFile, logDirectory);
    }

    return undefined;
  }, [logPath, selectedLogFile, logDirectory]);

  // Get a sample URL for a specific sample
  const getSampleUrl = useCallback(
    (
      sampleId: string | number,
      epoch: number,
      specificSampleTabId?: string,
    ) => {
      const resolvedPath = resolveLogPath();
      if (resolvedPath) {
        const currentSampleTabId = specificSampleTabId || sampleTabId;
        const url = logSamplesUrl(
          resolvedPath,
          sampleId,
          epoch,
          currentSampleTabId,
        );
        return url;
      }
      return undefined;
    },
    [resolveLogPath, sampleTabId],
  );
  return getSampleUrl;
};

/**
 * Hook that provides sample navigation utilities with proper URL handling
 * for use across the application
 */
export const useSampleNavigation = () => {
  const navigate = useNavigate();

  // The log directory
  const logDirectory = useStore((state) => state.logs.logDir);

  // The log
  const { logPath, tabId, sampleTabId } = useLogRouteParams();

  // Get the store access values directly in the hook
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);

  // Helper function to resolve the log path for URLs
  const resolveLogPath = useCallback(() => {
    // If we have a logPath from URL params, use that
    if (logPath) {
      return logPath;
    }

    if (selectedLogFile) {
      return directoryRelativeUrl(selectedLogFile, logDirectory);
    }

    return undefined;
  }, [logPath, selectedLogFile, logDirectory]);

  // The samples
  const sampleSummaries = useFilteredSamples();

  // Sample hooks
  const selectedSampleHandle = useStore(
    (state) => state.log.selectedSampleHandle,
  );

  const selectedSampleIndex = useMemo(() => {
    return sampleSummaries.findIndex((summary) => {
      return (
        sampleIdsEqual(summary.id, selectedSampleHandle?.id) &&
        summary.epoch === selectedSampleHandle?.epoch
      );
    });
  }, [selectedSampleHandle, sampleSummaries]);

  const selectSample = useStore((state) => state.logActions.selectSample);
  const setShowingSampleDialog = useStore(
    (state) => state.appActions.setShowingSampleDialog,
  );
  const showingSampleDialog = useStore((state) => state.app.dialogs.sample);

  // Navigate to a specific sample with index
  const showSample = useCallback(
    (id: string | number, epoch: number, specifiedSampleTabId?: string) => {
      const resolvedPath = resolveLogPath();

      if (resolvedPath) {
        // Update internal state
        selectSample(id, epoch);
        setShowingSampleDialog(true);

        // Use specified sampleTabId if provided, otherwise use current sampleTabId from URL params
        const currentSampleTabId = specifiedSampleTabId || sampleTabId;

        const url = logSamplesUrl(resolvedPath, id, epoch, currentSampleTabId);

        // Navigate to the sample URL
        navigate(url);
      }
    },
    [
      resolveLogPath,
      selectSample,
      setShowingSampleDialog,
      navigate,
      sampleTabId,
    ],
  );

  const navigateSampleIndex = useCallback(
    (index: number) => {
      if (index > -1 && index < sampleSummaries.length) {
        if (showingSampleDialog) {
          const resolvedPath = resolveLogPath();
          if (resolvedPath) {
            const summary = sampleSummaries[index];
            const url = logSamplesUrl(
              resolvedPath,
              summary.id,
              summary.epoch,
              sampleTabId,
            );

            // Navigate to the sample URL
            navigate(url);
          }
        } else {
          const summary = sampleSummaries[index];
          selectSample(summary.id, summary.epoch);
        }
      }
    },
    [
      sampleSummaries,
      showingSampleDialog,
      resolveLogPath,
      sampleTabId,
      navigate,
      selectSample,
    ],
  );

  // Navigate to the next sample
  const nextSample = useCallback(() => {
    const itemsCount = sampleSummaries.length;
    const next = Math.min(selectedSampleIndex + 1, itemsCount - 1);
    navigateSampleIndex(next);
  }, [selectedSampleIndex, navigateSampleIndex, sampleSummaries]);

  // Navigate to the previous sample
  const previousSample = useCallback(() => {
    const prev = selectedSampleIndex - 1;
    navigateSampleIndex(prev);
  }, [selectedSampleIndex, navigateSampleIndex]);

  const firstSample = useCallback(() => {
    navigateSampleIndex(0);
  }, [navigateSampleIndex]);

  const lastSample = useCallback(() => {
    navigateSampleIndex(sampleSummaries.length - 1);
  }, [navigateSampleIndex, sampleSummaries]);

  // Get a sample URL for a specific sample
  const getSampleUrl = useCallback(
    (
      sampleId: string | number,
      epoch: number,
      specificSampleTabId?: string,
    ) => {
      const resolvedPath = resolveLogPath();
      if (resolvedPath) {
        const currentSampleTabId = specificSampleTabId || sampleTabId;
        const url = logSamplesUrl(
          resolvedPath,
          sampleId,
          epoch,
          currentSampleTabId,
        );
        return `#${url}`;
      }
      return undefined;
    },
    [resolveLogPath, sampleTabId],
  );

  // Navigate back from sample dialog
  const clearSampleUrl = useCallback(() => {
    const resolvedPath = resolveLogPath();
    if (resolvedPath) {
      const url = logsUrlRaw(resolvedPath, tabId);
      navigate(url);
    }
  }, [resolveLogPath, navigate, tabId]);

  return {
    showSample,
    nextEnabled: selectedSampleIndex < sampleSummaries.length - 1,
    nextSample,
    previousEnabled: selectedSampleIndex > 0,
    previousSample,
    firstSample,
    lastSample,
    getSampleUrl,
    clearSampleUrl,
  };
};

export const useSampleDetailNavigation = () => {
  const [searchParams, _setSearchParams] = useSearchParams();
  const message = searchParams.get("message");
  const event = searchParams.get("event");
  return {
    message,
    event,
  };
};

/**
 * Hook for navigating to sample details from the samples grid.
 * Uses the /samples route pattern instead of /logs.
 */
export const useSamplesGridNavigation = () => {
  const navigate = useNavigate();
  const logDirectory = useStore((state) => state.logs.logDir);

  const navigateToSampleDetail = useCallback(
    (
      logFile: string,
      sampleId: string | number,
      epoch: number,
      openInNewWindow = false,
    ) => {
      // Convert absolute logFile path to relative path
      const relativePath = directoryRelativeUrl(logFile, logDirectory);
      const url = samplesSampleUrl(relativePath, sampleId, epoch);

      if (openInNewWindow) {
        // Open in new window/tab
        window.open(`#${url}`, "_blank");
      } else {
        navigate(url);
      }
    },
    [navigate, logDirectory],
  );

  return {
    navigateToSampleDetail,
  };
};
