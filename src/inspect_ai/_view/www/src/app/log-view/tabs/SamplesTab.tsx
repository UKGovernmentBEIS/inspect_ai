import { FC, Fragment, useEffect, useMemo, useRef, useState } from "react";
import { VirtuosoHandle } from "react-virtuoso";
import { Status } from "../../../@types/log";
import { InlineSampleDisplay } from "../../../app/samples/InlineSampleDisplay.tsx";
import { SampleDialog } from "../../../app/samples/SampleDialog.tsx";
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
  useGroupBy,
  useGroupByOrder,
  useSampleDescriptor,
  useScore,
  useTotalSampleCount,
} from "../../../state/hooks.ts";
import { useStore } from "../../../state/store.ts";
import { ApplicationIcons } from "../../appearance/icons.ts";
import { RunningNoSamples } from "./RunningNoSamples.tsx";
import { getSampleProcessor } from "./grouping.ts";
import { ListItem } from "./types.ts";

// Individual hook for Samples tab
export const useSamplesTabConfig = (
  evalStatus: Status | undefined,
  refreshLog: () => void,
) => {
  const totalSampleCount = useTotalSampleCount();
  const samplesDescriptor = useSampleDescriptor();
  const sampleSummaries = useFilteredSamples();
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
            ? [<ScoreFilterTools />]
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
    sampleSummaries,
    samplesDescriptor,
    totalSampleCount,
  ]);
};

interface SamplesTabProps {
  // Required props
  running: boolean;
}

export const SamplesTab: FC<SamplesTabProps> = ({ running }) => {
  const selectedSampleIndex = useStore(
    (state) => state.log.selectedSampleIndex,
  );

  const sampleSummaries = useFilteredSamples();
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);

  // Compute the limit to apply to the sample count (this is so)
  // we can provide a total expected sample count for this evaluation
  const evalSampleCount = useMemo(() => {
    const limit = selectedLogSummary?.eval.config.limit;
    const limitCount =
      limit === null || limit === undefined
        ? undefined
        : typeof limit === "number"
          ? limit
          : (limit[1] as number) - (limit[0] as number);
    return (
      (limitCount || selectedLogSummary?.eval.dataset.samples || 0) *
      (selectedLogSummary?.eval.config.epochs || 0)
    );
  }, [selectedLogSummary?.eval.config.limit]);

  const totalSampleCount = useTotalSampleCount();

  const samplesDescriptor = useSampleDescriptor();
  const groupBy = useGroupBy();
  const groupByOrder = useGroupByOrder();
  const currentScore = useScore();
  const selectSample = useStore((state) => state.logActions.selectSample);

  const selectedSampleIdentifier = useStore(
    (state) => state.sample.sample_identifier,
  );

  const [items, setItems] = useState<ListItem[]>([]);
  const [sampleItems, setSampleItems] = useState<ListItem[]>([]);

  const sampleListHandle = useRef<VirtuosoHandle | null>(null);

  // Keep the selected item scrolled into view
  useEffect(() => {
    setTimeout(() => {
      if (sampleListHandle.current) {
        sampleListHandle.current.scrollIntoView({ index: selectedSampleIndex });
      }
    }, 0);
  }, [selectedSampleIndex]);

  const showingSampleDialog = useStore((state) => state.app.dialogs.sample);

  // Focus the sample list when sample dialog is hidden, but only when it's being dismissed
  const previousShowingDialogRef = useRef(showingSampleDialog);
  useEffect(() => {
    // Only focus when transitioning from showing dialog to not showing dialog
    if (
      previousShowingDialogRef.current &&
      !showingSampleDialog &&
      sampleListHandle.current
    ) {
      setTimeout(() => {
        const element = document.querySelector(".samples-list");
        if (element instanceof HTMLElement) {
          element.focus();
        }
      }, 10);
    }
    previousShowingDialogRef.current = showingSampleDialog;
  }, [showingSampleDialog]);

  const sampleProcessor = useMemo(() => {
    if (!samplesDescriptor) return undefined;

    return getSampleProcessor(
      sampleSummaries || [],
      selectedLogSummary?.eval?.config?.epochs || 1,
      groupBy,
      groupByOrder,
      samplesDescriptor,
      currentScore,
    );
  }, [
    samplesDescriptor,
    sampleSummaries,
    selectedLogSummary?.eval?.config?.epochs,
    groupBy,
    groupByOrder,
    currentScore,
  ]);

  useEffect(() => {
    const resolvedSamples = sampleSummaries?.flatMap((sample, index) => {
      const results: ListItem[] = [];
      const previousSample =
        index !== 0 ? sampleSummaries[index - 1] : undefined;
      const items = sampleProcessor
        ? sampleProcessor(sample, index, previousSample)
        : [];

      results.push(...items);
      return results;
    });

    setItems(resolvedSamples || []);
    setSampleItems(
      resolvedSamples
        ? resolvedSamples.filter((item) => {
            return item.type === "sample";
          })
        : [],
    );

    if (sampleSummaries.length === 1) {
      selectSample(0);
    }
  }, [sampleSummaries, sampleProcessor]);

  const title =
    selectedSampleIndex > -1 && sampleItems.length > selectedSampleIndex
      ? sampleItems[selectedSampleIndex].label
      : "";

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
          <InlineSampleDisplay />
        ) : undefined}
        {samplesDescriptor && totalSampleCount > 1 ? (
          <SampleList
            listHandle={sampleListHandle}
            items={items}
            totalItemCount={evalSampleCount}
            running={running}
          />
        ) : undefined}
        {showingSampleDialog && (
          <SampleDialog
            id={
              selectedSampleIdentifier
                ? `${selectedSampleIdentifier.id}_${selectedSampleIdentifier.epoch}`
                : ""
            }
            title={title}
            showingSampleDialog={showingSampleDialog}
          />
        )}
      </Fragment>
    );
  }
};
