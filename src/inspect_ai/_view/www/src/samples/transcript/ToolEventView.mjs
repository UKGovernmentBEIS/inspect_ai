// @ts-check
import { html } from "htm/preact";
import { MarkdownDiv } from "../../components/MarkdownDiv.mjs";
import { MetaDataGrid } from "../../components/MetaDataGrid.mjs";
import { EventPanel } from "./EventPanel.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { TextStyle } from "../../appearance/Fonts.mjs";

/**
 * Renders the InfoEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").ToolEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ToolEventView = ({ id, event }) => {
  return html`
  <${EventPanel} id=${id} title="Tool" icon=${ApplicationIcons.solvers.use_tools}>
  ${event.function}
  </${EventPanel}>`;
};
