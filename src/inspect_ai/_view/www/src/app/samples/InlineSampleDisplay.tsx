import { FC, useEffect, useRef } from "react";
import { ErrorPanel } from "../../components/ErrorPanel";
import { SampleDisplay } from "./SampleDisplay";

import clsx from "clsx";
import { ActivityBar } from "../../components/ActivityBar";
import { useLogSelection, usePrevious, useSampleData } from "../../state/hooks";
import { useStore } from "../../state/store";
import styles from "./InlineSampleDisplay.module.css";

/**
 * Inline Sample Display
 */
export const InlineSampleDisplay: FC = () => {
  // Sample hooks
  const sampleData = useSampleData();
  const loadSample = useStore((state) => state.sampleActions.loadSample);
  const pollSample = useStore((state) => state.sampleActions.pollSample);
  const logSelection = useLogSelection();

  useEffect(() => {
    if (sampleData.running && logSelection.logFile && logSelection.sample) {
      pollSample(logSelection.logFile, logSelection.sample);
    }
  }, []);

  // Sample Loading
  const prevCompleted = usePrevious(
    logSelection.sample?.completed !== undefined
      ? logSelection.sample.completed
      : true,
  );
  const prevLogFile = usePrevious<string | undefined>(logSelection.loadedLog);
  const prevSampleNeedsReload = usePrevious<number>(
    sampleData.sampleNeedsReload,
  );

  useEffect(() => {
    if (logSelection.logFile && logSelection.sample) {
      const currentSampleCompleted =
        logSelection.sample.completed !== undefined
          ? logSelection.sample.completed
          : true;

      if (
        (prevLogFile !== undefined && prevLogFile !== logSelection.logFile) ||
        sampleData.selectedSampleIdentifier?.id !== logSelection.sample.id ||
        sampleData.selectedSampleIdentifier?.epoch !==
          logSelection.sample.epoch ||
        (prevCompleted !== undefined &&
          currentSampleCompleted !== prevCompleted) ||
        prevSampleNeedsReload !== sampleData.sampleNeedsReload
      ) {
        loadSample(logSelection.logFile, logSelection.sample);
      }
    }
  }, [
    logSelection.logFile,
    logSelection.sample?.id,
    logSelection.sample?.epoch,
    logSelection.sample?.completed,
    sampleData.selectedSampleIdentifier?.id,
    sampleData.selectedSampleIdentifier?.epoch,
    sampleData.sampleNeedsReload,
  ]);

  // Scroll ref
  const scrollRef = useRef<HTMLDivElement>(null);
  return (
    <div className={styles.container}>
      <ActivityBar
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
            <SampleDisplay id={"inline-sample-display"} scrollRef={scrollRef} />
          )}
        </div>
      </div>
    </div>
  );
};
