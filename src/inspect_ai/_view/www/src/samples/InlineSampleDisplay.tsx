import { RefObject } from "react";
import { ErrorPanel } from "../components/ErrorPanel";
import { ProgressBar } from "../components/ProgressBar";
import { EvalSample } from "../types/log";
import { SampleDisplay } from "./SampleDisplay";
import { SamplesDescriptor } from "./descriptor/samplesDescriptor";

import styles from "./InlineSampleDisplay.module.css";

interface InlineSampleDisplayProps {
  id: string;
  sampleStatus: string;
  sampleError?: Error;
  sample?: EvalSample;
  sampleDescriptor: SamplesDescriptor;
  selectedTab?: string;
  setSelectedTab: (tab: string) => void;
  scrollRef: RefObject<HTMLDivElement | null>;
}

/**
 * Inline Sample Display
 */
export const InlineSampleDisplay: React.FC<InlineSampleDisplayProps> = ({
  id,
  sample,
  sampleStatus,
  sampleError,
  sampleDescriptor,
  selectedTab,
  setSelectedTab,
  scrollRef,
}) => {
  return (
    <div className={styles.container}>
      <ProgressBar animating={sampleStatus === "loading"} />
      <div className={styles.body}>
        {sampleError ? (
          <ErrorPanel title="Unable to load sample" error={sampleError} />
        ) : (
          <SampleDisplay
            id={id}
            sample={sample}
            sampleDescriptor={sampleDescriptor}
            selectedTab={selectedTab}
            setSelectedTab={setSelectedTab}
            scrollRef={scrollRef}
          />
        )}
      </div>
    </div>
  );
};
