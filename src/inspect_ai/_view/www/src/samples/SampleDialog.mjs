import { html } from "htm/preact";

import { icons } from "../Constants.mjs";
import { EmptyPanel } from "../components/EmptyPanel.mjs";
import { LargeModal } from "../components/LargeModal.mjs";

import { SampleDisplay } from "./SampleDisplay.mjs"

export const SampleDialog = (props) => {
  const {
    id,
    index,
    task,
    model,
    title,
    sample,
    sampleDescriptor,
    nextSample,
    prevSample,
    context,
  } = props;

  // If there is no sample, just show an empty panel
  // This should never happen
  if (!sample) {
    return html`<${LargeModal} id=${id} title="No Sample"><${EmptyPanel}>No Sample Selected</${EmptyPanel}></${LargeModal}>`;
  }

  const nextTool = {
    label: "Next Sample",
    icon: icons.next,
    onclick: nextSample,
    enabled: !!nextSample,
  };

  const prevTool = {
    label: "Previous Sample",
    icon: icons.previous,
    onclick: prevSample,
    enabled: !!prevSample,
  };

  // Provide the dialog
  return html`
    <${LargeModal} 
      id=${id} 
      detail=${title}
      detailTools=${{
        left: [prevTool],
        right: [nextTool],
      }}
      onkeyup=${(e) => {
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
        }
      }}   
    >
    <${SampleDisplay}
      index=${index}
      id=${id}
      sample=${sample}
      sampleDescriptor=${sampleDescriptor}
      context=${context}/>
    </${LargeModal}>`;
};

