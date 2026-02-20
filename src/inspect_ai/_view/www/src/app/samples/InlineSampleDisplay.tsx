import { FC, useRef } from "react";
import { ErrorPanel } from "../../components/ErrorPanel";
import { SampleDisplay } from "./SampleDisplay";

import clsx from "clsx";
import { ActivityBar } from "../../components/ActivityBar";
import { StickyScrollProvider } from "../../components/StickyScrollContext";
import { useSampleData } from "../../state/hooks";
import { useLoadSample } from "../../state/useLoadSample";
import { usePollSample } from "../../state/usePollSample";
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
  // Use shared hooks for loading and polling
  useLoadSample();
  usePollSample();
  return (
    <InlineSampleComponent showActivity={showActivity} className={className} />
  );
};

export const InlineSampleComponent: FC<InlineSampleDisplayProps> = ({
  showActivity,
  className,
}) => {
  const sampleData = useSampleData();

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
        <StickyScrollProvider value={scrollRef}>
          <div className={styles.body}>
            {sampleData.error ? (
              <ErrorPanel
                title="Unable to load sample"
                error={sampleData.error}
              />
            ) : (
              <SampleDisplay
                id={"inline-sample-display"}
                scrollRef={scrollRef}
              />
            )}
          </div>
        </StickyScrollProvider>
      </div>
    </div>
  );
};
