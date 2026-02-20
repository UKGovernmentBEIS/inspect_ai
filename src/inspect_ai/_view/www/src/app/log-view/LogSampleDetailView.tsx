import { FC, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { kLogViewSamplesTabId } from "../../constants";
import { useSampleSummaries } from "../../state/hooks";
import { useStore } from "../../state/store";
import { useLoadSample } from "../../state/useLoadSample";
import { usePollSample } from "../../state/usePollSample";
import { useLogSampleNavigation } from "../routing/sampleNavigation";
import { logSamplesUrl, logsUrl, useLogRouteParams } from "../routing/url";
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
  const {
    logPath: routeLogPath,
    sampleId: routeSampleId,
    epoch: routeEpoch,
    sampleTabId,
    sampleUuid,
  } = useLogRouteParams();

  // Load sample data (depends on selectedLogFile and selectedSampleHandle being set)
  useLoadSample();
  usePollSample();

  const navigate = useNavigate();

  // Get store state and actions for log loading
  const initLogDir = useStore((state) => state.logsActions.initLogDir);
  const sampleSummaries = useSampleSummaries();
  const setSelectedLogFile = useStore(
    (state) => state.logsActions.setSelectedLogFile,
  );
  const syncLogs = useStore((state) => state.logsActions.syncLogs);
  const selectSample = useStore((state) => state.logActions.selectSample);

  // Fall back to state for VSCode restored state scenario
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const selectedSampleHandle = useStore(
    (state) => state.log.selectedSampleHandle,
  );
  const singleFileMode = useStore((state) => state.app.singleFileMode);

  // Use route params if available, otherwise fall back to state
  const logPath = routeLogPath || selectedLogFile;
  const sampleId = routeSampleId || selectedSampleHandle?.id?.toString();
  const epoch = routeEpoch || selectedSampleHandle?.epoch?.toString();

  // Load the log and select the sample when route params change
  // Only run this effect when we have route params (not state fallback)
  useEffect(() => {
    const loadLogAndSample = async () => {
      if (routeLogPath && routeSampleId && routeEpoch) {
        // Initialize log directory if needed
        await initLogDir();

        // Set the selected log file
        setSelectedLogFile(routeLogPath);

        // Sync logs to ensure we have the latest data
        void syncLogs();

        // Select the sample
        const targetEpoch = parseInt(routeEpoch, 10);
        if (isNaN(targetEpoch)) {
          return;
        }

        selectSample(routeSampleId, targetEpoch, routeLogPath);
      }
    };

    void loadLogAndSample();
  }, [
    routeLogPath,
    routeSampleId,
    routeEpoch,
    initLogDir,
    setSelectedLogFile,
    syncLogs,
    selectSample,
  ]);

  // Handle UUID routes by redirecting to id/epoch URL
  useEffect(() => {
    if (
      logPath &&
      sampleUuid &&
      sampleSummaries &&
      sampleSummaries.length > 0
    ) {
      // Find the sample with the matching UUID
      const sample = sampleSummaries.find((s) => s.uuid === sampleUuid);
      if (sample) {
        const url = logSamplesUrl(
          logPath,
          sample.id,
          sample.epoch,
          sampleTabId,
        );
        navigate(url, { replace: true });
      }
    }
  }, [logPath, sampleUuid, sampleSummaries, sampleTabId, navigate]);

  // Get navigation handlers from the hook
  const { onPrevious, onNext, hasPrevious, hasNext } = useLogSampleNavigation();

  // Custom navigation URL function for breadcrumbs and back button.
  // We use currentPath = `${logPath}/sample` so the log file becomes clickable.
  // - Back button: dirname of "logPath/sample" is "logPath", goes to log's samples tab
  // - Home button: goes to root
  // - Log file breadcrumb: goes to log's samples tab
  // - Parent folder breadcrumbs: go to those folders
  const fnNavigationUrl = useCallback(
    (file: string, log_dir?: string) => {
      if (!logPath || !file) {
        // Empty file = home button, go to root
        return logsUrl(file, log_dir);
      }

      // Normalize: remove trailing slash for comparison
      const normalizedFile = file.endsWith("/") ? file.slice(0, -1) : file;

      // If clicking the log file itself or the virtual "sample" path,
      // go to log's samples tab
      if (
        normalizedFile === logPath ||
        normalizedFile === `${logPath}/sample`
      ) {
        return logsUrl(logPath, log_dir, kLogViewSamplesTabId);
      }

      // Otherwise, use the default logsUrl behavior (for parent folders)
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
        // Add sample identifier to path so log file becomes clickable
        // (breadcrumbs don't make the last segment a link)
        currentPath: logPath ? `${logPath}/sample` : undefined,
        fnNavigationUrl,
        bordered: true,
        breadcrumbsEnabled: !singleFileMode,
      }}
    />
  );
};
