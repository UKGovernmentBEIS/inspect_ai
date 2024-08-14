// @ts-check
import { html } from "htm/preact";
import { TranscriptView } from "./transcript/TranscriptView.mjs";
import { initStateManager } from "./transcript/TranscriptState.mjs";

/**
 * Renders the SampleTranscript component.
 *
 * @param {Object} params - The parameters for the component.
 * @param {string} params.id - The id of this component
 * @param {import("../types/log").EvalEvents} params.evalEvents - The transcript to display.
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
export const SampleTranscript = ({ id, evalEvents }) => {
  const stateManager = initStateManager();

  return html`<${TranscriptView}
    id=${id}
    evalEvents=${evalEvents}
    stateManager=${stateManager}
  />`;
};
