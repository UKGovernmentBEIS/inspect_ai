import { c as useLogRouteParams, a as useNavigate, u as useStore, D as logSamplesUrl, l as logsUrl, j as jsxRuntimeExports, y as kLogViewSamplesTabId } from "./index.js";
import { b as reactExports } from "./vendor-grid.js";
import { U as useSampleSummaries } from "./ApplicationNavbar.js";
import { u as useLoadSample, e as usePollSample } from "./InlineSampleDisplay.js";
import { a as useLogSampleNavigation } from "./sampleNavigation.js";
import { S as SampleDetailComponent } from "./SampleDetailComponent.js";
import "./vendor-prism.js";
import "./vendor-asciinema.js";
const LogSampleDetailView = () => {
  const {
    logPath: routeLogPath,
    sampleId: routeSampleId,
    epoch: routeEpoch,
    sampleTabId,
    sampleUuid
  } = useLogRouteParams();
  useLoadSample();
  usePollSample();
  const navigate = useNavigate();
  const initLogDir = useStore((state) => state.logsActions.initLogDir);
  const sampleSummaries = useSampleSummaries();
  const setSelectedLogFile = useStore(
    (state) => state.logsActions.setSelectedLogFile
  );
  const syncLogs = useStore((state) => state.logsActions.syncLogs);
  const selectSample = useStore((state) => state.logActions.selectSample);
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const selectedSampleHandle = useStore(
    (state) => state.log.selectedSampleHandle
  );
  const singleFileMode = useStore((state) => state.app.singleFileMode);
  const logPath = routeLogPath || selectedLogFile;
  const sampleId = routeSampleId || selectedSampleHandle?.id?.toString();
  const epoch = routeEpoch || selectedSampleHandle?.epoch?.toString();
  reactExports.useEffect(() => {
    const loadLogAndSample = async () => {
      if (routeLogPath && routeSampleId && routeEpoch) {
        await initLogDir();
        setSelectedLogFile(routeLogPath);
        void syncLogs();
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
    selectSample
  ]);
  reactExports.useEffect(() => {
    if (logPath && sampleUuid && sampleSummaries && sampleSummaries.length > 0) {
      const sample = sampleSummaries.find((s) => s.uuid === sampleUuid);
      if (sample) {
        const url = logSamplesUrl(
          logPath,
          sample.id,
          sample.epoch,
          sampleTabId
        );
        navigate(url, { replace: true });
      }
    }
  }, [logPath, sampleUuid, sampleSummaries, sampleTabId, navigate]);
  const { onPrevious, onNext, hasPrevious, hasNext } = useLogSampleNavigation();
  const fnNavigationUrl = reactExports.useCallback(
    (file, log_dir) => {
      if (!logPath || !file) {
        return logsUrl(file, log_dir);
      }
      const normalizedFile = file.endsWith("/") ? file.slice(0, -1) : file;
      if (normalizedFile === logPath || normalizedFile === `${logPath}/sample`) {
        return logsUrl(logPath, log_dir, kLogViewSamplesTabId);
      }
      return logsUrl(file, log_dir);
    },
    [logPath]
  );
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    SampleDetailComponent,
    {
      sampleId,
      epoch,
      tabId: sampleTabId,
      navigation: {
        onPrevious,
        onNext,
        hasPrevious,
        hasNext
      },
      navbarConfig: {
        // Add sample identifier to path so log file becomes clickable
        // (breadcrumbs don't make the last segment a link)
        currentPath: logPath ? `${logPath}/sample` : void 0,
        fnNavigationUrl,
        bordered: true,
        breadcrumbsEnabled: !singleFileMode
      }
    }
  );
};
export {
  LogSampleDetailView
};
//# sourceMappingURL=LogSampleDetailView.js.map
