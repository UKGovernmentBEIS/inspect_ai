// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";
import { EventRow } from "./EventRow.mjs";

/**
 * Renders the LoggerEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param { number } props.depth - The depth of this event.
 * @param {import("../../types/log").LoggerEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const LoggerEventView = ({ id, depth, event }) => {
  // Create a Date object from the timestamp
  return html`
  <${EventRow} 
    id=${id}
    depth=${depth}
    title=${event.message.level} 
    icon=${ApplicationIcons.logging[event.message.level.toLowerCase()]}  
  >
  <div
    style=${{ width: "100%", display: "grid", gridTemplateColumns: "1fr max-content", columnGap: "1em", fontSize: FontSize.base }}
  >
    <div style=${{ fontSize: FontSize.smaller }}>${event.message.message}</div>
    <div style=${{ fontSize: FontSize.smaller, ...TextStyle.secondary }}>${event.message.filename}:${event.message.lineno}</div>
  </div>
  </${EventRow}>`;
};
