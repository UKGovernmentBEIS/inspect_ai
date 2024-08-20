// @ts-check
import { html } from "htm/preact";
import { EventPanel } from "./EventPanel.mjs";
import { MetaDataGrid } from "../../components/MetaDataGrid.mjs";
import { ChatView } from "../../components/ChatView.mjs";
import { EventSection } from "./EventSection.mjs";

/**
 * Renders the SampleInitEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param { number } props.depth - The depth of this event.
 * @param {import("../../types/log").SampleInitEvent} props.event - The event object to display.
 * @param {import("./TranscriptState.mjs").StateManager} props.stateManager - A function that updates the state with a new state object.
 * @returns {import("preact").JSX.Element} The component.
 */
export const SampleInitEventView = ({ id, depth, event, stateManager }) => {
  /**
   * @type {Record<string, unknown>}
   */
  //@ts-ignore
  const stateObj = event.state;

  // Rememember the state (so other event viewers can use
  // it as a baseline when applying their state updates)
  stateManager.setState(stateObj);

  const sections = [];

  if (event.sample.files && Object.keys(event.sample.files).length > 0) {
    sections.push(html`<${EventSection} title="Files">
      ${Object.keys(event.sample.files).map((file) => {
        return html`<pre style=${{ marginBottom: "0" }}>${file}</pre>`;
      })}
      </${EventSection}>
  `);
  }

  if (event.sample.setup) {
    sections.push(html`<${EventSection} title="Setup">
      <pre style=${{ background: "var(--bs-light)", borderRadius: "3px" }}><code class="sourceCode" >${event.sample.setup}</code></pre>
      </${EventSection}>
  `);
  }

  return html`
  <${EventPanel} id=${id} depth=${depth}>
    
    <div name="Sample">
      <${ChatView} messages=${stateObj["messages"]}/>
      <div style=${{ marginLeft: "2.1em", marginBottom: "1em" }}>
        ${
          event.sample.choices
            ? event.sample.choices.map((choice, index) => {
                return html`<div>
                  ${String.fromCharCode(65 + index)}) ${choice}
                </div>`;
              })
            : ""
        }
        <div style=${{ display: "flex", flexWrap: "wrap", gap: "1em", overflowWrap: "break-word" }}>
        ${sections}
        </div>
        <${EventSection} title="Target">
          ${event.sample.target}
        </${EventSection}>
      </div>
    </div>
    ${event.sample.metadata && Object.keys(event.sample.metadata).length > 0 ? html`<${MetaDataGrid} name="Metadata" style=${{ margin: "1em 0" }} entries=${event.sample.metadata} />` : ""}

  </${EventPanel}>`;
};
