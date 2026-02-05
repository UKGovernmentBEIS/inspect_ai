import { FC, useCallback, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { ExtendedFindProvider } from "../../components/ExtendedFindContext";
import { FindBand } from "../../components/FindBand";
import { useStore } from "../../state/store";
import { directoryRelativeUrl } from "../../utils/uri";
import { ApplicationIcons } from "../appearance/icons";
import { ApplicationNavbar } from "../navbar/ApplicationNavbar";
import {
  samplesSampleUrl,
  samplesUrl,
  useSamplesRouteParams,
} from "../routing/url";

import clsx from "clsx";
import { useSampleData } from "../../state/hooks";
import { useLoadLog } from "../../state/useLoadLog";
import { useLoadSample } from "../../state/useLoadSample";
import { usePollSample } from "../../state/usePollSample";
import { InlineSampleComponent } from "../samples/InlineSampleDisplay";
import styles from "./SampleDetailView.module.css";

/**
 * Component that displays a single sample in detail view within the samples route.
 * This is shown when navigating to /samples/path/to/file.eval/sample/id/epoch
 */
export const SampleDetailView: FC = () => {
  useLoadLog();
  useLoadSample();
  usePollSample();

  const {
    samplesPath: routeLogPath,
    sampleId,
    epoch,
    tabId,
  } = useSamplesRouteParams();
  const navigate = useNavigate();

  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const logDir = useStore((state) => state.logs.logDir);
  const displayedSamples = useStore(
    (state) => state.logs.samplesListState.displayedSamples,
  );
  const sampleStatus = useStore((state) => state.sample.sampleStatus);

  const sampleData = useSampleData();
  const sample = useMemo(() => {
    return sampleData.getSelectedSample();
  }, [sampleData]);

  const clearSelectedLogDetails = useStore(
    (state) => state.logActions.clearSelectedLogDetails,
  );
  const clearLog = useStore((state) => state.logActions.clearLog);
  const clearSampleTab = useStore((state) => state.appActions.clearSampleTab);
  const showFind = useStore((state) => state.app.showFind);
  const setSampleTab = useStore((state) => state.appActions.setSampleTab);

  // Find current sample in displayed samples list
  const currentIndex = useMemo(() => {
    if (!displayedSamples || !selectedLogFile || !sampleId || !epoch) {
      return -1;
    }
    return displayedSamples.findIndex(
      (s) =>
        s.sampleId === sampleId &&
        s.epoch === parseInt(epoch, 10) &&
        s.logFile === selectedLogFile,
    );
  }, [displayedSamples, selectedLogFile, sampleId, epoch]);

  const hasPrevious = currentIndex > 0;
  const hasNext =
    displayedSamples &&
    currentIndex >= 0 &&
    currentIndex < displayedSamples.length - 1;

  const setShowFind = useStore((state) => state.appActions.setShowFind);
  const hideFind = useStore((state) => state.appActions.hideFind);
  const nativeFind = useStore((state) => state.app.nativeFind);

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

  useEffect(() => {
    // Set the sample tab if specified in the URL
    if (tabId) {
      setSampleTab(tabId);
    }
  }, [tabId, setSampleTab]);

  // Global keydown handler for keyboard shortcuts
  useEffect(() => {
    const handleGlobalKeyDown = (e: globalThis.KeyboardEvent) => {
      // Don't handle keyboard events if focus is on an input, textarea, or select element
      const activeElement = document.activeElement;
      const isInputFocused =
        activeElement &&
        (activeElement.tagName === "INPUT" ||
          activeElement.tagName === "TEXTAREA" ||
          activeElement.tagName === "SELECT");

      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        if (!nativeFind) {
          e.preventDefault(); // Always prevent browser find
          e.stopPropagation();
          if (setShowFind) {
            setShowFind(true);
          }
        }
      } else if (e.key === "Escape") {
        if (!nativeFind) {
          hideFind();
        }
      } else if (!isInputFocused) {
        // Navigation shortcuts (only when not in an input field)
        if (e.key === "ArrowLeft") {
          if (hasPrevious) {
            e.preventDefault();
            handlePrevious();
          }
        } else if (e.key === "ArrowRight") {
          if (hasNext) {
            e.preventDefault();
            handleNext();
          }
        }
      }
    };

    // Use capture phase to catch event before it reaches other handlers
    document.addEventListener("keydown", handleGlobalKeyDown, true);

    return () => {
      document.removeEventListener("keydown", handleGlobalKeyDown, true);
    };
  }, [
    setShowFind,
    hideFind,
    hasPrevious,
    hasNext,
    nativeFind,
    handlePrevious,
    handleNext,
  ]);

  useEffect(() => {
    return () => {
      clearSelectedLogDetails();
      clearLog();
      clearSampleTab();
    };
  }, [clearLog, clearSampleTab, clearSelectedLogDetails]);

  return (
    <ExtendedFindProvider>
      {showFind ? <FindBand /> : ""}
      <div className={styles.detail}>
        <ApplicationNavbar
          currentPath={routeLogPath}
          fnNavigationUrl={samplesUrl}
          bordered={true}
        >
          <div className={clsx(styles.sampleNav)}>
            <div
              onClick={handlePrevious}
              tabIndex={0}
              className={clsx(!hasPrevious && styles.disabled, styles.nav)}
            >
              <i className={clsx(ApplicationIcons.previous)} />
            </div>
            <div className={clsx(styles.sampleInfo, "text-size-smallest")}>
              Sample {sampleId} (Epoch {epoch})
            </div>
            <div
              onClick={handleNext}
              tabIndex={0}
              className={clsx(!hasNext && styles.disabled, styles.nav)}
            >
              <i className={clsx(ApplicationIcons.next)} />
            </div>
          </div>
        </ApplicationNavbar>

        {sampleStatus !== "loading" && sample && (
          <InlineSampleComponent
            showActivity={false}
            className={styles.panel}
          />
        )}
      </div>
    </ExtendedFindProvider>
  );
};
