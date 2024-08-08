// @ts-check
import { html } from "htm/preact";
import { TranscriptView } from "./TranscriptView.mjs";
import { EventPanel } from "./EventPanel.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").SubtaskEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const SubtaskEventView = ({ id, event }) => {
  return html`
    <${EventPanel} id=${id} title="Subtask: ${event.name}">
    <${TranscriptView}
      evalEvents=${event.events}
    />
    </${EventPanel}>`;
};
