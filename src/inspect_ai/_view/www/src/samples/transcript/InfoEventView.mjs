// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { EventPanel } from "./EventPanel.mjs";

/**
 * Renders the InfoEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").LoggerEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const InfoEventView = ({ id, event }) => {
  return html`
  <${EventPanel} id=${id} title="Info">
  <div
    style=${{ display: "grid", gridTemplateColumns: "auto auto" }}
  >
    <div><i class=${ApplicationIcons.logging.info} /></div>
    <div>${event.message}</div>
    <div></div>
  </div>
  </${EventPanel}>`;
};
