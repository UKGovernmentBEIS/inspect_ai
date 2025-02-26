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
import { SampleSummary } from "../../api/types.ts";
import { EmptyPanel } from "../../components/EmptyPanel.tsx";
import { InlineSampleDisplay } from "../../samples/InlineSampleDisplay";
import { SampleDialog } from "../../samples/SampleDialog";
import { SamplesDescriptor } from "../../samples/descriptor/samplesDescriptor.tsx";
import { SampleList } from "../../samples/list/SampleList";
import { SampleMode, ScoreFilter } from "../../types.ts";
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
  sampleMode: SampleMode;
  groupBy: "epoch" | "sample" | "none";
  groupByOrder: "asc" | "desc";
  sampleStatus: string;
  selectedSampleIndex: number;
  setSelectedSampleIndex: (index: number) => void;
  showingSampleDialog: boolean;
  setShowingSampleDialog: (showing: boolean) => void;
  selectedSampleTab?: string;
  setSelectedSampleTab: (tab: string) => void;
  epoch: string;
  filter: ScoreFilter;
  sampleScrollPositionRef: RefObject<number>;
  setSampleScrollPosition: (position: number) => void;
  sampleTabScrollRef: RefObject<HTMLDivElement | null>;
}

export const SamplesTab: FC<SamplesTabProps> = ({
  sample,
  samples,
  sampleMode,
  groupBy,
  groupByOrder,
  sampleDescriptor,
  sampleStatus,
  sampleError,
  selectedSampleIndex,
  setSelectedSampleIndex,
  showingSampleDialog,
  setShowingSampleDialog,
  selectedSampleTab,
  setSelectedSampleTab,
  sampleScrollPositionRef,
  setSampleScrollPosition,
  sampleTabScrollRef,
}) => {
  const [items, setItems] = useState<ListItem[]>([]);
  const [sampleItems, setSampleItems] = useState<ListItem[]>([]);

  const sampleListHandle = useRef<VirtuosoHandle | null>(null);
  const sampleDialogRef = useRef<HTMLDivElement>(null);

  // Shows the sample dialog
  const showSample = useCallback(
    (index: number) => {
      setSelectedSampleIndex(index);
      setShowingSampleDialog(true);
    },
    [setSelectedSampleIndex, setShowingSampleDialog],
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
    const sampleProcessor = sampleDescriptor
      ? getSampleProcessor(
          samples || [],
          groupBy,
          groupByOrder,
          sampleDescriptor,
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
  }, [samples, groupBy, groupByOrder, sampleDescriptor]);

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
      setSelectedSampleIndex(next);
    }
  }, [nextSampleIndex, sampleStatus, setSelectedSampleIndex]);

  const previousSample = useCallback(() => {
    const prev = previousSampleIndex();
    if (sampleStatus !== "loading" && prev > -1) {
      setSelectedSampleIndex(prev);
    }
  }, [previousSampleIndex, sampleStatus, setSelectedSampleIndex]);

  const title =
    selectedSampleIndex > -1 && sampleItems.length > selectedSampleIndex
      ? sampleItems[selectedSampleIndex].label
      : "";

  if (!sampleDescriptor) {
    return <EmptyPanel />;
  } else {
    return (
      <Fragment>
        {sampleDescriptor && sampleMode === "single" ? (
          <InlineSampleDisplay
            id="sample-display"
            sample={sample}
            sampleStatus={sampleStatus}
            sampleError={sampleError}
            sampleDescriptor={sampleDescriptor}
            selectedTab={selectedSampleTab}
            setSelectedTab={setSelectedSampleTab}
            scrollRef={sampleTabScrollRef}
          />
        ) : undefined}
        {sampleDescriptor && sampleMode === "many" ? (
          <SampleList
            listHandle={sampleListHandle}
            items={items}
            sampleDescriptor={sampleDescriptor}
            selectedIndex={selectedSampleIndex}
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
          sampleDescriptor={sampleDescriptor}
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
