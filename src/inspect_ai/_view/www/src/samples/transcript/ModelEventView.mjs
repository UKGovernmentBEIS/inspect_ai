// @ts-check
import { html } from "htm/preact";
import { ChatView } from "../../components/ChatView.mjs";
import { EventPanel } from "./EventPanel.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { MetaDataGrid } from "../../components/MetaDataGrid.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").ModelEvent} props.event - The event object to display.
 * @param {string} props.baseId - The baseId of the event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ModelEventView = ({ id, event }) => {
  const totalUsage = event.output.usage?.total_tokens;
  const subtitle = totalUsage ? `(${totalUsage} tokens)` : "";

  // Note: despite the type system saying otherwise, this has appeared empircally
  // to sometimes be undefined
  const outputMessages = event.output.choices?.map((choice) => {
    return choice.message;
  });

  const entries = { ...event.config };
  if (event.tools) {
    entries["tools"] = event.tools;
    entries["tool_choice"] = event.tool_choice;
  }

  return html`
  <${EventPanel} id=${id} title="Model Call: ${event.model} ${subtitle}" icon=${ApplicationIcons.model}>
  
    <div name="Answer">
    <${ChatView}
      id="${id}-model-output"
      messages=${[...(outputMessages || [])]}
      />
    </div>

    <${MetaDataGrid} name="Config" entries=${entries} style=${{ margin: "1em 0" }}/>


    <${ChatView}
      id="${id}-model-input-full"
      name="All Msgs"
      messages=${[...event.input, ...(outputMessages || [])]}
      />      

  </${EventPanel}>`;
};
