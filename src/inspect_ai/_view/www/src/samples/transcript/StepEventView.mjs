// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { EventPanel } from "./EventPanel.mjs";

/**
 * Renders the StepEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {number} props.depth - The depth level of this event for nested UI display.
 * @param {import("../../types/log").StepEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component that displays event details.
 */
export const StepEventView = ({ depth, event }) => {
  const descriptor = stepDescriptor(event);
  if (event.action === "end") {
    // end events have no special implicit UI
    if (descriptor.endSpace) {
      return html`<div style=${{ height: "1.5em" }}></div>`;
    } else {
      return html``;
    }
  }

  const title =
    descriptor.name ||
    `${event.type ? event.type + ": " : "Step: "}${event.name}`;

  return html`<${EventPanel}
    title="${title}"
    depth=${depth}
    icon=${descriptor.icon}
    style=${descriptor.style}
  />`;
};

/** @type {Record<string, string>} */
const rootStepStyle = {
  backgroundColor: "var(--bs-light)",
  fontWeight: "600",
};

/**
 * Returns a descriptor object containing icon and style based on the event type and name.
 *
 * @param {import("../../types/log").StepEvent} event - The event object.
 * @returns {{ icon: string, style: Record<string, string>, endSpace: boolean, name?: string }} The descriptor with the icon and style for the event.
 */
const stepDescriptor = (event) => {
  const rootStepDescriptor = {
    style: rootStepStyle,
    endSpace: true,
  };

  if (event.type === "solver") {
    switch (event.name) {
      case "chain_of_thought":
        return {
          icon: ApplicationIcons.solvers.chain_of_thought,
          ...rootStepDescriptor,
        };
      case "generate":
        return {
          icon: ApplicationIcons.solvers.generate,
          ...rootStepDescriptor,
        };
      case "self_critique":
        return {
          icon: ApplicationIcons.solvers.self_critique,
          ...rootStepDescriptor,
        };
      case "system_message":
        return {
          icon: ApplicationIcons.solvers.system_message,
          ...rootStepDescriptor,
        };
      case "use_tools":
        return {
          icon: ApplicationIcons.solvers.use_tools,
          ...rootStepDescriptor,
        };
      case "multiple_choice":
        return {
          icon: ApplicationIcons["multiple-choice"],
          ...rootStepDescriptor,
        };
      default:
        return {
          icon: ApplicationIcons.solvers.default,
          ...rootStepDescriptor,
        };
    }
  } else if (event.type === "scorer") {
    return {
      icon: ApplicationIcons.scorer,
      ...rootStepDescriptor,
    };
  } else {
    switch (event.name) {
      case "sample_init":
        return {
          icon: ApplicationIcons.sample,
          ...rootStepDescriptor,
          name: "Sample Init",
        };
      default:
        return {
          icon: ApplicationIcons.step,
          style: {},
          endSpace: false,
        };
    }
  }
};
