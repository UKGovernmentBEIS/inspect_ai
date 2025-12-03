import { FC, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { kLogViewSamplesTabId } from "../../constants";
import {
  useEvalSpec,
  useFilteredSamples,
  usePrevious,
  useSampleSummaries,
  useTotalSampleCount,
} from "../../state/hooks";
import { useUnloadLog } from "../../state/log";
import { useStore } from "../../state/store";
import { baseUrl, logSamplesUrl, useLogRouteParams } from "../routing/url";
import { LogViewLayout } from "./LogViewLayout";

/**
 * LogContainer component that handles routing to specific logs, tabs, and samples
 */
export const LogViewContainer: FC = () => {
  const { logPath, tabId, sampleUuid, sampleId, epoch, sampleTabId } =
    useLogRouteParams();

  const initialState = useStore((state) => state.app.initialState);
  const clearInitialState = useStore(
    (state) => state.appActions.clearInitialState,
  );
  const evalSpec = useEvalSpec();
  const setSampleTab = useStore((state) => state.appActions.setSampleTab);
  const setShowingSampleDialog = useStore(
    (state) => state.appActions.setShowingSampleDialog,
  );
  const setWorkspaceTab = useStore((state) => state.appActions.setWorkspaceTab);

  const selectSample = useStore((state) => state.logActions.selectSample);
  const setSelectedLogFile = useStore(
    (state) => state.logsActions.setSelectedLogFile,
  );

  const clearSelectedLogSummary = useStore(
    (state) => state.logActions.clearSelectedLogDetails,
  );

  const clearSelectedSample = useStore(
    (state) => state.sampleActions.clearSelectedSample,
  );

  const filteredSamples = useFilteredSamples();
  const totalSampleCount = useTotalSampleCount();
  const navigate = useNavigate();
  const sampleSummaries = useSampleSummaries();
  const [searchParams] = useSearchParams();

  // Unload the log when this is mounted. This prevents the old log
  // data from being displayed when navigating back to the logs panel
  // and also ensures that we reload logs when freshly navigating to them.
  const { unloadLog } = useUnloadLog();
  useEffect(() => {
    return () => {
      unloadLog();
    };
  }, [unloadLog]);

  useEffect(() => {
    // Redirect to an id/epoch url if a sampleUuid is provided
    if (logPath && sampleUuid && sampleSummaries) {
      // Find the sample with the matching UUID
      const sample = sampleSummaries.find((s) => s.uuid === sampleUuid);
      if (sample) {
        const url = logSamplesUrl(
          logPath,
          sample.id,
          sample.epoch,
          sampleTabId,
        );
        const finalUrl = searchParams.toString()
          ? `${url}?${searchParams.toString()}`
          : url;
        navigate(finalUrl);
        return;
      }
    }
  }, [
    sampleSummaries,
    logPath,
    sampleUuid,
    searchParams,
    sampleTabId,
    navigate,
  ]);

  useEffect(() => {
    if (initialState && !evalSpec) {
      const url = baseUrl(
        initialState.log,
        initialState.sample_id,
        initialState.sample_epoch,
      );
      clearInitialState();
      navigate(url);
    }
  }, [initialState, evalSpec, clearInitialState, navigate]);

  const prevLogPath = usePrevious<string | undefined>(logPath);
  const syncLogs = useStore((state) => state.logsActions.syncLogs);
  const initLogDir = useStore((state) => state.logsActions.initLogDir);

  useEffect(() => {
    const loadLogFromPath = async () => {
      if (logPath) {
        await initLogDir();
        setSelectedLogFile(logPath);
        void syncLogs();

        // Set the tab if specified in the URL
        if (tabId) {
          // Only set the tab if it's valid - the LogView component will handle
          // determining if the tab exists before updating the state
          setWorkspaceTab(tabId);
        } else {
          setWorkspaceTab(kLogViewSamplesTabId);
        }

        // Reset the sample
        if (prevLogPath && logPath !== prevLogPath) {
          clearSelectedSample();

          clearSelectedLogSummary();
        }
      }
    };

    loadLogFromPath();
  }, [
    logPath,
    tabId,
    setSelectedLogFile,
    setWorkspaceTab,
    initLogDir,
    syncLogs,
    prevLogPath,
    clearSelectedSample,
    clearSelectedLogSummary,
  ]);

  // Handle sample selection from URL params
  useEffect(() => {
    if (sampleId && filteredSamples) {
      const targetEpoch = epoch ? parseInt(epoch, 10) : 1;
      selectSample(sampleId, targetEpoch);

      // Set the sample tab if specified in the URL
      if (sampleTabId) {
        setSampleTab(sampleTabId);
      }

      if (filteredSamples.length > 1) {
        setShowingSampleDialog(true);
      }
    } else {
      // If we don't have sample params in the URL but the dialog is showing, close it
      // This handles the case when user navigates back from a sample
      setShowingSampleDialog(false);
      if (totalSampleCount > 1) {
        clearSelectedSample();
      }
    }
  }, [
    sampleId,
    epoch,
    sampleTabId,
    filteredSamples,
    totalSampleCount,
    selectSample,
    setSampleTab,
    setShowingSampleDialog,
    clearSelectedSample,
  ]);

  return <LogViewLayout />;
};
