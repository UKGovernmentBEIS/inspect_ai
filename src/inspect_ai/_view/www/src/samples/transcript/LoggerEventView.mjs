// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { EventPanel } from "./EventPanel.mjs";
import { FontSize } from "../../appearance/Fonts.mjs";

/**
 * Renders the LoggerEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").LoggerEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const LoggerEventView = ({ event }) => {

  // Create a Date object from the timestamp
  const date = new Date(event.message.created);

  return html`
  <${EventPanel}>
  <div
    style=${{ width: "100%", display: "grid", gridTemplateColumns: "max-content max-content max-content max-content 1fr", columnGap: "0.5em", fontSize: FontSize.base }}
  >
    <div><i class=${ApplicationIcons.logging[event.message.level.toLowerCase()]}/></div>
    <div>${date.toUTCString()}</div>
    <div>${event.message.name}</div>
    <div>${event.message.filename} (L:${event.message.lineno})</div>
    <div>${event.message.message}</div>
  </div>
  </${EventPanel}>`;
};
