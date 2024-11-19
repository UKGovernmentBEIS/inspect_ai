// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { EventPanel } from "./EventPanel.mjs";

/**
 * Renders the InfoEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param { Object } props.style - The style of this event.
 * @param {import("../../types/log").SampleLimitEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const SampleLimitEventView = ({ id, event, style }) => {
  const resolve_title = (type) => {
    switch (type) {
      case "context":
        return "Context Limit Exceeded";
      case "time":
        return "Time Limit Execeeded";
      case "message":
        return "Message Limit Exceeded";
      case "token":
        return "Token Limit Exceeded";
      case "operator":
        return "Operator Canceled";
    }
  };

  const resolve_icon = (type) => {
    switch (type) {
      case "context":
        return ApplicationIcons.limits.context;
      case "time":
        return ApplicationIcons.limits.time;
      case "message":
        return ApplicationIcons.limits.messages;
      case "token":
        return ApplicationIcons.limits.tokens;
      case "operator":
        return ApplicationIcons.limits.operator;
    }
  };

  const title = resolve_title(event.type);
  const icon = resolve_icon(event.type);

  return html`
  <${EventPanel} id=${id} title=${title} icon=${icon} style=${style}>
    ${event.message}
  </${EventPanel}>`;
};
