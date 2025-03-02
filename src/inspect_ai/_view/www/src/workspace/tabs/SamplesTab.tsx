import {
  FC,
  Fragment,
  RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { VirtuosoHandle } from "react-virtuoso";
import { EmptyPanel } from "../../components/EmptyPanel.tsx";
import { useLogContext } from "../../contexts/LogContext.tsx";
import { useSampleContext } from "../../contexts/SampleContext.tsx";
import { InlineSampleDisplay } from "../../samples/InlineSampleDisplay";
import { SampleDialog } from "../../samples/SampleDialog";
import { SampleList } from "../../samples/list/SampleList";
import { getSampleProcessor } from "./grouping.ts";
import { ListItem } from "./types.ts";

interface SamplesTabProps {
  // Required props
  running: boolean;
  showingSampleDialog: boolean;
  setShowingSampleDialog: (showing: boolean) => void;
  selectedSampleTab?: string;
  setSelectedSampleTab: (tab: string) => void;
  sampleScrollPositionRef: RefObject<number>;
  setSampleScrollPosition: (position: number) => void;
  sampleTabScrollRef: RefObject<HTMLDivElement | null>;
}

export const SamplesTab: FC<SamplesTabProps> = ({
  running,
  showingSampleDialog,
  setShowingSampleDialog,
  selectedSampleTab,
  setSelectedSampleTab,
  sampleScrollPositionRef,
  setSampleScrollPosition,
  sampleTabScrollRef,
}) => {
  const logContext = useLogContext();
  const sampleContext = useSampleContext();

  const [items, setItems] = useState<ListItem[]>([]);
  const [sampleItems, setSampleItems] = useState<ListItem[]>([]);

  const sampleListHandle = useRef<VirtuosoHandle | null>(null);
  const sampleDialogRef = useRef<HTMLDivElement>(null);

  // Shows the sample dialog
  const showSample = useCallback(
    (index: number) => {
      logContext.dispatch({ type: "SELECT_SAMPLE", payload: index });
      setShowingSampleDialog(true);
    },
    [logContext.dispatch, setShowingSampleDialog],
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

  useEffect(() => {
    const sampleProcessor = logContext.samplesDescriptor
      ? getSampleProcessor(
          logContext.sampleSummaries || [],
          logContext.state.selectedLogSummary?.eval?.config?.epochs || 1,
          logContext.groupBy,
          logContext.groupByOrder,
          logContext.samplesDescriptor,
          logContext.state.score,
        )
      : undefined;

    // Process the samples into the proper data structure
    const items = logContext.sampleSummaries?.flatMap((sample, index) => {
      const results: ListItem[] = [];
      const previousSample =
        index !== 0 ? logContext.sampleSummaries[index - 1] : undefined;
      const items = sampleProcessor
        ? sampleProcessor(sample, index, previousSample)
        : [];

      results.push(...items);
      return results;
    });

    setItems(items || []);
    setSampleItems(
      items
        ? items.filter((item) => {
            return item.type === "sample";
          })
        : [],
    );
  }, [
    logContext.sampleSummaries,
    logContext.state.selectedLogSummary?.eval?.config?.epochs,
    logContext.state.score,
    logContext.groupBy,
    logContext.groupByOrder,
    logContext.samplesDescriptor,
  ]);

  const nextSampleIndex = useCallback(() => {
    if (logContext.state.selectedSampleIndex < sampleItems.length - 1) {
      return logContext.state.selectedSampleIndex + 1;
    } else {
      return -1;
    }
  }, [logContext.state.selectedSampleIndex, sampleItems.length]);

  const previousSampleIndex = useCallback(() => {
    return logContext.state.selectedSampleIndex > 0
      ? logContext.state.selectedSampleIndex - 1
      : -1;
  }, [logContext.state.selectedSampleIndex]);

  const status = sampleContext.state.sampleStatus;
  // Manage the next / previous state the selected sample
  const nextSample = useCallback(() => {
    const next = nextSampleIndex();
    if (status !== "loading" && next > -1) {
      logContext.dispatch({ type: "SELECT_SAMPLE", payload: next });
    }
  }, [nextSampleIndex, status, logContext.dispatch]);

  const previousSample = useCallback(() => {
    const prev = previousSampleIndex();
    if (status !== "loading" && prev > -1) {
      logContext.dispatch({ type: "SELECT_SAMPLE", payload: prev });
    }
  }, [previousSampleIndex, status, logContext.dispatch]);

  const title =
    logContext.state.selectedSampleIndex > -1 &&
    sampleItems.length > logContext.state.selectedSampleIndex
      ? sampleItems[logContext.state.selectedSampleIndex].label
      : "";

  if (!logContext.samplesDescriptor) {
    return (
      <EmptyPanel>
        <div>No samples</div>
      </EmptyPanel>
    );
  } else {
    return (
      <Fragment>
        {logContext.samplesDescriptor && logContext.totalSampleCount === 1 ? (
          <InlineSampleDisplay
            id="sample-display"
            selectedTab={selectedSampleTab}
            setSelectedTab={setSelectedSampleTab}
            scrollRef={sampleTabScrollRef}
          />
        ) : undefined}
        {logContext.samplesDescriptor && logContext.totalSampleCount > 1 ? (
          <SampleList
            listHandle={sampleListHandle}
            items={items}
            running={running}
            nextSample={nextSample}
            prevSample={previousSample}
            showSample={showSample}
          />
        ) : undefined}
        <SampleDialog
          id={String(sampleContext.state.selectedSample?.id || "")}
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
      </Fragment>
    );
  }
};
