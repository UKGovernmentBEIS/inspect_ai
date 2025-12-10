import { FC, Fragment, useEffect, useMemo, useRef } from "react";
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
  useSelectedScores,
  useTotalSampleCount,
} from "../../../state/hooks.ts";
import { useStore } from "../../../state/store.ts";
import { ApplicationIcons } from "../../appearance/icons.ts";
import { sampleIdsEqual } from "../../shared/sample.ts";
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
  const selectedSampleHandle = useStore(
    (state) => state.log.selectedSampleHandle,
  );

  const sampleSummaries = useFilteredSamples();
  const selectedLogDetails = useStore((state) => state.log.selectedLogDetails);

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
  const groupBy = useGroupBy();
  const groupByOrder = useGroupByOrder();
  const selectedScores = useSelectedScores();
  const selectSample = useStore((state) => state.logActions.selectSample);
  const sampleStatus = useStore((state) => state.sample.sampleStatus);

  const sampleListHandle = useRef<VirtuosoHandle | null>(null);

  const sampleProcessor = useMemo(() => {
    if (!samplesDescriptor) return undefined;

    return getSampleProcessor(
      sampleSummaries || [],
      selectedLogDetails?.eval?.config?.epochs || 1,
      groupBy,
      groupByOrder,
      samplesDescriptor,
      selectedScores,
    );
  }, [
    samplesDescriptor,
    sampleSummaries,
    selectedLogDetails?.eval?.config?.epochs,
    groupBy,
    groupByOrder,
    selectedScores,
  ]);

  const items = useMemo(() => {
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

    return resolvedSamples || [];
  }, [sampleSummaries, sampleProcessor]);

  const selectedItemIndex = useMemo(() => {
    return items.findIndex((item) => {
      if (item.type !== "sample") {
        return false;
      }
      return (
        sampleIdsEqual(item.sampleId, selectedSampleHandle?.id) &&
        item.sampleEpoch === selectedSampleHandle?.epoch
      );
    });
  }, [selectedSampleHandle, items]);

  // Keep the selected item scrolled into view
  useEffect(() => {
    setTimeout(() => {
      if (sampleListHandle.current && selectedItemIndex >= 0) {
        sampleListHandle.current.scrollIntoView({
          index: selectedItemIndex,
        });
      }
    }, 0);
  }, [selectedItemIndex]);

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

  useEffect(() => {
    if (sampleSummaries.length === 1) {
      const sample = sampleSummaries[0];
      selectSample(sample.id, sample.epoch);
    }
  }, [sampleSummaries, selectSample]);

  const title = useMemo(() => {
    if (selectedSampleHandle) {
      return `Sample ${selectedSampleHandle.id} (Epoch ${selectedSampleHandle.epoch})`;
    }
    return "";
  }, [selectedSampleHandle]);

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
        {showingSampleDialog && (
          <SampleDialog
            id={
              selectedSampleHandle
                ? `${selectedSampleHandle.id}_${selectedSampleHandle.epoch}`
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
