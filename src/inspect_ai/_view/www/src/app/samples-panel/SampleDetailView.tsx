import clsx from "clsx";
import { FC, useEffect } from "react";
import { ExtendedFindProvider } from "../../components/ExtendedFindContext";
import { useLogs, useSelectedSampleSummary } from "../../state/hooks";
import { useStore } from "../../state/store";
import { ApplicationNavbar } from "../navbar/ApplicationNavbar";
import { samplesUrl, useSamplesRouteParams } from "../routing/url";
import { SampleDisplay } from "../samples/SampleDisplay";
import styles from "./SampleDetailView.module.css";

/**
 * Component that displays a single sample in detail view within the samples route.
 * This is shown when navigating to /samples/path/to/file.eval/sample/id/epoch
 */
export const SampleDetailView: FC = () => {
  const { samplesPath, sampleId, epoch } = useSamplesRouteParams();
  const { loadLogs } = useLogs();

  const selectSample = useStore((state) => state.logActions.selectSample);
  const setSelectedLogFile = useStore(
    (state) => state.logsActions.setSelectedLogFile,
  );
  const selectedSampleSummary = useSelectedSampleSummary();
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);
  const initLogDir = useStore((state) => state.logsActions.initLogDir);

  const loadSample = useStore((state) => state.sampleActions.loadSample);
  const clearSelectedSample = useStore(
    (state) => state.sampleActions.clearSelectedSample,
  );
  const clearSelectedLogDetails = useStore(
    (state) => state.logActions.clearSelectedLogDetails,
  );
  const clearLog = useStore((state) => state.logActions.clearLog);

  // Load the log file and select the sample
  useEffect(() => {
    const exec = async () => {
      if (samplesPath && sampleId && epoch) {
        await initLogDir();
        // Load the log file
        await loadLogs(samplesPath);
        setSelectedLogFile(samplesPath);

        // Select the specific sample
        const targetEpoch = parseInt(epoch, 10);
        selectSample(sampleId, targetEpoch);
      }
    };

    exec();
  }, [
    samplesPath,
    sampleId,
    epoch,
    loadLogs,
    setSelectedLogFile,
    selectSample,
  ]);

  useEffect(() => {
    const exec = async () => {
      if (selectedLogFile && selectedSampleSummary) {
        await loadSample(selectedLogFile, selectedSampleSummary);
      }
    };
    void exec();
  }, [selectedLogFile, selectedSampleSummary]);

  useEffect(() => {
    return () => {
      // Clear selected sample on unmount
      clearSelectedSample();
      clearSelectedLogDetails();
      clearLog();
    };
  }, [clearLog, clearSelectedSample, clearSelectedLogDetails]);

  return (
    <ExtendedFindProvider>
      <div className={clsx(styles.panel)}>
        <ApplicationNavbar
          currentPath={samplesPath}
          fnNavigationUrl={samplesUrl}
          bordered={true}
        />

        <div className={clsx(styles.detail)}>
          {sampleId && (
            <SampleDisplay
              id={`sample-detail-${sampleId}-${epoch}`}
              scrollRef={{ current: null }}
              focusOnLoad={true}
            />
          )}
        </div>
      </div>
    </ExtendedFindProvider>
  );
};
