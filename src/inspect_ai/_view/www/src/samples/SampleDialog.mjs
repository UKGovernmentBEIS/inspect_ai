import { html } from "htm/preact";
import { useCallback, useMemo } from "preact/hooks";

import { ApplicationIcons } from "../appearance/Icons.mjs";
import { LargeModal } from "../components/LargeModal.mjs";

import { SampleDisplay } from "./SampleDisplay.mjs";
import { ErrorPanel } from "../components/ErrorPanel.mjs";

/**
 * Inline Sample Display
 *
 * @param {Object} props - The parameters for the component.
 * @param {string} props.id - The task id
 * @param {string} props.title - The task title
 * @param {string} props.sampleStatus - the sample status
 * @param {Error} [props.sampleError] - sample error
 * @param {import("../types/log").EvalSample} [props.sample] - the sample
 * @param {import("../samples/SamplesDescriptor.mjs").SamplesDescriptor} props.sampleDescriptor - the sample descriptor
 * @param {string} props.selectedTab - The selected tab
 * @param {(tab: string) => void} props.setSelectedTab - function to set the selected tab
 * @param {boolean} props.showingSampleDialog - whether the dialog is showing
 * @param {(showing: boolean) => void} props.setShowingSampleDialog - function to set whether the dialog is showing
 * @param {() => void} [props.nextSample] - function to move to next sample
 * @param {() => void} [props.prevSample] - function to move to previous sample
 * @param {import("../Types.mjs").RenderContext} props.context - the app context
 * @returns {import("preact").JSX.Element} The TranscriptView component.
 */
export const SampleDialog = ({
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
  context,
}) => {
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
                selectedTab=${selectedTab}
                setSelectedTab=${setSelectedTab}
                context=${context}
              />`
        }
    </${LargeModal}>`;
};
