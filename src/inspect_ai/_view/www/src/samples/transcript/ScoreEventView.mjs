// @ts-check
import { html } from "htm/preact";
import { MarkdownDiv } from "../../components/MarkdownDiv.mjs";
import { MetaDataGrid } from "../../components/MetaDataGrid.mjs";
import { EventPanel } from "./EventPanel.mjs";

/**
 * Renders the InfoEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").ScoreEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ScoreEventView = ({ event }) => {
  return html`
  <${EventPanel} title="Score">
  <div
    style=${{ display: "grid", gridTemplateColumns: "max-content auto", columnGap: "1em" }}
  >
    <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
    <div>Answer</div>
    <div>${event.score.answer}</div>
    <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
    <div>Explanation</div>
    <div><${MarkdownDiv} markdown=${event.score.explanation}/></div>
    <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
    <div>Score</div>  
    <div>${event.score.value}</div>
    <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
  </div>
          ${
            event.score.metadata
              ? html` <div style=${{ marginTop: "1em" }}>Metadata</div>
                  <${MetaDataGrid}
                    entries=${event.score.metadata}
                    compact=${true}
                  />`
              : ""
          }


  </${EventPanel}>`;
};
