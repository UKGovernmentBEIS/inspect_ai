import { FC, useRef } from "react";
import { ErrorPanel } from "../../components/ErrorPanel";
import { SampleDisplay } from "./SampleDisplay";

import clsx from "clsx";
import { ActivityBar } from "../../components/ActivityBar";
import { useSampleData } from "../../state/hooks";
import { useSampleLoader } from "../../state/useSampleLoader";
import { useSamplePolling } from "../../state/useSamplePolling";
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

  // Use shared hooks for loading and polling
  useSampleLoader();
  useSamplePolling();

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
