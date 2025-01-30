import { ApplicationIcons } from "../appearance/icons";
import { LargeModal, ModalTool, ModalTools } from "../components/LargeModal";

import { Ref, RefObject, useCallback, useMemo, useRef } from "react";
import { ErrorPanel } from "../components/ErrorPanel";
import { EvalSample } from "../types/log";
import { SampleDisplay } from "./SampleDisplay";
import { SamplesDescriptor } from "./descriptor/samplesDescriptor";

interface SampleDialogProps {
  id: string;
  title: string;
  sampleStatus: string;
  sampleError?: Error;
  sample?: EvalSample;
  sampleDescriptor: SamplesDescriptor;
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
export const SampleDialog: React.FC<SampleDialogProps> = ({
  id,
  title,
  sample,
  sampleDescriptor,
  nextSample,
  prevSample,
  sampleStatus,
  sampleError,
  showingSampleDialog,
  setShowingSampleDialog,
  selectedTab,
  setSelectedTab,
  sampleScrollPositionRef,
  setSampleScrollPosition,
}) => {
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
    [prevSample, nextSample],
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
      showProgress={sampleStatus === "loading"}
      initialScrollPositionRef={sampleScrollPositionRef}
      setInitialScrollPosition={setSampleScrollPosition}
      scrollRef={scrollRef}
    >
      {sampleError ? (
        <ErrorPanel title="Sample Error" error={sampleError} />
      ) : (
        <SampleDisplay
          id={id}
          sample={sample}
          sampleDescriptor={sampleDescriptor}
          selectedTab={selectedTab}
          setSelectedTab={setSelectedTab}
          scrollRef={scrollRef}
        />
      )}
    </LargeModal>
  );
};
