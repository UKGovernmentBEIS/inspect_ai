import { FC, use, useCallback, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "../../state/store";
import { directoryRelativeUrl } from "../../utils/uri";
import {
  samplesSampleUrl,
  samplesUrl,
  useSamplesRouteParams,
} from "../routing/url";
import { SampleDetailComponent } from "../samples/SampleDetailComponent";

import { useLoadLog } from "../../state/useLoadLog";
import { useLoadSample } from "../../state/useLoadSample";
import { usePollSample } from "../../state/usePollSample";

/**
 * Component that displays a single sample in detail view within the samples route.
 * This is shown when navigating to /samples/path/to/file.eval/sample/id/epoch
 *
 * This component handles:
 * - Loading hooks (useLoadLog, useLoadSample, usePollSample)
 * - Navigation state calculation using displayedSamples from samples grid
 * - Navigation callbacks (handlePrevious, handleNext)
 * - Cleanup on unmount (clears log state since this is a standalone view)
 *
 * Rendering is delegated to SampleDetailComponent.
 */
export const SampleDetailView: FC = () => {
  // Load sample data
  useLoadLog();
  useLoadSample();
  usePollSample();

  // Get route params
  const {
    samplesPath: routeLogPath,
    sampleId,
    epoch,
    tabId,
  } = useSamplesRouteParams();
  const navigate = useNavigate();

  // Get store state for navigation
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const logDir = useStore((state) => state.logs.logDir);
  const displayedSamples = useStore(
    (state) => state.logs.samplesListState.displayedSamples,
  );

  // Cleanup actions
  const clearSelectedLogDetails = useStore(
    (state) => state.logActions.clearSelectedLogDetails,
  );
  const clearLog = useStore((state) => state.logActions.clearLog);
  const clearSampleTab = useStore((state) => state.appActions.clearSampleTab);
  const singleFileMode = useStore((state) => state.app.singleFileMode);

  // Find current sample in displayed samples list
  const currentIndex = useMemo(() => {
    if (!displayedSamples || !selectedLogFile || !sampleId || !epoch) {
      return -1;
    }
    const index = displayedSamples.findIndex((s) => {
      const isMatch =
        String(s.sampleId) === sampleId &&
        s.epoch === parseInt(epoch, 10) &&
        s.logFile === selectedLogFile;
      return isMatch;
    });
    return index;
  }, [displayedSamples, selectedLogFile, sampleId, epoch]);

  const hasPrevious = currentIndex > 0;
  const hasNext =
    displayedSamples &&
    currentIndex >= 0 &&
    currentIndex < displayedSamples.length - 1;

  // Navigation handlers
  const handlePrevious = useCallback(() => {
    if (currentIndex > 0 && displayedSamples && routeLogPath && logDir) {
      const prev = displayedSamples[currentIndex - 1];
      const relativePath = directoryRelativeUrl(prev.logFile, logDir);
      const url = samplesSampleUrl(
        relativePath,
        prev.sampleId,
        prev.epoch,
        tabId,
      );
      navigate(url);
    }
  }, [currentIndex, displayedSamples, routeLogPath, logDir, tabId, navigate]);

  const handleNext = useCallback(() => {
    if (
      displayedSamples &&
      currentIndex >= 0 &&
      currentIndex < displayedSamples.length - 1 &&
      routeLogPath &&
      logDir
    ) {
      const next = displayedSamples[currentIndex + 1];
      const relativePath = directoryRelativeUrl(next.logFile, logDir);
      const url = samplesSampleUrl(
        relativePath,
        next.sampleId,
        next.epoch,
        tabId,
      );
      navigate(url);
    }
  }, [currentIndex, displayedSamples, routeLogPath, logDir, tabId, navigate]);

  // Cleanup on unmount - clear log state since this is a standalone view
  useEffect(() => {
    return () => {
      clearSelectedLogDetails();
      clearLog();
      clearSampleTab();
    };
  }, [clearLog, clearSampleTab, clearSelectedLogDetails]);

  return (
    <SampleDetailComponent
      sampleId={sampleId}
      epoch={epoch}
      tabId={tabId}
      navigation={{
        onPrevious: handlePrevious,
        onNext: handleNext,
        hasPrevious: !!hasPrevious,
        hasNext: !!hasNext,
      }}
      navbarConfig={{
        currentPath: routeLogPath,
        fnNavigationUrl: samplesUrl,
        bordered: true,
        breadcrumbsEnabled: !singleFileMode,
      }}
    />
  );
};
