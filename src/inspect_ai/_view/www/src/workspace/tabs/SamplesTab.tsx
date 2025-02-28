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
import { useLogContext } from "../../LogContext.tsx";
import { SampleSummary } from "../../api/types.ts";
import { EmptyPanel } from "../../components/EmptyPanel.tsx";
import { InlineSampleDisplay } from "../../samples/InlineSampleDisplay";
import { SampleDialog } from "../../samples/SampleDialog";
import { SamplesDescriptor } from "../../samples/descriptor/samplesDescriptor.tsx";
import { SampleList } from "../../samples/list/SampleList";
import { RunningSampleData, SampleMode } from "../../types.ts";
import { EvalSample } from "../../types/log";
import { getSampleProcessor } from "./grouping.ts";
import { ListItem } from "./types.ts";

interface SamplesTabProps {
  // Optional props
  sample?: EvalSample;
  samples?: SampleSummary[];
  sampleDescriptor?: SamplesDescriptor;
  sampleError?: Error;

  // Required props
  running: boolean;
  sampleMode: SampleMode;
  sampleStatus: string;
  showingSampleDialog: boolean;
  setShowingSampleDialog: (showing: boolean) => void;
  selectedSampleTab?: string;
  setSelectedSampleTab: (tab: string) => void;
  runningSampleData?: RunningSampleData;
  sampleScrollPositionRef: RefObject<number>;
  setSampleScrollPosition: (position: number) => void;
  sampleTabScrollRef: RefObject<HTMLDivElement | null>;
}

export const SamplesTab: FC<SamplesTabProps> = ({
  sample,
  samples,
  sampleMode,
  running,
  sampleStatus,
  sampleError,
  showingSampleDialog,
  setShowingSampleDialog,
  runningSampleData,
  selectedSampleTab,
  setSelectedSampleTab,
  sampleScrollPositionRef,
  setSampleScrollPosition,
  sampleTabScrollRef,
}) => {
  const logContext = useLogContext();
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
          samples || [],
          logContext.state.selectedLogSummary?.eval?.config?.epochs || 1,
          logContext.groupBy,
          logContext.groupByOrder,
          logContext.samplesDescriptor,
          logContext.state.score,
        )
      : undefined;

    // Process the samples into the proper data structure
    const items = samples?.flatMap((sample, index) => {
      const results: ListItem[] = [];
      const previousSample = index !== 0 ? samples[index - 1] : undefined;
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
    samples,
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

  // Manage the next / previous state the selected sample
  const nextSample = useCallback(() => {
    const next = nextSampleIndex();
    if (sampleStatus !== "loading" && next > -1) {
      logContext.dispatch({ type: "SELECT_SAMPLE", payload: next });
    }
  }, [nextSampleIndex, sampleStatus, logContext.dispatch]);

  const previousSample = useCallback(() => {
    const prev = previousSampleIndex();
    if (sampleStatus !== "loading" && prev > -1) {
      logContext.dispatch({ type: "SELECT_SAMPLE", payload: prev });
    }
  }, [previousSampleIndex, sampleStatus, logContext.dispatch]);

  const title =
    logContext.state.selectedSampleIndex > -1 &&
    sampleItems.length > logContext.state.selectedSampleIndex
      ? sampleItems[logContext.state.selectedSampleIndex].label
      : "";

  if (!logContext.samplesDescriptor) {
    return <EmptyPanel />;
  } else {
    return (
      <Fragment>
        {logContext.samplesDescriptor && sampleMode === "single" ? (
          <InlineSampleDisplay
            id="sample-display"
            sample={sample}
            runningSampleData={runningSampleData}
            sampleStatus={sampleStatus}
            sampleError={sampleError}
            selectedTab={selectedSampleTab}
            setSelectedTab={setSelectedSampleTab}
            scrollRef={sampleTabScrollRef}
          />
        ) : undefined}
        {logContext.samplesDescriptor && sampleMode === "many" ? (
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
          id={String(sample?.id || "")}
          title={title}
          sample={sample}
          sampleStatus={sampleStatus}
          sampleError={sampleError}
          runningSampleData={runningSampleData}
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
