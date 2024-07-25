// @ts-check
import { html } from "htm/preact";
import { TranscriptEvent } from "./TranscriptEvent.mjs";
import { MetaDataView } from "../../components/MetaDataView.mjs";
import { MarkdownDiv } from "../../components/MarkdownDiv.mjs";

/**
 * Renders the InfoEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").ScoreEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ScoreEventView = ({ event }) => {
  console.log({ event });
  return html`
  <${TranscriptEvent} name="Score">
  <div
    style=${{ display: "grid", gridTemplateColumns: "max-content auto", columnGap: "1em" }}
  >
    <div>Answer</div>
    <div>${event.score.answer}</div>
    <div>Explanation</div>
    <div><${MarkdownDiv} markdown=${event.score.explanation}/></div>
    <div>Score</div>  
    <div>${event.score.value}</div>
  </div>
  ${
    event.score.metadata
      ? html` <div style=${{marginTop: "0.5rem"}}>Scorer Metadata</div>
          <${MetaDataView} entries=${event.score.metadata} compact=${true} />`
      : ""
  }
    

  </${TranscriptEvent}>`;
};
