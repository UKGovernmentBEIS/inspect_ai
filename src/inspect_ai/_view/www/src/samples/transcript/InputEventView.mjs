// @ts-check
import { html } from "htm/preact";
import { EventPanel } from "./EventPanel.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { ANSIDisplay } from "../../components/AnsiDisplay.mjs";
import { formatDateTime } from "../../utils/Format.mjs";

/**
 * Renders the ErrorEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").InputEvent} props.event - The event object to display.
 * @param { Object } props.style - The style of this event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const InputEventView = ({ id, event, style }) => {
  return html`
  <${EventPanel} id=${id} title="Input" subTitle=${formatDateTime(new Date(event.timestamp))} icon=${ApplicationIcons.input} style=${style}>
    <${ANSIDisplay} output=${event.input_ansi} style=${{ fontSize: "clamp(0.4rem, 1.15vw, 0.9rem)", ...style }}/>
  </${EventPanel}>`;
};
