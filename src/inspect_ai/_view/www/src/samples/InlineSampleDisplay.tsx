import { FC, RefObject, useEffect } from "react";
import { ErrorPanel } from "../components/ErrorPanel";
import { ProgressBar } from "../components/ProgressBar";
import { SampleDisplay } from "./SampleDisplay";

import { useLogSelection, useSampleData } from "../state/hooks";
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
  const sampleData = useSampleData();
  const logSelection = useLogSelection();
  useEffect(() => {
    if (logSelection.logFile && logSelection.sample) {
      sampleData.loadSample(logSelection.logFile, logSelection.sample);
    }
  }, [logSelection.logFile, logSelection.sample]);

  return (
    <div className={styles.container}>
      <ProgressBar animating={sampleData.status === "loading"} />
      <div className={styles.body}>
        {sampleData.error ? (
          <ErrorPanel title="Unable to load sample" error={sampleData.error} />
        ) : (
          <SampleDisplay
            id={id}
            sample={sampleData.sample}
            runningSampleData={sampleData.running}
            selectedTab={selectedTab}
            setSelectedTab={setSelectedTab}
            scrollRef={scrollRef}
          />
        )}
      </div>
    </div>
  );
};
