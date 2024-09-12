import { html } from "htm/preact";
import { useCallback, useMemo } from "preact/hooks";

import { ApplicationIcons } from "../appearance/Icons.mjs";
import { EmptyPanel } from "../components/EmptyPanel.mjs";
import { LargeModal } from "../components/LargeModal.mjs";

import { SampleDisplay } from "./SampleDisplay.mjs";

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
    context,
  } = props;

  // If there is no sample, just show an empty panel
  // This should never happen
  if (!sample) {
    return html`<${LargeModal} visible=${sampleDialogVisible} onHide=${hideSample} id=${id} title="No Sample"><${EmptyPanel}>No Sample Selected</${EmptyPanel}></${LargeModal}>`;
  }

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
    >
    <${SampleDisplay}
      index=${index}
      id=${id}
      sample=${sample}
      sampleDescriptor=${sampleDescriptor}
      visible=${sampleDialogVisible}
      context=${context}/>
    </${LargeModal}>`;
};
