import { FC, useEffect } from "react";
import { useParams } from "react-router";
import { kLogViewSamplesTabId } from "../../constants";
import { useFilteredSamples } from "../../state/hooks";
import { useStore } from "../../state/store";
import { LogViewLayout } from "./LogViewLayout";

/**
 * LogContainer component that handles routing to specific logs, tabs, and samples
 */
export const LogViewContainer: FC = () => {
  const { logPath, tabId, sampleId, epoch } = useParams<{
    logPath?: string;
    tabId?: string;
    sampleId?: string;
    epoch?: string;
  }>();
  const selectLogFile = useStore((state) => state.logsActions.selectLogFile);
  const refreshLogs = useStore((state) => state.logsActions.refreshLogs);
  const setWorkspaceTab = useStore((state) => state.appActions.setWorkspaceTab);
  const setShowingSampleDialog = useStore(
    (state) => state.appActions.setShowingSampleDialog,
  );
  const selectSample = useStore((state) => state.logActions.selectSample);
  const filteredSamples = useFilteredSamples();

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
        await refreshLogs();
        setWorkspaceTab(kLogViewSamplesTabId);
      }
    };

    loadLogFromPath();
  }, [logPath, tabId, selectLogFile, refreshLogs, setWorkspaceTab]);

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
        setShowingSampleDialog(true);
      }
    } else {
      // If we don't have sample params in the URL but the dialog is showing, close it
      // This handles the case when user navigates back from a sample
      setShowingSampleDialog(false);
    }
  }, [sampleId, epoch, filteredSamples, selectSample, setShowingSampleDialog]);

  return <LogViewLayout />;
};
