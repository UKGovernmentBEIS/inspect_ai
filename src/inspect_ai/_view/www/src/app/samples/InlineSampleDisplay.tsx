import { FC, useEffect, useRef } from "react";
import { ErrorPanel } from "../../components/ErrorPanel";
import { SampleDisplay } from "./SampleDisplay";

import clsx from "clsx";
import { ActivityBar } from "../../components/ActivityBar";
import { useLogSelection, usePrevious, useSampleData } from "../../state/hooks";
import { useStore } from "../../state/store";
import styles from "./InlineSampleDisplay.module.css";

interface InlineSampleDisplayProps {
  showActivity?: boolean;
  className?: string | string[];
}

/**
 * Inline Sample Display
 */
export const InlineSampleDisplay: FC<InlineSampleDisplayProps> = ({
  showActivity,
  className,
}) => {
  // Sample hooks
  const sampleData = useSampleData();
  const loadSample = useStore((state) => state.sampleActions.loadSample);
  const pollSample = useStore((state) => state.sampleActions.pollSample);
  const logSelection = useLogSelection();

  useEffect(() => {
    if (sampleData.running && logSelection.logFile && logSelection.sample) {
      pollSample(logSelection.logFile, logSelection.sample);
    }
  }, [
    logSelection.logFile,
    logSelection.sample,
    pollSample,
    sampleData.running,
  ]);

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
    logSelection.sample,
    prevLogFile,
    prevCompleted,
    prevSampleNeedsReload,
    loadSample,
  ]);

  // Scroll ref
  const scrollRef = useRef<HTMLDivElement>(null);
  return (
    <div className={clsx(className, styles.container)}>
      {showActivity && (
        <ActivityBar
          animating={
            sampleData.status === "loading" || sampleData.status === "streaming"
          }
        />
      )}
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
