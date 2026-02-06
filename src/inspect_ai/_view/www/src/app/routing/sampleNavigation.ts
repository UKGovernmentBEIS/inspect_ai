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
  const { logPath: routeLogPath } = useLogRouteParams();
  const logDir = useStore((state) => state.logs.logDir);
  const loadedLog = useStore((state) => state.log.loadedLog);

  const selectTab = useCallback(
    (tabId: string) => {
      // Only update URL if we have a loaded log
      if (loadedLog && routeLogPath) {
        // We already have the logPath from params, just navigate to the tab
        const url = logsUrlRaw(routeLogPath, tabId);
        navigate(url);
      } else if (loadedLog) {
        // Fallback to constructing the path if needed
        const url = logsUrl(loadedLog, logDir, tabId);
        navigate(url);
      }
    },
    [loadedLog, routeLogPath, logDir, navigate],
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

  // Navigate to a specific sample with index
  const showSample = useCallback(
    (id: string | number, epoch: number, specifiedSampleTabId?: string) => {
      const resolvedPath = resolveLogPath();

      if (resolvedPath) {
        // Update internal state
        selectSample(id, epoch, resolvedPath);

        // Use specified sampleTabId if provided, otherwise use current sampleTabId from URL params
        const currentSampleTabId = specifiedSampleTabId || sampleTabId;

        const url = logSamplesUrl(resolvedPath, id, epoch, currentSampleTabId);

        // Navigate to the sample URL (now goes to LogSampleDetailView)
        navigate(url);
      }
    },
    [resolveLogPath, selectSample, navigate, sampleTabId],
  );

  const navigateSampleIndex = useCallback(
    (index: number) => {
      if (index > -1 && index < sampleSummaries.length) {
        const summary = sampleSummaries[index];
        // Use logPath from url, otherwise fall back to selectedLogFile
        const logFile = logPath || selectedLogFile;
        if (logFile) {
          selectSample(summary.id, summary.epoch, logFile);
        }
      }
    },
    [sampleSummaries, selectSample, logPath, selectedLogFile],
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

/**
 * Hook for sample navigation within the log context (LogSampleDetailView).
 * Uses filteredSamples to navigate between samples respecting current filters.
 * Unlike useSampleNavigation, this hook doesn't manage dialog state.
 */
export const useLogSampleNavigation = () => {
  const navigate = useNavigate();
  const { logPath, sampleTabId } = useLogRouteParams();

  // Get filtered samples for navigation
  const sampleSummaries = useFilteredSamples();

  // Get the currently selected sample
  const selectedSampleHandle = useStore(
    (state) => state.log.selectedSampleHandle,
  );

  // Action to update selected sample in store
  const selectSample = useStore((state) => state.logActions.selectSample);

  // Calculate current index in the filtered samples list
  const currentIndex = useMemo(() => {
    if (!selectedSampleHandle) {
      return -1;
    }
    return sampleSummaries.findIndex((summary) => {
      return (
        sampleIdsEqual(summary.id, selectedSampleHandle.id) &&
        summary.epoch === selectedSampleHandle.epoch
      );
    });
  }, [selectedSampleHandle, sampleSummaries]);

  // Navigation state
  const hasPrevious = currentIndex > 0;
  const hasNext =
    currentIndex >= 0 && currentIndex < sampleSummaries.length - 1;

  // Navigate to previous sample
  const onPrevious = useCallback(() => {
    if (hasPrevious && logPath) {
      const prevSample = sampleSummaries[currentIndex - 1];
      // Update store state before navigation
      selectSample(prevSample.id, prevSample.epoch, logPath);
      const url = logSamplesUrl(
        logPath,
        prevSample.id,
        prevSample.epoch,
        sampleTabId,
      );
      navigate(url);
    }
  }, [
    hasPrevious,
    logPath,
    sampleSummaries,
    currentIndex,
    sampleTabId,
    selectSample,
    navigate,
  ]);

  // Navigate to next sample
  const onNext = useCallback(() => {
    if (hasNext && logPath) {
      const nextSample = sampleSummaries[currentIndex + 1];
      // Update store state before navigation
      selectSample(nextSample.id, nextSample.epoch, logPath);
      const url = logSamplesUrl(
        logPath,
        nextSample.id,
        nextSample.epoch,
        sampleTabId,
      );
      navigate(url);
    }
  }, [
    hasNext,
    logPath,
    sampleSummaries,
    currentIndex,
    sampleTabId,
    selectSample,
    navigate,
  ]);

  return {
    onPrevious,
    onNext,
    hasPrevious,
    hasNext,
  };
};
