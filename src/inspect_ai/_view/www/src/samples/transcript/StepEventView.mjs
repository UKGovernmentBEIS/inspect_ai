// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { EventPanel } from "./EventPanel.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { number } props.depth - The depth of this event.
 * @param {import("../../types/log").StepEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const StepEventView = ({ depth, event }) => {
  const icon = () => {
    if (event.type === "solver") {
      switch (event.name) {
        case "chain_of_thought":
          return ApplicationIcons.solvers.chain_of_thought;
        case "generate":
          return ApplicationIcons.solvers.generate;
        case "self_critique":
          return ApplicationIcons.solvers.self_critique;
        case "system_message":
          return ApplicationIcons.solvers.system_message;
        case "use_tools":
          return ApplicationIcons.solvers.use_tools;
        case "multiple_choice":
          return ApplicationIcons["multiple-choice"];
        default:
          return ApplicationIcons.solvers.default;
      }
    } else if (event.type === "scorer") {
      return ApplicationIcons.scorer;
    } else {
      return ApplicationIcons.step;
    }
  };

  if (event.action === "end" || event.type === "generate_loop") {
    // end events have no special implicit UI
    return html``;
  }

  return html`<${EventPanel}
    title="${event.type ? event.type + ": " : "Step: "}${event.name}"
    depth=${depth}
    icon=${icon()}
    style=${{ background: "var(--bs-light" }}
  />`;
};
