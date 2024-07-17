// @ts-check
import { html } from "htm/preact";
import { MetaDataView } from "../../components/MetaDataView.mjs";
import { ChatView } from "../../components/ChatView.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").ModelEvent} props.event - The event object to display.
 * * @param {number} props.index - The index of the event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ModelEventView = ({ event, index }) => {
  const contents = {};
  contents["model"] = html`<b>${event.model}</b>`;
  if (event.config && Object.keys(event.config).length > 0) {
    contents["config"] = html`<${MetaDataView}
      entries=${event.config}
    />`;
  }
  contents["input"] = html`<${ChatView}
    id="model-input-${index}"
    messages=${event.input}
  />`;
  const outputMessages = event.output.choices.map((choice) => {
    return choice.message;
  });
  contents["output"] = html`<${ChatView}
    id="model-output-${index}"
    messages=${outputMessages}
  />`;

  return html`<div
    style=${{
      display: "grid",
      gridTemplateColumns: "auto auto",
      columnGap: "1em",
    }}
  >
    ${Object.keys(contents).map((key) => {
      return html`<div>${key}</div>
        <div>${contents[key]}</div>`;
    })}
  </div>`;

};
