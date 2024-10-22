import { html } from "htm/preact";
import { useCallback, useMemo } from "preact/hooks";

import { ApplicationIcons } from "../appearance/Icons.mjs";
import { LargeModal } from "../components/LargeModal.mjs";

import { SampleDisplay } from "./SampleDisplay.mjs";
import { ErrorPanel } from "../components/ErrorPanel.mjs";

export const SampleDialog = (props) => {
  const {
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
          setShowingSampleDialog(false);
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
      visible=${showingSampleDialog}
      onHide=${() => {
        setShowingSampleDialog(false);
      }}
      showProgress=${sampleStatus === "loading"}
    >
        ${
          sampleError
            ? html`<${ErrorPanel} title="Sample Error" error=${sampleError} />`
            : html`<${SampleDisplay}
                id=${id}
                sample=${sample}
                sampleDescriptor=${sampleDescriptor}
                visible=${showingSampleDialog}
                context=${context}
              />`
        }
    </${LargeModal}>`;
};
