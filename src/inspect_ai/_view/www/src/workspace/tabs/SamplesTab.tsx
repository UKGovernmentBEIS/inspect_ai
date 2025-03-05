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
import { EmptyPanel } from "../../components/EmptyPanel.tsx";
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
import { getSampleProcessor } from "./grouping.ts";
import { ListItem } from "./types.ts";

interface SamplesTabProps {
  // Required props
  running: boolean;
  sampleScrollPositionRef: RefObject<number>;
  setSampleScrollPosition: (position: number) => void;
  sampleTabScrollRef: RefObject<HTMLDivElement | null>;
}

export const SamplesTab: FC<SamplesTabProps> = ({
  running,
  sampleScrollPositionRef,
  setSampleScrollPosition,
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

  const sampleStatus = useStore((state) => state.sample.sampleStatus);
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

  useEffect(() => {
    if (showingSampleDialog) {
      setTimeout(() => {
        sampleDialogRef.current?.focus();
      }, 0);
    } else {
      setTimeout(() => {
        if (sampleListHandle.current) {
          sampleListHandle.current.scrollToIndex(0);
        }
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

  const nextSampleIndex = useCallback(() => {
    if (selectedSampleIndex < sampleItems.length - 1) {
      return selectedSampleIndex + 1;
    } else {
      return -1;
    }
  }, [selectedSampleIndex, sampleItems.length]);

  const previousSampleIndex = useCallback(() => {
    return selectedSampleIndex > 0 ? selectedSampleIndex - 1 : -1;
  }, [selectedSampleIndex]);

  // Manage the next / previous state the selected sample
  const nextSample = useCallback(() => {
    const next = nextSampleIndex();
    if (sampleStatus !== "loading" && next > -1) {
      selectSample(next);
    }
  }, [nextSampleIndex, sampleStatus, selectSample, showingSampleDialog]);

  const previousSample = useCallback(() => {
    const prev = previousSampleIndex();
    if (sampleStatus !== "loading" && prev > -1) {
      selectSample(prev);
    }
  }, [previousSampleIndex, sampleStatus, selectSample, showingSampleDialog]);

  const title =
    selectedSampleIndex > -1 && sampleItems.length > selectedSampleIndex
      ? sampleItems[selectedSampleIndex].label
      : "";

  if (totalSampleCount === 0) {
    return (
      <EmptyPanel>
        <div>No samples</div>
      </EmptyPanel>
    );
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
            sampleScrollPositionRef={sampleScrollPositionRef}
            setSampleScrollPosition={setSampleScrollPosition}
          />
        ) : undefined}
      </Fragment>
    );
  }
};
