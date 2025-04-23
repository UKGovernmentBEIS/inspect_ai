import { FC, useEffect, useRef } from "react";
import { ErrorPanel } from "../../components/ErrorPanel";
import { SampleDisplay } from "./SampleDisplay";

import clsx from "clsx";
import { ProgressBar } from "../../components/ProgressBar";
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
  useEffect(() => {
    if (logSelection.logFile && logSelection.sample) {
      const currentSampleCompleted =
        logSelection.sample?.completed !== undefined
          ? logSelection.sample.completed
          : true;

      if (
        (prevLogFile !== undefined && prevLogFile !== logSelection.loadedLog) ||
        sampleData.sample?.id !== logSelection.sample.id ||
        sampleData.sample?.epoch !== logSelection.sample.epoch ||
        (prevCompleted !== undefined &&
          currentSampleCompleted !== prevCompleted)
      ) {
        loadSample(logSelection.logFile, logSelection.sample);
      }
    }
  }, [
    logSelection.loadedLog,
    logSelection.sample?.id,
    logSelection.sample?.epoch,
    logSelection.sample?.completed,
    sampleData.sample?.id,
    sampleData.sample?.epoch,
  ]);

  // Scroll ref
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
            <SampleDisplay id={"inline-sample-display"} scrollRef={scrollRef} />
          )}
        </div>
      </div>
    </div>
  );
};
