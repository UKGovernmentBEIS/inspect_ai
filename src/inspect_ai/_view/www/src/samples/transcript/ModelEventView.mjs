// @ts-check
import { html } from "htm/preact";
import { MetaDataView } from "../../components/MetaDataView.mjs";
import { ChatView } from "../../components/ChatView.mjs";
import { EventPanel } from "./EventPanel.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").ModelEvent} props.event - The event object to display.
 * @param {string} props.baseId - The baseId of the event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ModelEventView = ({ event, baseId }) => {
  const tools = event.tools
    .map((tool) => {
      return tool.name;
    })
    .join(",");

  const modelProperties = {
    ...event.config,
  };

  if (tools.length > 0) {
    modelProperties["tools"] = tools;
    modelProperties["tool_choice"] = event.tool_choice;
  }

  if (event.output.usage) {
    modelProperties["usage"] = event.output.usage;
  }

  const outputMessages = event.output.choices.map((choice) => {
    return choice.message;
  });

  return html`
  <${EventPanel} title="Model Call: ${event.model}">
  <div>
    <${MetaDataView} entries=${modelProperties} compact=${true} />
  </div>
  <div>
    <${ChatView}
      id="model-input-${baseId}"
      messages=${[...outputMessages]}
      />
  </div>  
  </${EventPanel}>`;
};
