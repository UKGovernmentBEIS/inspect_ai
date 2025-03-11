import {
  FC,
  Fragment,
  RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { VirtuosoHandle } from "react-virtuoso";
import { InlineSampleDisplay } from "../../samples/InlineSampleDisplay";
import { SampleDialog } from "../../samples/SampleDialog";
import { SampleList } from "../../samples/list/SampleList";
import {
  useFilteredSamples,
  useGroupBy,
  useGroupByOrder,
  useSampleDescriptor,
  useScore,
  useTotalSampleCount,
} from "../../state/hooks.ts";
import { useStore } from "../../state/store.ts";
import { NoSamplesPanel } from "./NoSamples.tsx";
import { getSampleProcessor } from "./grouping.ts";
import { ListItem } from "./types.ts";

interface SamplesTabProps {
  // Required props
  running: boolean;
  sampleTabScrollRef: RefObject<HTMLDivElement | null>;
}

export const SamplesTab: FC<SamplesTabProps> = ({
  running,
  sampleTabScrollRef,
}) => {
  const selectSample = useStore((state) => state.logActions.selectSample);
  const selectedSampleIndex = useStore(
    (state) => state.log.selectedSampleIndex,
  );

  const sampleSummaries = useFilteredSamples();
  const selectedLogSummary = useStore((state) => state.log.selectedLogSummary);
  const totalSampleCount = useTotalSampleCount();

  const samplesDescriptor = useSampleDescriptor();
  const groupBy = useGroupBy();
  const groupByOrder = useGroupByOrder();
  const currentScore = useScore();

  const selectedSample = useStore((state) => state.sample.selectedSample);

  const [items, setItems] = useState<ListItem[]>([]);
  const [sampleItems, setSampleItems] = useState<ListItem[]>([]);

  const sampleListHandle = useRef<VirtuosoHandle | null>(null);
  const sampleDialogRef = useRef<HTMLDivElement>(null);

  const selectedSampleTab = useStore((state) => state.app.tabs.sample);
  const setSelectedSampleTab = useStore(
    (state) => state.appActions.setSampleTab,
  );
  const showingSampleDialog = useStore((state) => state.app.dialogs.sample);
  const setShowingSampleDialog = useStore(
    (state) => state.appActions.setShowingSampleDialog,
  );

  // Shows the sample dialog
  const showSample = useCallback(
    (index: number) => {
      selectSample(index);
      setShowingSampleDialog(true);
    },
    [selectSample, setShowingSampleDialog],
  );

  // Keep the selected item scrolled into view
  useEffect(() => {
    setTimeout(() => {
      if (sampleListHandle.current) {
        sampleListHandle.current.scrollIntoView({ index: selectedSampleIndex });
      }
    }, 0);
  }, [selectedSampleIndex]);

  // Focus the dialog when it is shown
  useEffect(() => {
    if (showingSampleDialog) {
      setTimeout(() => {
        sampleDialogRef.current?.focus();
      }, 0);
    }
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
  }, [sampleSummaries, sampleProcessor]);

  const previousSampleIndex = useCallback(() => {
    return selectedSampleIndex > 0 ? selectedSampleIndex - 1 : -1;
  }, [selectedSampleIndex]);

  // Manage the next / previous state the selected sample
  const nextSample = useCallback(() => {
    const next = Math.min(selectedSampleIndex + 1, sampleItems.length - 1);
    if (next > -1) {
      selectSample(next);
    }
  }, [selectedSampleIndex, sampleItems, selectSample]);

  const previousSample = useCallback(() => {
    const prev = previousSampleIndex();
    if (prev > -1) {
      selectSample(prev);
    }
  }, [previousSampleIndex, selectSample]);

  const title =
    selectedSampleIndex > -1 && sampleItems.length > selectedSampleIndex
      ? sampleItems[selectedSampleIndex].label
      : "";

  if (totalSampleCount === 0) {
    return <NoSamplesPanel />;
  } else {
    return (
      <Fragment>
        {samplesDescriptor && totalSampleCount === 1 ? (
          <InlineSampleDisplay
            id="sample-display"
            selectedTab={selectedSampleTab}
            setSelectedTab={setSelectedSampleTab}
            scrollRef={sampleTabScrollRef}
          />
        ) : undefined}
        {samplesDescriptor && totalSampleCount > 1 ? (
          <SampleList
            listHandle={sampleListHandle}
            items={items}
            running={running}
            nextSample={nextSample}
            prevSample={previousSample}
            showSample={showSample}
          />
        ) : undefined}
        {showingSampleDialog ? (
          <SampleDialog
            id={String(selectedSample?.id || "")}
            title={title}
            showingSampleDialog={showingSampleDialog}
            setShowingSampleDialog={setShowingSampleDialog}
            selectedTab={selectedSampleTab}
            setSelectedTab={setSelectedSampleTab}
            nextSample={nextSample}
            prevSample={previousSample}
          />
        ) : undefined}
      </Fragment>
    );
  }
};
