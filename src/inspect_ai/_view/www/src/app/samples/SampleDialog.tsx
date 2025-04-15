import { LargeModal, ModalTool, ModalTools } from "../../components/LargeModal";
import { ApplicationIcons } from "../appearance/icons";

import { FC, Ref, useCallback, useEffect, useMemo, useRef } from "react";
import { ErrorPanel } from "../../components/ErrorPanel";
import { useLogSelection, usePrevious, useSampleData } from "../../state/hooks";
import { useStatefulScrollPosition } from "../../state/scrolling";
import { useStore } from "../../state/store";
import { useSampleNavigation } from "../routing/navigationHooks";
import { SampleDisplay } from "./SampleDisplay";

interface SampleDialogProps {
  id: string;
  title: string;
  showingSampleDialog: boolean;
}

/**
 * Inline Sample Display
 */
export const SampleDialog: FC<SampleDialogProps> = ({
  id,
  title,
  showingSampleDialog,
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
        (prevLogFile !== undefined && prevLogFile !== logSelection.logFile) ||
        sampleData.sample?.id !== logSelection.sample.id ||
        sampleData.sample?.epoch !== logSelection.sample.epoch ||
        (prevCompleted !== undefined &&
          currentSampleCompleted !== prevCompleted)
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

  // Tools
  const tools = useMemo<ModalTools>(() => {
    const nextTool: ModalTool = {
      label: "Next Sample",
      icon: ApplicationIcons.next,
      onClick: sampleNavigation.nextSample,
      enabled: sampleNavigation.nextEnabled,
    };

    const prevTool: ModalTool = {
      label: "Previous Sample",
      icon: ApplicationIcons.previous,
      onClick: sampleNavigation.previousSample,
      enabled: sampleNavigation.previousEnabled,
    };

    return {
      left: [prevTool],
      right: [nextTool],
    };
  }, [
    sampleNavigation.nextSample,
    sampleNavigation.previousSample,
    sampleNavigation.nextEnabled,
    sampleNavigation.previousEnabled,
  ]);

  const handleKeyUp = useCallback(
    (e: KeyboardEvent) => {
      switch (e.key) {
        case "ArrowRight":
          sampleNavigation.nextSample();
          break;
        case "ArrowLeft":
          sampleNavigation.previousSample();
          break;
        case "Escape":
          // Use the navigation hook to close the dialog
          sampleNavigation.clearSampleUrl();
          break;
      }
    },
    [
      sampleNavigation.nextSample,
      sampleNavigation.previousSample,
      sampleNavigation.clearSampleUrl,
    ],
  );

  const onHide = useCallback(() => {
    // Use the navigation hook to close the dialog
    sampleNavigation.clearSampleUrl();
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
        <SampleDisplay id={id} scrollRef={scrollRef} />
      )}
    </LargeModal>
  );
};
