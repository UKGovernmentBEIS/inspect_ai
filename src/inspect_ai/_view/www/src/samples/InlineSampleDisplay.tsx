import { FC, RefObject } from "react";
import { ErrorPanel } from "../components/ErrorPanel";
import { ProgressBar } from "../components/ProgressBar";
import { SampleDisplay } from "./SampleDisplay";

import { useSampleContext } from "../state/SampleContext";
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
  const sampleContext = useSampleContext();
  return (
    <div className={styles.container}>
      <ProgressBar animating={sampleContext.state.sampleStatus === "loading"} />
      <div className={styles.body}>
        {sampleContext.state.sampleError ? (
          <ErrorPanel
            title="Unable to load sample"
            error={sampleContext.state.sampleError}
          />
        ) : (
          <SampleDisplay
            id={id}
            sample={sampleContext.state.selectedSample}
            runningSampleData={sampleContext.state.runningSampleData}
            selectedTab={selectedTab}
            setSelectedTab={setSelectedTab}
            scrollRef={scrollRef}
          />
        )}
      </div>
    </div>
  );
};
