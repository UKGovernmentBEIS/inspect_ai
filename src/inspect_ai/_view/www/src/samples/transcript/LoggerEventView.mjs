// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { FontSize } from "../../appearance/Fonts.mjs";
import { EventRow } from "./EventRow.mjs";

/**
 * Renders the LoggerEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").LoggerEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const LoggerEventView = ({ id, event }) => {
  // Create a Date object from the timestamp
  return html`
  <${EventRow} 
    id=${id}
    title=${event.message.level} 
    icon=${ApplicationIcons.logging[event.message.level.toLowerCase()]}  
    style="compact"
  >
  <div
    style=${{ width: "100%", display: "grid", gridTemplateColumns: "max-content 1fr", columnGap: "0.5em", fontSize: FontSize.base }}
  >
    <div>${event.message.filename} (L:${event.message.lineno})</div>
    <div>${event.message.message}</div>
  </div>
  </${EventRow}>`;
};
