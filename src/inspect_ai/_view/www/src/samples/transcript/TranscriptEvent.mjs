// @ts-check
import { html } from "htm/preact";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string} props.name - The name of the event
 * @param {import("preact").ComponentChildren} props.children - The rendered event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const TranscriptEvent = ({name, children}) => {
  return html`
    <div>
      <div style=${{ textTransform: "uppercase", fontSize: "0.7rem" }}>${name}</div>
      <div>${children}</div>
    </div>`;
}