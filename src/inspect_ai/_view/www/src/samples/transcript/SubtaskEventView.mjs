// @ts-check
import { html } from "htm/preact";
import { TranscriptView } from "./TranscriptView.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").SubtaskEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const SubtaskEventView = ({ event }) => {
  return html`<${TranscriptView} transcript=${event.transcript} />`;
};
