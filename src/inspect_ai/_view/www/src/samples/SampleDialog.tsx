import { ApplicationIcons } from "../appearance/icons";
import { LargeModal, ModalTool, ModalTools } from "../components/LargeModal";

import { FC, Ref, RefObject, useCallback, useMemo, useRef } from "react";
import { ErrorPanel } from "../components/ErrorPanel";
import { useSampleContext } from "../contexts/SampleContext";
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
  sampleScrollPositionRef: RefObject<number>;
  setSampleScrollPosition: (position: number) => void;
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
  sampleScrollPositionRef,
  setSampleScrollPosition,
}) => {
  const sampleContext = useSampleContext();
  const scrollRef: Ref<HTMLDivElement> = useRef(null);

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
      showProgress={sampleContext.state.sampleStatus === "loading"}
      initialScrollPositionRef={sampleScrollPositionRef}
      setInitialScrollPosition={setSampleScrollPosition}
      scrollRef={scrollRef}
    >
      {sampleContext.state.sampleError ? (
        <ErrorPanel
          title="Sample Error"
          error={sampleContext.state.sampleError}
        />
      ) : (
        <SampleDisplay
          id={id}
          sample={sampleContext.state.selectedSample}
          runningSampleData={sampleContext.state.runningSampleData}
          selectedTab={selectedTab}
          setSelectedTab={setSelectedTab}
          scrollRef={scrollRef}
        />
      )}
    </LargeModal>
  );
};
