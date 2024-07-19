// @ts-check
import { html } from "htm/preact";
import { ChatView } from "../../components/ChatView.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").StateEvent | import("../../types/log").StoreEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const StateEventView = ({ event }) => {
  const mutations = event.changes.map((change) => {
    // TODO: change.from is always undefined

    // Compute the change rows
    const symbol = iconForOp(change.op);
    const background = backgroundForOp(change.op);
    const toStyle = {
      background: background ? background.to : "initial",
    };
    const baseStyle = {};
    return html`
      <div style=${baseStyle}>${symbol ? symbol : ""}</div>
      <code style=${baseStyle}>${change.path}</code>
      <div style=${toStyle}>${renderValue(change)}</div>
    `;
  });

  // Compute the title
  const title = event.event === "state" ? "State Updated" : "Store Updated";

  return html` <div style=${{ textTransform: "uppercase", fontSize: "0.7rem" }}>
      ${title}
    </div>
    <div
      style=${{
        display: "grid",
        gridTemplateColumns: "max-content max-content 1fr",
        columnGap: "1em",
      }}
    >
      ${mutations}
    </div>`;
};

/**
 * Returns a symbol representing the operation type.
 *
 * @param {string} op - The operation type.
 * @returns {import("preact").JSX.Element | undefined} The component.
 */
const iconForOp = (op) => {
  switch (op) {
    case "add":
      return html`<i class="${ApplicationIcons.changes.add}" />`;
    case "remove":
      return html`<i class="${ApplicationIcons.changes.remove}" />`;
    case "replace":
      return html`<i class="${ApplicationIcons.changes.replace}" />`;
    case "copy":
    case "move":
    case "test":
    default:
      return undefined;
  }
};

/**
 * Returns a background color configuration based on the operation type.
 *
 * @param {string} op - The operation type.
 * @returns {{from: string, to: string}|undefined} - The background color configuration, or undefined for certain operations.
 */
const backgroundForOp = (op) => {
  switch (op) {
    case "add":
      return {
        from: "#dafbe1",
        to: "#dafbe1",
      };
    case "remove":
      return {
        from: "#ffebe9",
        to: "#ffebe9",
      };
    case "replace":
      return {
        from: "#ffebe9",
        to: "#dafbe1",
      };
    case "copy":
    case "move":
    case "test":
    default:
      return undefined;
  }
};

/**
 * Renders the value of a change based on its type.
 *
 * @param {import("../../types/log").JsonChange} change - The change object containing the value.
 * @returns {import("preact").JSX.Element|Object|string} - The rendered HTML template if the value is an object with content and source, otherwise the value itself.
 */
const renderValue = (change) => {
  const contents =
    typeof change.value === "object" || Array.isArray(change.value)
      ? JSON.stringify(change.value, null, 2)
      : change.value;

  return html`<pre style=${{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
${contents}</pre
  >`;
};
