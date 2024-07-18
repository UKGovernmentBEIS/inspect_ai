// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";

/**
 * Renders the LoggerEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").LoggerEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const LoggerEventView = ({ event }) => {
  return html` <div
    style=${{ display: "grid", gridTemplateColumns: "auto auto" }}
  >
    <div><i class=${ApplicationIcons.logging[event.level]} /></div>
    <div>${event.message}</div>
    <div></div>
  </div>`;
};
