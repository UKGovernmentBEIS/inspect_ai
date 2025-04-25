import { FC, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { kLogViewSamplesTabId } from "../../constants";
import { useFilteredSamples, useTotalSampleCount } from "../../state/hooks";
import { useStore } from "../../state/store";
import { baseUrl } from "../routing/url";
import { LogViewLayout } from "./LogViewLayout";

/**
 * LogContainer component that handles routing to specific logs, tabs, and samples
 */
export const LogViewContainer: FC = () => {
  const { logPath, tabId, sampleId, epoch, sampleTabId } = useParams<{
    logPath?: string;
    tabId?: string;
    sampleId?: string;
    epoch?: string;
    sampleTabId?: string;
  }>();
  const selectLogFile = useStore((state) => state.logsActions.selectLogFile);
  const refreshLogs = useStore((state) => state.logsActions.refreshLogs);
  const setWorkspaceTab = useStore((state) => state.appActions.setWorkspaceTab);
  const setShowingSampleDialog = useStore(
    (state) => state.appActions.setShowingSampleDialog,
  );
  const selectSample = useStore((state) => state.logActions.selectSample);
  const setSampleTab = useStore((state) => state.appActions.setSampleTab);
  const filteredSamples = useFilteredSamples();
  const totalSampleCount = useTotalSampleCount();
  const setStatus = useStore((state) => state.appActions.setStatus);
  const setSelectedLogIndex = useStore(
    (state) => state.logsActions.setSelectedLogIndex,
  );

  const selectedLogIndex = useStore((state) => state.logs.selectedLogIndex);
  const initialState = useStore((state) => state.app.initialState);
  const clearInitialState = useStore(
    (state) => state.appActions.clearInitialState,
  );
  const navigate = useNavigate();

  useEffect(() => {
    if (initialState) {
      const url = baseUrl(
        initialState.log,
        initialState.sample_id,
        initialState.sample_epoch,
      );
      clearInitialState();
      navigate(url);
    }
  }, [initialState]);

  useEffect(() => {
    const loadLogFromPath = async () => {
      if (logPath) {
        await selectLogFile(decodeURIComponent(logPath));

        // Set the tab if specified in the URL
        if (tabId) {
          // Only set the tab if it's valid - the LogView component will handle
          // determining if the tab exists before updating the state
          setWorkspaceTab(tabId);
        } else {
          setWorkspaceTab(kLogViewSamplesTabId);
        }
      } else {
        setStatus({
          loading: true,
          error: undefined,
        });

        // Reset the log/task tab
        setSelectedLogIndex(-1);
        setWorkspaceTab(kLogViewSamplesTabId);

        // Refresh the list of logs
        await refreshLogs();

        // Select the first log in the list
        setSelectedLogIndex(0);

        if (!sampleId) {
          selectSample(0);
        }

        setStatus({
          loading: false,
          error: undefined,
        });
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

  const clearSample = useStore(
    (state) => state.sampleActions.clearSelectedSample,
  );

  useEffect(() => {
    if (selectedLogIndex > -1) {
      selectSample(0);
    }
  }, [selectedLogIndex]);

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
        clearSample();
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
    clearSample,
  ]);

  return <LogViewLayout />;
};
