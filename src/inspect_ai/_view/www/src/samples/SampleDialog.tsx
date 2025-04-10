import { ApplicationIcons } from "../appearance/icons";
import { LargeModal, ModalTool, ModalTools } from "../components/LargeModal";

import { FC, Ref, useCallback, useEffect, useMemo, useRef } from "react";
import { ErrorPanel } from "../components/ErrorPanel";
import { useLogSelection, usePrevious, useSampleData } from "../state/hooks";
import { useStatefulScrollPosition } from "../state/scrolling";
import { useStore } from "../state/store";
import { SampleDisplay } from "./SampleDisplay";

interface SampleDialogProps {
  id: string;
  title: string;
  selectedTab?: string;
  setSelectedTab: (tab: string) => void;
  showingSampleDialog: boolean;
  setShowingSampleDialog: (showing: boolean) => void;
  nextSample: () => void;
  prevSample: () => void;
}

/**
 * Inline Sample Display
 */
export const SampleDialog: FC<SampleDialogProps> = ({
  id,
  title,
  nextSample,
  prevSample,
  showingSampleDialog,
  setShowingSampleDialog,
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

  // Tools
  const tools = useMemo<ModalTools>(() => {
    const nextTool: ModalTool = {
      label: "Next Sample",
      icon: ApplicationIcons.next,
      onClick: nextSample,
      enabled: !!nextSample,
    };

    const prevTool: ModalTool = {
      label: "Previous Sample",
      icon: ApplicationIcons.previous,
      onClick: prevSample,
      enabled: !!prevSample,
    };

    return {
      left: [prevTool],
      right: [nextTool],
    };
  }, [prevSample, nextSample]);

  const handleKeyUp = useCallback(
    (e: KeyboardEvent) => {
      switch (e.key) {
        case "ArrowRight":
          if (nextSample) {
            nextSample();
          }
          break;
        case "ArrowLeft":
          if (prevSample) {
            prevSample();
          }
          break;
        case "Escape":
          setShowingSampleDialog(false);
          break;
      }
    },
    [prevSample, nextSample, setShowingSampleDialog],
  );

  const onHide = useCallback(() => {
    setShowingSampleDialog(false);
  }, [setShowingSampleDialog]);

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
