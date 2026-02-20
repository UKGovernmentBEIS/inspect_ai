import type { AgGridReact } from "ag-grid-react";
import { FC, Fragment, useEffect, useMemo, useRef } from "react";
import { Status } from "../../../@types/log";
import { InlineSampleDisplay } from "../../../app/samples/InlineSampleDisplay.tsx";
import {
  SampleTools,
  ScoreFilterTools,
} from "../../../app/samples/SamplesTools.tsx";
import { SampleList } from "../../../app/samples/list/SampleList.tsx";
import { NoContentsPanel } from "../../../components/NoContentsPanel.tsx";
import { ToolButton } from "../../../components/ToolButton.tsx";
import { kLogViewSamplesTabId } from "../../../constants.ts";
import {
  useFilteredSamples,
  useSampleDescriptor,
  useTotalSampleCount,
} from "../../../state/hooks.ts";
import { useStore } from "../../../state/store.ts";
import { ApplicationIcons } from "../../appearance/icons.ts";
import { RunningNoSamples } from "./RunningNoSamples.tsx";
import { SampleListItem } from "./types.ts";

// Individual hook for Samples tab
export const useSamplesTabConfig = (
  evalStatus: Status | undefined,
  refreshLog: () => void,
) => {
  const totalSampleCount = useTotalSampleCount();
  const samplesDescriptor = useSampleDescriptor();
  const streamSamples = useStore((state) => state.capabilities.streamSamples);

  return useMemo(() => {
    return {
      id: kLogViewSamplesTabId,
      scrollable: false,
      label: totalSampleCount > 1 ? "Samples" : "Sample",
      component: SamplesTab,
      componentProps: {
        running: evalStatus === "started",
      },
      tools: () =>
        !samplesDescriptor
          ? undefined
          : totalSampleCount === 1
            ? [<ScoreFilterTools key="sample-score-tool" />]
            : [
                <SampleTools key="sample-tools" />,
                evalStatus === "started" && !streamSamples && (
                  <ToolButton
                    key="refresh"
                    label="Refresh"
                    icon={ApplicationIcons.refresh}
                    onClick={refreshLog}
                  />
                ),
              ],
    };
  }, [
    evalStatus,
    refreshLog,
    samplesDescriptor,
    streamSamples,
    totalSampleCount,
  ]);
};

interface SamplesTabProps {
  // Required props
  running: boolean;
}

export const SamplesTab: FC<SamplesTabProps> = ({ running }) => {
  const sampleSummaries = useFilteredSamples();
  const selectedLogDetails = useStore((state) => state.log.selectedLogDetails);
  const selectedLogFile = useStore((state) => state.logs.selectedLogFile);

  // Compute the limit to apply to the sample count (this is so)
  // we can provide a total expected sample count for this evaluation
  const evalSampleCount = useMemo(() => {
    const limit = selectedLogDetails?.eval.config.limit;
    const limitCount =
      limit === null || limit === undefined
        ? undefined
        : typeof limit === "number"
          ? limit
          : (limit[1] as number) - (limit[0] as number);
    return (
      (limitCount || selectedLogDetails?.eval.dataset.samples || 0) *
      (selectedLogDetails?.eval.config.epochs || 0)
    );
  }, [
    selectedLogDetails?.eval.config.epochs,
    selectedLogDetails?.eval.config.limit,
    selectedLogDetails?.eval.dataset.samples,
  ]);

  const totalSampleCount = useTotalSampleCount();

  const samplesDescriptor = useSampleDescriptor();
  const selectSample = useStore((state) => state.logActions.selectSample);
  const sampleStatus = useStore((state) => state.sample.sampleStatus);

  const sampleListHandle = useRef<AgGridReact<SampleListItem> | null>(null);

  const items: SampleListItem[] = useMemo(() => {
    if (!samplesDescriptor) return [];
    return sampleSummaries.map(
      (sample): SampleListItem => ({
        data: sample,
        answer:
          samplesDescriptor.selectedScorerDescriptor(sample)?.answer() || "",
        completed: sample.completed !== undefined ? sample.completed : true,
      }),
    );
  }, [sampleSummaries, samplesDescriptor]);

  useEffect(() => {
    if (sampleSummaries.length === 1 && selectedLogFile) {
      const sample = sampleSummaries[0];
      selectSample(sample.id, sample.epoch, selectedLogFile);
    }
  }, [sampleSummaries, selectSample, selectedLogFile]);

  if (totalSampleCount === 0) {
    if (running) {
      return <RunningNoSamples />;
    } else {
      return <NoContentsPanel text="No samples" />;
    }
  } else {
    return (
      <Fragment>
        {samplesDescriptor && totalSampleCount === 1 ? (
          <InlineSampleDisplay showActivity={sampleStatus === "loading"} />
        ) : undefined}
        {samplesDescriptor && totalSampleCount > 1 ? (
          <SampleList
            listHandle={sampleListHandle}
            items={items}
            earlyStopping={selectedLogDetails?.results?.early_stopping}
            totalItemCount={evalSampleCount}
            running={running}
          />
        ) : undefined}
      </Fragment>
    );
  }
};
