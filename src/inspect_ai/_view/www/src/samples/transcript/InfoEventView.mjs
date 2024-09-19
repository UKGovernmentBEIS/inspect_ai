// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { EventPanel } from "./EventPanel.mjs";
import { JSONPanel } from "../../components/JsonPanel.mjs";
import { MarkdownDiv } from "../../components/MarkdownDiv.mjs";

/**
 * Renders the InfoEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param { Object } props.style - The depth of this event.
 * @param {import("../../types/log").InfoEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const InfoEventView = ({ id, event, style }) => {
  const panels = [];
  if (typeof event.data === "string") {
    panels.push(
      html`<${MarkdownDiv}
        markdown=${event.data}
        style=${{ margin: "0.5em 0" }}
      />`,
    );
  } else {
    panels.push(
      html`<${JSONPanel} data=${event.data} style=${{ margin: "0.5em 0" }} />`,
    );
  }

  return html`
  <${EventPanel} id=${id} title="Info" icon=${ApplicationIcons.info} style=${style}>
    ${panels}
  </${EventPanel}>`;
};
