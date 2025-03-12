import { FC, useEffect, useRef } from "react";
import { ErrorPanel } from "../components/ErrorPanel";
import { SampleDisplay } from "./SampleDisplay";

import clsx from "clsx";
import { ProgressBar } from "../components/ProgressBar";
import { useLogSelection, useSampleData } from "../state/hooks";
import { useStore } from "../state/store";
import styles from "./InlineSampleDisplay.module.css";

interface InlineSampleDisplayProps {
  id: string;
  selectedTab?: string;
  setSelectedTab: (tab: string) => void;
}

/**
 * Inline Sample Display
 */
export const InlineSampleDisplay: FC<InlineSampleDisplayProps> = ({
  id,
  selectedTab,
  setSelectedTab,
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
  const scrollRef = useRef<HTMLDivElement>(null);

  return (
    <div className={styles.container}>
      <ProgressBar
        animating={
          sampleData.status === "loading" || sampleData.status === "streaming"
        }
      />
      <div className={clsx(styles.scroller)} ref={scrollRef}>
        <div className={styles.body}>
          {sampleData.error ? (
            <ErrorPanel
              title="Unable to load sample"
              error={sampleData.error}
            />
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
    </div>
  );
};
