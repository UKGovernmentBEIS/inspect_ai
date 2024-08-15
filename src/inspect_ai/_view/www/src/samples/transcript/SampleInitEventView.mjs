// @ts-check
import { html } from "htm/preact";
import { EventPanel } from "./EventPanel.mjs";
import { MetaDataGrid } from "../../components/MetaDataGrid.mjs";
import { ChatView } from "../../components/ChatView.mjs";
import { isBase64 } from "../../utils/Base64.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";

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

  const addtl_sample_data = [];

  if (event.sample.choices && event.sample.choices.length > 0) {
    addtl_sample_data.push(
      html`<div style=${{ fontSize: FontSize.small, ...TextStyle.label }}>
        Choices
      </div>`,
    );

    addtl_sample_data.push(
      html`<div style=${{ fontSize: FontSize.small, marginBottom: "1em" }}>
        ${event.sample.choices.map((choice, index) => {
          return html`<div>${String.fromCharCode(65 + index)}) ${choice}</div>`;
        })}
      </div>`,
    );
  }

  addtl_sample_data.push(
    html`<div style=${{ fontSize: FontSize.small, ...TextStyle.label }}>
      Target
    </div>`,
  );
  addtl_sample_data.push(
    html`<div style=${{ fontSize: FontSize.small, marginBottom: "1em" }}>
      ${event.sample.target}
    </div>`,
  );

  if (event.sample.files && Object.keys(event.sample.files).length > 0) {
    addtl_sample_data.push(
      html`<div style=${{ fontSize: FontSize.small, ...TextStyle.label }}>
        Files
      </div>`,
    );
    addtl_sample_data.push(
      html` <div
        style=${{
          display: "grid",
          gridTemplateColumns: "max-content 1fr",
          columnGap: "1em",
          marginBottom: "1em",
        }}
      >
        ${Object.keys(event.sample.files).map((key) => {
          if (event.sample.files) {
            const value = isBase64(event.sample.files[key])
              ? `<Base64 string>`
              : event.sample.files[key];
            return html`
              <div
                style=${{
                  fontSize: FontSize.small,
                  ...TextStyle.label,
                  ...TextStyle.secondary,
                }}
              >
                ${key}
              </div>
              <div style=${{ fontSize: FontSize.small }}>
                <code>${value}</code>
              </div>
            `;
          } else {
            return "";
          }
        })}
      </div>`,
    );
  }

  if (event.sample.setup) {
    addtl_sample_data.push(
      html`<div style=${{ fontSize: FontSize.small, ...TextStyle.label }}>
        Setup
      </div>`,
    );
    addtl_sample_data.push(html`<pre>${event.sample.setup}</pre>`);
  }

  if (event.sample.metadata) {
    addtl_sample_data.push(
      html`<div style=${{ fontSize: FontSize.small, ...TextStyle.label }}>
        Metadata
      </div>`,
    );
    addtl_sample_data.push(
      html`<${MetaDataGrid}
        entries=${event.sample.metadata}
        style=${{ marginBottom: "1em" }}
      />`,
    );
  }

  return html`
  <${EventPanel} id=${id} depth=${depth} title="Sample Init" icon=${ApplicationIcons.sample}>

    <div name="Summary">
      <${ChatView} messages=${stateObj["messages"]}/>
      <div style=${{ marginLeft: "2.1em" }}>${addtl_sample_data}</div>
    </div>

    <div name="Complete">
      <${MetaDataGrid} entries=${event.state} style=${{ margin: "1em 0" }}/>
    </div>

  </${EventPanel}>`;
};
