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
import { useStore } from "../../state/store";
import { baseUrl, sampleUrl, useLogRouteParams } from "../routing/url";
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
  const setStatus = useStore((state) => state.appActions.setStatus);
  const setWorkspaceTab = useStore((state) => state.appActions.setWorkspaceTab);

  const refreshLogs = useStore((state) => state.logsActions.refreshLogs);
  const selectLogFile = useStore((state) => state.logsActions.selectLogFile);
  const selectSample = useStore((state) => state.logActions.selectSample);
  const setSelectedLogIndex = useStore(
    (state) => state.logsActions.setSelectedLogIndex,
  );

  const clearSelectedLogSummary = useStore(
    (state) => state.logActions.clearSelectedLogSummary,
  );

  const clearSelectedSample = useStore(
    (state) => state.sampleActions.clearSelectedSample,
  );

  const filteredSamples = useFilteredSamples();
  const totalSampleCount = useTotalSampleCount();
  const navigate = useNavigate();
  const sampleSummaries = useSampleSummaries();
  const [searchParams] = useSearchParams();

  useEffect(() => {
    // Redirect to an id/epoch url if a sampleUuid is provided
    if (logPath && sampleUuid && sampleSummaries) {
      // Find the sample with the matching UUID
      const sample = sampleSummaries.find((s) => s.uuid === sampleUuid);
      if (sample) {
        const url = sampleUrl(logPath, sample.id, sample.epoch, sampleTabId);
        const finalUrl = searchParams.toString()
          ? `${url}?${searchParams.toString()}`
          : url;
        navigate(finalUrl);
        return;
      }
    }
  }, [sampleSummaries, logPath, sampleUuid, searchParams]);

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
  }, [initialState, evalSpec]);

  const prevLogPath = usePrevious<string | undefined>(logPath);

  useEffect(() => {
    const loadLogFromPath = async () => {
      if (logPath) {
        await selectLogFile(logPath);

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
    selectLogFile,
    refreshLogs,
    setWorkspaceTab,
    setSelectedLogIndex,
    setStatus,
  ]);

  // Handle sample selection from URL params
  useEffect(() => {
    if (sampleId && filteredSamples) {
      // Find the sample with matching ID and epoch

      const targetEpoch = epoch ? parseInt(epoch, 10) : undefined;
      const sampleIndex = filteredSamples.findIndex((sample) => {
        const matches =
          String(sample.id) === sampleId &&
          (targetEpoch === undefined || sample.epoch === targetEpoch);
        return matches;
      });

      if (sampleIndex >= 0) {
        selectSample(sampleIndex);
        // Set the sample tab if specified in the URL
        if (sampleTabId) {
          setSampleTab(sampleTabId);
        }

        if (filteredSamples.length > 1) {
          setShowingSampleDialog(true);
        }
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
