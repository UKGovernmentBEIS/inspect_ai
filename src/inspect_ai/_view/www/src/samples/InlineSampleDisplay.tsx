import { FC, RefObject, useEffect } from "react";
import { ErrorPanel } from "../components/ErrorPanel";
import { ProgressBar } from "../components/ProgressBar";
import { SampleDisplay } from "./SampleDisplay";

import { useSelectedSampleSummary } from "../state/logStore";
import { useLoadSample, useSampleStore } from "../state/sampleStore";
import { useStore } from "../state/store";
import styles from "./InlineSampleDisplay.module.css";

interface InlineSampleDisplayProps {
  id: string;
  selectedTab?: string;
  setSelectedTab: (tab: string) => void;
  scrollRef: RefObject<HTMLDivElement | null>;
}

/**
 * Inline Sample Display
 */
export const InlineSampleDisplay: FC<InlineSampleDisplayProps> = ({
  id,
  selectedTab,
  setSelectedTab,
  scrollRef,
}) => {
  const sampleStatus = useSampleStore((state) => state.sampleStatus);
  const sampleError = useSampleStore((state) => state.sampleError);
  const selectedSample = useSampleStore((state) => state.selectedSample);
  const runningSampleData = useSampleStore((state) => state.runningSampleData);
  const selectedSampleSummary = useSelectedSampleSummary();
  const loadSample = useLoadSample();
  const selectedLogFile = useStore((state) =>
    state.logsActions.getSelectedLogFile(),
  );

  useEffect(() => {
    if (selectedLogFile && selectedSampleSummary) {
      loadSample(selectedLogFile, selectedSampleSummary);
    }
  }, [selectedSampleSummary]);

  return (
    <div className={styles.container}>
      <ProgressBar animating={sampleStatus === "loading"} />
      <div className={styles.body}>
        {sampleError ? (
          <ErrorPanel title="Unable to load sample" error={sampleError} />
        ) : (
          <SampleDisplay
            id={id}
            sample={selectedSample}
            runningSampleData={runningSampleData}
            selectedTab={selectedTab}
            setSelectedTab={setSelectedTab}
            scrollRef={scrollRef}
          />
        )}
      </div>
    </div>
  );
};
