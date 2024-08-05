// @ts-check
import { html } from "htm/preact";
import { TranscriptView } from "./transcript/TranscriptView.mjs";

/**
 * Renders the SampleTranscript component.
 *
 * @param {Object} params - The parameters for the component.
 * @param {import("../types/log").EvalEvents} params.eval_events - The transcript to display.
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
export const SampleTranscript = ({ eval_events }) => {
  return html`<${TranscriptView} transcript=${eval_events} />`;
};
