// @ts-check
import { html } from "htm/preact";
import { ChatView } from "../../components/ChatView.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").StateEvent | import("../../types/log").StoreEvent} props.event - The event object to display.
 * @param {number} props.index - The index of the event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const StateEventView = ({ event, index }) => {
  const mutations = event.changes.map((change) => {
    return html`
      <div>${change.op}</div>
      <div>${change.path}</div>
      <div>${change.from}</div>
      <div>${renderValue(change, index)}</div>
    `;
  });

  return html`<div
    style=${{
      display: "grid",
      gridTemplateColumns: "auto auto auto auto",
      columnGap: "1em",
    }}
  >
    ${mutations}
  </div>`;
};

/**
 * Renders the value of a change based on its type.
 *
 * @param {import("../../types/log").JsonChange} change - The change object containing the value.
 * @param {number} index - The index of the change.
 * @returns {import("preact").JSX.Element|Object|string} - The rendered HTML template if the value is an object with content and source, otherwise the value itself.
 */
const renderValue = (change, index) => {
  if (change.value && typeof change.value === "object") {
    if (change.value["content"] && change.value["source"]) {
      return html`<${ChatView}
        id="model-input-${index}"
        messages=${[change.value]}
      />`;
    }
    return change.value;
  } else {
    return change.value;
  }
};
