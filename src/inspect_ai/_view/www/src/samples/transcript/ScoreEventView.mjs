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
 * @param {Object} props.style - The style properties passed to the component.
 * @param {import("../../types/log").ScoreEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ScoreEventView = ({ id, event, style }) => {
  return html`
  <${EventPanel} id=${id} title="Score" icon=${ApplicationIcons.scorer} style=${style}>
  
    <div
      name="Explanation"
      style=${{ display: "grid", gridTemplateColumns: "max-content auto", columnGap: "1em", margin: "0.5em 0" }}
    >
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
      <div style=${{ ...TextStyle.label }}>Answer</div>
      <div><${MarkdownDiv} markdown=${event.score.answer}/></div>
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
      <div style=${{ ...TextStyle.label }}>Explanation</div>
      <div><${MarkdownDiv} markdown=${event.score.explanation}/></div>
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
      <div style=${{ ...TextStyle.label }}>Score</div>  
      <div>${event.score.value}</div>
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
    </div>
    ${
      event.score.metadata
        ? html`<div name="Metadata">
            <${MetaDataGrid}
              entries=${event.score.metadata}
              compact=${true}
              style=${{ margin: "0.5em 0" }}
            />
          </div>`
        : undefined
    }


  </${EventPanel}>`;
};
