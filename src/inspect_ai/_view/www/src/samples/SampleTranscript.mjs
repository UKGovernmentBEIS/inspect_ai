// @ts-check
import { html } from "htm/preact";
import { TranscriptView } from "./transcript/TranscriptView.mjs";

/**
 * Renders the SampleTranscript component.
 *
 * @param {Object} params - The parameters for the component.
 * @param {string} params.id - The id of this component
 * @param {import("../types/log").Events} params.evalEvents - The transcript to display.
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
export const SampleTranscript = ({ id, evalEvents }) => {
  return html`<${TranscriptView} id=${id} events=${evalEvents} />`;
};
