// @ts-check
import { html } from "htm/preact";
import { EventPanel } from "./EventPanel.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { ANSIDisplay } from "../../components/AnsiDisplay.mjs";

/**
 * Renders the ErrorEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param { number } props.depth - The depth of this event.
 * @param {import("../../types/log").ErrorEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ErrorEventView = ({ id, depth, event }) => {
  return html`
  <${EventPanel} id=${id} depth=${depth} title="Error" icon=${ApplicationIcons.error}>
    <${ANSIDisplay} output=${event.error.traceback_ansi} style=${{ fontSize: "clamp(0.5rem, calc(0.25em + 1vw), 0.8rem)", margin: "1em 0" }}/>
  </${EventPanel}>`;
};
