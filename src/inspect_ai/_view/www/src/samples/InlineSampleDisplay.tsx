import { FC, RefObject, useEffect } from "react";
import { ErrorPanel } from "../components/ErrorPanel";
import { ProgressBar } from "../components/ProgressBar";
import { SampleDisplay } from "./SampleDisplay";

import { useLogSelection, useSampleData } from "../state/hooks";
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
  const sampleData = useSampleData();
  const loadSample = useStore((state) => state.sampleActions.loadSample);
  const logSelection = useLogSelection();
  useEffect(() => {
    if (logSelection.logFile && logSelection.sample) {
      if (
        sampleData.sample?.id !== logSelection.sample.id ||
        sampleData.sample.epoch !== logSelection.sample.epoch
      ) {
        loadSample(logSelection.logFile, logSelection.sample);
      }
    }
  }, [
    logSelection.logFile,
    logSelection.sample?.id,
    logSelection.sample?.epoch,
    sampleData.sample?.id,
    sampleData.sample?.epoch,
  ]);

  return (
    <div className={styles.container}>
      <ProgressBar
        animating={
          sampleData.status === "loading" || sampleData.status === "streaming"
        }
      />
      <div className={styles.body}>
        {sampleData.error ? (
          <ErrorPanel title="Unable to load sample" error={sampleData.error} />
        ) : (
          <SampleDisplay
            id={id}
            sample={sampleData.sample}
            runningEvents={sampleData.running}
            selectedTab={selectedTab}
            setSelectedTab={setSelectedTab}
            scrollRef={scrollRef}
          />
        )}
      </div>
    </div>
  );
};
