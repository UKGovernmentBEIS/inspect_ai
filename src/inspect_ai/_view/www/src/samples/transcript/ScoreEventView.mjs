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
  const resolvedTarget = event.target
    ? Array.isArray(event.target)
      ? event.target.join("\n")
      : event.target
    : undefined;

  return html`
  <${EventPanel} id=${id} title="Score" icon=${ApplicationIcons.scorer} style=${style}>
  
    <div
      name="Explanation"
      style=${{ display: "grid", gridTemplateColumns: "max-content auto", columnGap: "1em", margin: "0.5em 0" }}
    >
      ${
        event.target
          ? html` <div
                style=${{
                  gridColumn: "1 / -1",
                  borderBottom: "solid 1px var(--bs-light-border-subtle",
                }}
              ></div>
              <div style=${{ ...TextStyle.label }}>Target</div>
              <div><${MarkdownDiv} markdown=${resolvedTarget} /></div>`
          : ""
      }
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
      <div style=${{ ...TextStyle.label }}>Answer</div>
      <div><${MarkdownDiv} markdown=${event.score.answer}/></div>
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
      <div style=${{ ...TextStyle.label }}>Explanation</div>
      <div><${MarkdownDiv} markdown=${event.score.explanation}/></div>
      <div style=${{ gridColumn: "1 / -1", borderBottom: "solid 1px var(--bs-light-border-subtle" }}></div>
      <div style=${{ ...TextStyle.label }}>Score</div>  
      <div>${renderScore(event.score.value)}</div>
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

const renderScore = (value) => {
  if (Array.isArray(value)) {
    return html`<${MetaDataGrid} entries=${value} />`;
  } else if (typeof value === "object") {
    return html`<${MetaDataGrid} entries=${value} />`;
  } else {
    return value;
  }
};
