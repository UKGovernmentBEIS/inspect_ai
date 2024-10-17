import { html } from "htm/preact";
import { useCallback, useMemo } from "preact/hooks";

import { ApplicationIcons } from "../appearance/Icons.mjs";
import { LargeModal } from "../components/LargeModal.mjs";

import { SampleDisplay } from "./SampleDisplay.mjs";
import { ErrorPanel } from "../components/ErrorPanel.mjs";

export const SampleDialog = (props) => {
  const {
    id,
    index,
    title,
    sample,
    sampleDescriptor,
    nextSample,
    prevSample,
    sampleDialogVisible,
    hideSample,
    sampleStatus,
    sampleError,
    context,
  } = props;

  const tools = useMemo(() => {
    const nextTool = {
      label: "Next Sample",
      icon: ApplicationIcons.next,
      onclick: nextSample,
      enabled: !!nextSample,
    };

    const prevTool = {
      label: "Previous Sample",
      icon: ApplicationIcons.previous,
      onclick: prevSample,
      enabled: !!prevSample,
    };

    return {
      left: [prevTool],
      right: [nextTool],
    };
  }, [prevSample, nextSample]);

  const handleKeyUp = useCallback(
    (e) => {
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
          hideSample();
          break;
      }
    },
    [prevSample, nextSample],
  );

  // Provide the dialog
  return html`
    <${LargeModal} 
      id=${id} 
      detail=${title}
      detailTools=${tools}
      onkeyup=${handleKeyUp}   
      visible=${sampleDialogVisible}
      onHide=${hideSample}
      showProgress=${sampleStatus === "loading"}
    >
        ${
          sampleError
            ? html`<${ErrorPanel} title="Sample Error" error=${sampleError} />`
            : html`<${SampleDisplay}
                index=${index}
                id=${id}
                sample=${sample}
                sampleDescriptor=${sampleDescriptor}
                visible=${sampleDialogVisible}
                context=${context}
              />`
        }
    </${LargeModal}>`;
};
