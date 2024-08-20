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
 * @param { number } props.depth - The depth of this event.
 * @param {import("../../types/log").ScoreEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ScoreEventView = ({ id, depth, event }) => {
  return html`
  <${EventPanel} id=${id} depth=${depth} title="Score" icon=${ApplicationIcons.scorer}>
  
    <div
      name="Explanation"
      style=${{ display: "grid", gridTemplateColumns: "max-content auto", columnGap: "1em", margin: "1em 0" }}
    >
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
      <div style=${{ ...TextStyle.label }}>Answer</div>
      <div>${event.score.answer}</div>
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
              style=${{ margin: "1em 0" }}
            />
          </div>`
        : undefined
    }


  </${EventPanel}>`;
};
