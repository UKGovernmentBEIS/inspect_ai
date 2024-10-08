// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { EventRow } from "./EventRow.mjs";

/**
 * Renders the ApprovalEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").ApprovalEvent} props.event - The event object to display.
 * @param { Object } props.style - The style of this event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ApprovalEventView = ({ id, event, style }) => {
  return html`
  <${EventRow}
      id=${id}
      title="${decisionLabel(event.decision)}"
      icon=${decisionIcon(event.decision)}  
      style=${style}
    >
    ${event.explanation}
  </${EventRow}>`;
};

/**
 * Determines the label for a decision
 *
 * @param {string} decision - The decision
 * @returns {string} The label for this decision.
 */
const decisionLabel = (decision) => {
  switch (decision) {
    case "approve":
      return "Approved";
    case "reject":
      return "Rejected";
    case "terminate":
      return "Terminated";
    case "escalate":
      return "Escalated";
    case "modify":
      return "Modified";
    default:
      return decision;
  }
};

/**
 * Determines the icon for a decision
 *
 * @param {string} decision - The decision
 * @returns {string} The icon for this decision.
 */
const decisionIcon = (decision) => {
  switch (decision) {
    case "approve":
      return ApplicationIcons.approvals.approve;
    case "reject":
      return ApplicationIcons.approvals.reject;
    case "terminate":
      return ApplicationIcons.approvals.terminate;
    case "escalate":
      return ApplicationIcons.approvals.escalate;
    case "modify":
      return ApplicationIcons.approvals.modify;
    default:
      return ApplicationIcons.approve;
  }
};
