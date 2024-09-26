// @ts-check
import { html } from "htm/preact";
import { EventPanel } from "./EventPanel.mjs";
import { MetaDataGrid } from "../../components/MetaDataGrid.mjs";
import { ChatView } from "../../components/ChatView.mjs";
import { EventSection } from "./EventSection.mjs";
import { toArray } from "../../utils/Type.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";

/**
 * Renders the SampleInitEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").SampleInitEvent} props.event - The event object to display.
 * @param {Object} props.style - The style for this view
 * @returns {import("preact").JSX.Element} The component.
 */
export const SampleInitEventView = ({ id, event, style }) => {
  /**
   * @type {Record<string, unknown>}
   */
  //@ts-ignore
  const stateObj = event.state;

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
      <pre style=${{ background: "var(--bs-light)", borderRadius: "var(--bs-border-radius)" }}><code class="sourceCode" >${event.sample.setup}</code></pre>
      </${EventSection}>
  `);
  }

  return html`
  <${EventPanel} id=${id} style=${style} title="Sample" icon=${ApplicationIcons.sample}>
    <div name="Sample" style=${{ margin: "1em 0em" }}>
      <${ChatView} messages=${stateObj["messages"]}/>
      <div>
        ${
          event.sample.choices
            ? event.sample.choices.map((choice, index) => {
                return html`<div>
                  ${String.fromCharCode(65 + index)}) ${choice}
                </div>`;
              })
            : ""
        }
        ${
          sections.length > 0
            ? html`
                <div
                  style=${{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: "1em",
                    overflowWrap: "break-word",
                  }}
                >
                  ${sections}
                </div>
              `
            : ""
        }
        <${EventSection} title="Target">
          ${toArray(event.sample.target).map((target) => {
            return html`<div>${target}</div>`;
          })}
        </${EventSection}>
      </div>
    </div>
    ${event.sample.metadata && Object.keys(event.sample.metadata).length > 0 ? html`<${MetaDataGrid} name="Metadata" style=${{ margin: "0.5em 0" }} entries=${event.sample.metadata} />` : ""}

  </${EventPanel}>`;
};
