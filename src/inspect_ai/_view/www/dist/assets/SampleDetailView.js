import { J as useSamplesRouteParams, u as useStore, a as useNavigate, e as directoryRelativeUrl, M as samplesSampleUrl, j as jsxRuntimeExports, I as samplesUrl } from "./index.js";
import { b as reactExports } from "./vendor-grid.js";
import { S as SampleDetailComponent } from "./SampleDetailComponent.js";
import { b as useLogs } from "./ApplicationNavbar.js";
import { u as useLoadSample, e as usePollSample } from "./InlineSampleDisplay.js";
import "./vendor-prism.js";
import "./sampleNavigation.js";
import "./vendor-asciinema.js";
const useLoadLog = () => {
  const {
    samplesPath: routeLogPath,
    sampleId,
    epoch
  } = useSamplesRouteParams();
  const { loadLogs } = useLogs();
  const initLogDir = useStore((state) => state.logsActions.initLogDir);
  const selectSample = useStore((state) => state.logActions.selectSample);
  const logs = useStore((state) => state.logs.logs);
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const logDir = useStore((state) => state.logs.logDir);
  const setSelectedLogFile = useStore(
    (state) => state.logsActions.setSelectedLogFile
  );
  reactExports.useEffect(() => {
    const exec = async () => {
      if (routeLogPath && sampleId && epoch) {
        if (!logDir) {
          await initLogDir();
        }
        if (!logs.some((log) => log.name.endsWith(routeLogPath))) {
          await loadLogs(routeLogPath);
        }
        if (selectedLogFile !== routeLogPath) {
          setSelectedLogFile(routeLogPath);
        }
        const targetEpoch = parseInt(epoch, 10);
        selectSample(sampleId, targetEpoch, routeLogPath);
      }
    };
    exec();
  }, [
    routeLogPath,
    sampleId,
    epoch,
    loadLogs,
    setSelectedLogFile,
    selectSample,
    initLogDir,
    logDir,
    logs,
    selectedLogFile
  ]);
};
const SampleDetailView = () => {
  useLoadLog();
  useLoadSample();
  usePollSample();
  const {
    samplesPath: routeLogPath,
    sampleId,
    epoch,
    tabId
  } = useSamplesRouteParams();
  const navigate = useNavigate();
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const logDir = useStore((state) => state.logs.logDir);
  const displayedSamples = useStore(
    (state) => state.logs.samplesListState.displayedSamples
  );
  const clearSelectedLogDetails = useStore(
    (state) => state.logActions.clearSelectedLogDetails
  );
  const clearLog = useStore((state) => state.logActions.clearLog);
  const clearSampleTab = useStore((state) => state.appActions.clearSampleTab);
  const singleFileMode = useStore((state) => state.app.singleFileMode);
  const currentIndex = reactExports.useMemo(() => {
    if (!displayedSamples || !selectedLogFile || !sampleId || !epoch) {
      return -1;
    }
    const index = displayedSamples.findIndex((s) => {
      const isMatch = String(s.sampleId) === sampleId && s.epoch === parseInt(epoch, 10) && s.logFile === selectedLogFile;
      return isMatch;
    });
    return index;
  }, [displayedSamples, selectedLogFile, sampleId, epoch]);
  const hasPrevious = currentIndex > 0;
  const hasNext = displayedSamples && currentIndex >= 0 && currentIndex < displayedSamples.length - 1;
  const handlePrevious = reactExports.useCallback(() => {
    if (currentIndex > 0 && displayedSamples && routeLogPath && logDir) {
      const prev = displayedSamples[currentIndex - 1];
      const relativePath = directoryRelativeUrl(prev.logFile, logDir);
      const url = samplesSampleUrl(
        relativePath,
        prev.sampleId,
        prev.epoch,
        tabId
      );
      navigate(url);
    }
  }, [currentIndex, displayedSamples, routeLogPath, logDir, tabId, navigate]);
  const handleNext = reactExports.useCallback(() => {
    if (displayedSamples && currentIndex >= 0 && currentIndex < displayedSamples.length - 1 && routeLogPath && logDir) {
      const next = displayedSamples[currentIndex + 1];
      const relativePath = directoryRelativeUrl(next.logFile, logDir);
      const url = samplesSampleUrl(
        relativePath,
        next.sampleId,
        next.epoch,
        tabId
      );
      navigate(url);
    }
  }, [currentIndex, displayedSamples, routeLogPath, logDir, tabId, navigate]);
  reactExports.useEffect(() => {
    return () => {
      clearSelectedLogDetails();
      clearLog();
      clearSampleTab();
    };
  }, [clearLog, clearSampleTab, clearSelectedLogDetails]);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    SampleDetailComponent,
    {
      sampleId,
      epoch,
      tabId,
      navigation: {
        onPrevious: handlePrevious,
        onNext: handleNext,
        hasPrevious: !!hasPrevious,
        hasNext: !!hasNext
      },
      navbarConfig: {
        currentPath: routeLogPath,
        fnNavigationUrl: samplesUrl,
        bordered: true,
        breadcrumbsEnabled: !singleFileMode
      }
    }
  );
};
export {
  SampleDetailView
};
//# sourceMappingURL=SampleDetailView.js.map
