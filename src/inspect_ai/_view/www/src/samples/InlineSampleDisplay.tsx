import { FC, RefObject } from "react";
import { ErrorPanel } from "../components/ErrorPanel";
import { ProgressBar } from "../components/ProgressBar";
import { EvalSample } from "../types/log";
import { SampleDisplay } from "./SampleDisplay";
import { SamplesDescriptor } from "./descriptor/samplesDescriptor";

import { RunningSampleData, ScoreLabel } from "../types";
import styles from "./InlineSampleDisplay.module.css";

interface InlineSampleDisplayProps {
  id: string;
  sampleStatus: string;
  sampleError?: Error;
  sample?: EvalSample;
  score?: ScoreLabel;
  sampleDescriptor: SamplesDescriptor;
  selectedTab?: string;
  setSelectedTab: (tab: string) => void;
  scrollRef: RefObject<HTMLDivElement | null>;
  runningSampleData?: RunningSampleData;
}

/**
 * Inline Sample Display
 */
export const InlineSampleDisplay: FC<InlineSampleDisplayProps> = ({
  id,
  sample,
  score,
  sampleStatus,
  sampleError,
  sampleDescriptor,
  selectedTab,
  setSelectedTab,
  scrollRef,
  runningSampleData,
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
            score={score}
            sampleDescriptor={sampleDescriptor}
            selectedTab={selectedTab}
            setSelectedTab={setSelectedTab}
            scrollRef={scrollRef}
            runningSampleData={runningSampleData}
          />
        )}
      </div>
    </div>
  );
};
