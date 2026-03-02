import { b as reactExports } from "./vendor-grid.js";
import { z as useFilteredSamples } from "./ApplicationNavbar.js";
import { a as useNavigate, c as useLogRouteParams, u as useStore, a2 as sampleIdsEqual, D as logSamplesUrl, C as useSearchParams, e as directoryRelativeUrl, k as logsUrlRaw, M as samplesSampleUrl } from "./index.js";
const useSampleNavigation = () => {
  const navigate = useNavigate();
  const logDirectory = useStore((state) => state.logs.logDir);
  const { logPath, tabId, sampleTabId } = useLogRouteParams();
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const resolveLogPath = reactExports.useCallback(() => {
    if (logPath) {
      return logPath;
    }
    if (selectedLogFile) {
      return directoryRelativeUrl(selectedLogFile, logDirectory);
    }
    return void 0;
  }, [logPath, selectedLogFile, logDirectory]);
  const sampleSummaries = useFilteredSamples();
  const selectedSampleHandle = useStore(
    (state) => state.log.selectedSampleHandle
  );
  const selectedSampleIndex = reactExports.useMemo(() => {
    return sampleSummaries.findIndex((summary) => {
      return sampleIdsEqual(summary.id, selectedSampleHandle?.id) && summary.epoch === selectedSampleHandle?.epoch;
    });
  }, [selectedSampleHandle, sampleSummaries]);
  const selectSample = useStore((state) => state.logActions.selectSample);
  const showSample = reactExports.useCallback(
    (id, epoch, specifiedSampleTabId) => {
      const resolvedPath = resolveLogPath();
      if (resolvedPath) {
        selectSample(id, epoch, resolvedPath);
        const currentSampleTabId = specifiedSampleTabId || sampleTabId;
        const url = logSamplesUrl(resolvedPath, id, epoch, currentSampleTabId);
        navigate(url);
      }
    },
    [resolveLogPath, selectSample, navigate, sampleTabId]
  );
  const navigateSampleIndex = reactExports.useCallback(
    (index) => {
      if (index > -1 && index < sampleSummaries.length) {
        const summary = sampleSummaries[index];
        const logFile = logPath || selectedLogFile;
        if (logFile) {
          selectSample(summary.id, summary.epoch, logFile);
        }
      }
    },
    [sampleSummaries, selectSample, logPath, selectedLogFile]
  );
  const nextSample = reactExports.useCallback(() => {
    const itemsCount = sampleSummaries.length;
    const next = Math.min(selectedSampleIndex + 1, itemsCount - 1);
    navigateSampleIndex(next);
  }, [selectedSampleIndex, navigateSampleIndex, sampleSummaries]);
  const previousSample = reactExports.useCallback(() => {
    const prev = selectedSampleIndex - 1;
    navigateSampleIndex(prev);
  }, [selectedSampleIndex, navigateSampleIndex]);
  const firstSample = reactExports.useCallback(() => {
    navigateSampleIndex(0);
  }, [navigateSampleIndex]);
  const lastSample = reactExports.useCallback(() => {
    navigateSampleIndex(sampleSummaries.length - 1);
  }, [navigateSampleIndex, sampleSummaries]);
  const getSampleUrl = reactExports.useCallback(
    (sampleId, epoch, specificSampleTabId) => {
      const resolvedPath = resolveLogPath();
      if (resolvedPath) {
        const currentSampleTabId = specificSampleTabId || sampleTabId;
        const url = logSamplesUrl(
          resolvedPath,
          sampleId,
          epoch,
          currentSampleTabId
        );
        return `#${url}`;
      }
      return void 0;
    },
    [resolveLogPath, sampleTabId]
  );
  const clearSampleUrl = reactExports.useCallback(() => {
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
    clearSampleUrl
  };
};
const useSampleDetailNavigation = () => {
  const [searchParams] = useSearchParams();
  const message = searchParams.get("message");
  const event = searchParams.get("event");
  return {
    message,
    event
  };
};
const useSamplesGridNavigation = () => {
  const navigate = useNavigate();
  const logDirectory = useStore((state) => state.logs.logDir);
  const navigateToSampleDetail = reactExports.useCallback(
    (logFile, sampleId, epoch, openInNewWindow = false) => {
      const relativePath = directoryRelativeUrl(logFile, logDirectory);
      const url = samplesSampleUrl(relativePath, sampleId, epoch);
      if (openInNewWindow) {
        window.open(`#${url}`, "_blank");
      } else {
        navigate(url);
      }
    },
    [navigate, logDirectory]
  );
  return {
    navigateToSampleDetail
  };
};
const useLogSampleNavigation = () => {
  const navigate = useNavigate();
  const { logPath: routeLogPath, sampleTabId } = useLogRouteParams();
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const logPath = routeLogPath || selectedLogFile;
  const sampleSummaries = useFilteredSamples();
  const selectedSampleHandle = useStore(
    (state) => state.log.selectedSampleHandle
  );
  const selectSample = useStore((state) => state.logActions.selectSample);
  const currentIndex = reactExports.useMemo(() => {
    if (!selectedSampleHandle) {
      return -1;
    }
    return sampleSummaries.findIndex((summary) => {
      return sampleIdsEqual(summary.id, selectedSampleHandle.id) && summary.epoch === selectedSampleHandle.epoch;
    });
  }, [selectedSampleHandle, sampleSummaries]);
  const hasPrevious = currentIndex > 0;
  const hasNext = currentIndex >= 0 && currentIndex < sampleSummaries.length - 1;
  const onPrevious = reactExports.useCallback(() => {
    if (hasPrevious && logPath && currentIndex > 0) {
      const prevSample = sampleSummaries[currentIndex - 1];
      if (!prevSample) return;
      selectSample(prevSample.id, prevSample.epoch, logPath);
      const url = logSamplesUrl(
        logPath,
        prevSample.id,
        prevSample.epoch,
        sampleTabId
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
    navigate
  ]);
  const onNext = reactExports.useCallback(() => {
    if (hasNext && logPath && currentIndex < sampleSummaries.length - 1) {
      const nextSample = sampleSummaries[currentIndex + 1];
      if (!nextSample) return;
      selectSample(nextSample.id, nextSample.epoch, logPath);
      const url = logSamplesUrl(
        logPath,
        nextSample.id,
        nextSample.epoch,
        sampleTabId
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
    navigate
  ]);
  return {
    onPrevious,
    onNext,
    hasPrevious,
    hasNext
  };
};
export {
  useLogSampleNavigation as a,
  useSamplesGridNavigation as b,
  useSampleDetailNavigation as c,
  useSampleNavigation as u
};
//# sourceMappingURL=sampleNavigation.js.map
