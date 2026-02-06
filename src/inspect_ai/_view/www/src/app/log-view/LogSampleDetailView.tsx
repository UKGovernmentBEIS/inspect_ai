import { FC, useCallback, useEffect } from "react";
import { kLogViewSamplesTabId } from "../../constants";
import { useStore } from "../../state/store";
import { useLoadSample } from "../../state/useLoadSample";
import { usePollSample } from "../../state/usePollSample";
import { useLogRouteParams, logsUrl } from "../routing/url";
import { useLogSampleNavigation } from "../routing/sampleNavigation";
import { SampleDetailComponent } from "../samples/SampleDetailComponent";

/**
 * Component that displays a single sample in detail view within the logs route.
 * This is shown when navigating to /logs/path/to/file.eval/samples/sample/id/epoch
 *
 * This component handles:
 * - Log loading (initLogDir, setSelectedLogFile, syncLogs)
 * - Sample selection and loading (useLoadSample, usePollSample)
 * - Navigation state via useLogSampleNavigation (respects log filters)
 *
 * Unlike SampleDetailView, this component:
 * - Does NOT clear log state on unmount (user expects to return to same log state)
 * - Uses filteredSamples for navigation (respects current log filters)
 * - Navigates back to log view rather than samples grid
 *
 * Rendering is delegated to SampleDetailComponent.
 */
export const LogSampleDetailView: FC = () => {
  // Get route params
  const { logPath, sampleId, epoch, sampleTabId } = useLogRouteParams();

  // Get store actions for log loading
  const initLogDir = useStore((state) => state.logsActions.initLogDir);
  const setSelectedLogFile = useStore(
    (state) => state.logsActions.setSelectedLogFile,
  );
  const syncLogs = useStore((state) => state.logsActions.syncLogs);
  const selectSample = useStore((state) => state.logActions.selectSample);

  // Load the log and select the sample when route params change
  useEffect(() => {
    const loadLogAndSample = async () => {
      if (logPath && sampleId && epoch) {
        // Initialize log directory if needed
        await initLogDir();

        // Set the selected log file
        setSelectedLogFile(logPath);

        // Sync logs to ensure we have the latest data
        void syncLogs();

        // Select the sample
        const targetEpoch = parseInt(epoch, 10);
        selectSample(sampleId, targetEpoch, logPath);
      }
    };

    loadLogAndSample();
  }, [
    logPath,
    sampleId,
    epoch,
    initLogDir,
    setSelectedLogFile,
    syncLogs,
    selectSample,
  ]);

  // Load sample data (depends on selectedLogFile and selectedSampleHandle being set)
  useLoadSample();
  usePollSample();

  // Get navigation handlers from the hook
  const { onPrevious, onNext, hasPrevious, hasNext } = useLogSampleNavigation();

  // Custom navigation URL function that returns to the log's samples tab
  // when navigating back from a sample detail view.
  // The navbar uses dirname(currentPath) for the back button, so when the
  // path is "metr/file.eval", dirname returns "metr/". We want to go to
  // the log's samples tab instead (logsUrl("metr/file.eval", logDir, "samples")).
  // The home button uses fnNavigationUrl("", logDir) which should go to root.
  const fnNavigationUrl = useCallback(
    (file: string, log_dir?: string) => {
      // Detect if this is the back button trying to go to the parent directory.
      // The back button passes ensureTrailingSlash(dirname(logPath)).
      // For "metr/file.eval", that's "metr/".
      // We want to redirect this to the log's samples tab instead.
      if (logPath && file) {
        // Normalize: remove trailing slash for comparison
        const normalizedFile = file.endsWith("/") ? file.slice(0, -1) : file;
        const logDir = logPath.includes("/")
          ? logPath.substring(0, logPath.lastIndexOf("/"))
          : "";

        // If the file matches the parent directory of the log path,
        // redirect to the log's samples tab
        if (normalizedFile === logDir) {
          return logsUrl(logPath, log_dir, kLogViewSamplesTabId);
        }
      }
      // Otherwise, use the default logsUrl behavior
      return logsUrl(file, log_dir);
    },
    [logPath],
  );

  return (
    <SampleDetailComponent
      sampleId={sampleId}
      epoch={epoch}
      tabId={sampleTabId}
      navigation={{
        onPrevious,
        onNext,
        hasPrevious,
        hasNext,
      }}
      navbarConfig={{
        currentPath: logPath,
        fnNavigationUrl,
        bordered: true,
      }}
    />
  );
};
