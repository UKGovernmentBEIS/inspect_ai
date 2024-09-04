// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { EventPanel } from "./EventPanel.mjs";
import { JSONPanel } from "../../components/JsonPanel.mjs";

/**
 * Renders the InfoEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param { number } props.depth - The depth of this event.
 * @param {import("../../types/log").InfoEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const InfoEventView = ({ id, depth, event }) => {
  return html`
  <${EventPanel} id=${id} depth=${depth} title="Info" icon=${ApplicationIcons.info}>
    <${JSONPanel} data=${event.data} style=${{ margin: "1em 0" }}/>
  </${EventPanel}>`;
};
