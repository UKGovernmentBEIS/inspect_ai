import { LargeModal, ModalTool, ModalTools } from "../../components/LargeModal";
import { ApplicationIcons } from "../appearance/icons";

import { FC, Ref, useCallback, useMemo, useRef } from "react";
import { ErrorPanel } from "../../components/ErrorPanel";
import { useSampleData } from "../../state/hooks";
import { useStatefulScrollPosition } from "../../state/scrolling";
import { useSampleLoader } from "../../state/useSampleLoader";
import { useSamplePolling } from "../../state/useSamplePolling";
import { SampleDisplay } from "./SampleDisplay";

import { useSampleNavigation } from "../routing/sampleNavigation";
import styles from "./SampleDialog.module.css";

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

  // Use shared hooks for loading and polling
  useSampleLoader();
  useSamplePolling();

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
    [sampleNavigation],
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
      classNames={{
        body: styles.modalBody,
      }}
      showProgress={
        sampleData.status === "loading" || sampleData.status === "streaming"
      }
      scrollRef={scrollRef}
    >
      {sampleData.error ? (
        <ErrorPanel title="Sample Error" error={sampleData.error} />
      ) : (
        <SampleDisplay id={id} scrollRef={scrollRef} focusOnLoad={true} />
      )}
    </LargeModal>
  );
};
