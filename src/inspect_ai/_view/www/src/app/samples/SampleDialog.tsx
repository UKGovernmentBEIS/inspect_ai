import { LargeModal, ModalTool, ModalTools } from "../../components/LargeModal";
import { ApplicationIcons } from "../appearance/icons";

import { FC, Ref, useCallback, useEffect, useMemo, useRef } from "react";
import { ErrorPanel } from "../../components/ErrorPanel";
import {
  useFilteredSamples,
  useLogSelection,
  usePrevious,
  useSampleData,
  useSampleNavigation,
} from "../../state/hooks";
import { useStatefulScrollPosition } from "../../state/scrolling";
import { useStore } from "../../state/store";
import { SampleDisplay } from "./SampleDisplay";

interface SampleDialogProps {
  id: string;
  title: string;
  selectedTab?: string;
  setSelectedTab: (tab: string) => void;
  showingSampleDialog: boolean;
  setShowingSampleDialog: (showing: boolean) => void;
}

/**
 * Inline Sample Display
 */
export const SampleDialog: FC<SampleDialogProps> = ({
  id,
  title,
  showingSampleDialog,
  selectedTab,
  setSelectedTab,
}) => {
  // Scroll referernce (attach stateful trackign)
  const scrollRef: Ref<HTMLDivElement> = useRef(null);
  useStatefulScrollPosition(scrollRef, "sample-dialog");

  // Sample hooks
  const sampleData = useSampleData();
  const loadSample = useStore((state) => state.sampleActions.loadSample);
  const pollSample = useStore((state) => state.sampleActions.pollSample);
  const logSelection = useLogSelection();

  useEffect(() => {
    if (sampleData.running && logSelection.logFile && logSelection.sample) {
      pollSample(logSelection.logFile, logSelection.sample);
    }
  }, []);

  // Load sample
  const prevCompleted = usePrevious(
    logSelection.sample?.completed !== undefined
      ? logSelection.sample.completed
      : true,
  );
  const prevLogFile = usePrevious<string | undefined>(logSelection.logFile);
  useEffect(() => {
    if (logSelection.logFile && logSelection.sample) {
      const currentSampleCompleted =
        logSelection.sample.completed !== undefined
          ? logSelection.sample.completed
          : true;

      if (
        prevLogFile !== logSelection.logFile ||
        sampleData.sample?.id !== logSelection.sample.id ||
        sampleData.sample?.epoch !== logSelection.sample.epoch ||
        currentSampleCompleted !== prevCompleted
      ) {
        loadSample(logSelection.logFile, logSelection.sample);
      }
    }
  }, [
    logSelection.logFile,
    logSelection.sample?.id,
    logSelection.sample?.epoch,
    logSelection.sample?.completed,
    sampleData.sample?.id,
    sampleData.sample?.epoch,
  ]);

  // Get sample navigation utilities
  const sampleNavigation = useSampleNavigation();
  const filteredSamples = useFilteredSamples();
  const selectedSampleIndex = sampleNavigation.selectedSampleIndex;

  // Calculate next and previous sample indexes
  const nextSampleIndex = useMemo(
    () =>
      selectedSampleIndex < filteredSamples.length - 1
        ? selectedSampleIndex + 1
        : -1,
    [filteredSamples, selectedSampleIndex],
  );

  const prevSampleIndex = useMemo(
    () => (selectedSampleIndex > 0 ? selectedSampleIndex - 1 : -1),
    [selectedSampleIndex],
  );

  // Create navigation handlers using only our hook
  const handleNextSample = useCallback(() => {
    // Only use the navigation hook for URL handling
    if (nextSampleIndex >= 0) {
      sampleNavigation.navigateToSample(nextSampleIndex);
    }
  }, [nextSampleIndex, sampleNavigation]);

  const handlePrevSample = useCallback(() => {
    // Only use the navigation hook for URL handling
    if (prevSampleIndex >= 0) {
      sampleNavigation.navigateToSample(prevSampleIndex);
    }
  }, [prevSampleIndex, sampleNavigation]);

  // Tools
  const tools = useMemo<ModalTools>(() => {
    const nextTool: ModalTool = {
      label: "Next Sample",
      icon: ApplicationIcons.next,
      onClick: handleNextSample,
      enabled: nextSampleIndex >= 0,
    };

    const prevTool: ModalTool = {
      label: "Previous Sample",
      icon: ApplicationIcons.previous,
      onClick: handlePrevSample,
      enabled: prevSampleIndex >= 0,
    };

    return {
      left: [prevTool],
      right: [nextTool],
    };
  }, [handlePrevSample, handleNextSample, nextSampleIndex, prevSampleIndex]);

  const handleKeyUp = useCallback(
    (e: KeyboardEvent) => {
      switch (e.key) {
        case "ArrowRight":
          handleNextSample();
          break;
        case "ArrowLeft":
          handlePrevSample();
          break;
        case "Escape":
          // Use the navigation hook to close the dialog
          sampleNavigation.closeDialog();
          break;
      }
    },
    [handlePrevSample, handleNextSample, sampleNavigation],
  );

  const onHide = useCallback(() => {
    // Use the navigation hook to close the dialog
    sampleNavigation.closeDialog();
  }, [sampleNavigation]);

  // Provide the dialog
  return (
    <LargeModal
      id={id}
      detail={title}
      detailTools={tools}
      onkeyup={handleKeyUp}
      visible={showingSampleDialog}
      onHide={onHide}
      showProgress={
        sampleData.status === "loading" || sampleData.status === "streaming"
      }
      scrollRef={scrollRef}
    >
      {sampleData.error ? (
        <ErrorPanel title="Sample Error" error={sampleData.error} />
      ) : (
        <SampleDisplay
          id={id}
          sample={sampleData.sample}
          runningEvents={sampleData.running}
          selectedTab={selectedTab}
          setSelectedTab={setSelectedTab}
          scrollRef={scrollRef}
        />
      )}
    </LargeModal>
  );
};
