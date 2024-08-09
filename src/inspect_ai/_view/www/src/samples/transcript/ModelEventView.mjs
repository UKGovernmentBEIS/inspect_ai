// @ts-check
import { html } from "htm/preact";
import { ChatView } from "../../components/ChatView.mjs";
import { EventPanel } from "./EventPanel.mjs";

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

  return html`
  <${EventPanel} id=${id} title="Model Call: ${event.model} ${subtitle}">
  
  <div style=${{ display: "grid", gridTemplateColumns: "1fr max-content" }}>
    <${ChatView}
      id="${id}-model-input}"
      name="Output"
      messages=${[...(outputMessages || [])]}
      />
  </div>

  </${EventPanel}>`;
};
