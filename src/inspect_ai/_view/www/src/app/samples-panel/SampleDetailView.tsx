import clsx from "clsx";
import { FC, useEffect } from "react";
import { useLogs } from "../../state/hooks";
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

  // Load the log file and select the sample
  useEffect(() => {
    const loadSample = async () => {
      if (samplesPath && sampleId && epoch) {
        // Load the log file
        await loadLogs(samplesPath);
        setSelectedLogFile(samplesPath);

        // Select the specific sample
        const targetEpoch = parseInt(epoch, 10);
        selectSample(sampleId, targetEpoch);
      }
    };

    loadSample();
  }, [
    samplesPath,
    sampleId,
    epoch,
    loadLogs,
    setSelectedLogFile,
    selectSample,
  ]);

  return (
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
  );
};
