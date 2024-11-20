// @ts-check
import { html } from "htm/preact";
import { EventPanel } from "./EventPanel.mjs";
import { TranscriptComponent } from "./TranscriptView.mjs";
import { formatDateTime } from "../../utils/Format.mjs";

/**
 * Renders the StepEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {Object} props.style - The style properties passed to the component.
 * @param {import("../../types/log").StepEvent} props.event - The event object to display.
 * @param {import("./Types.mjs").EventNode[]} props.children - The event notes children of this step
 * @returns {import("preact").JSX.Element} The component that displays event details.
 */
export const StepEventView = ({ event, children, style }) => {
  const descriptor = stepDescriptor(event);
  const title =
    descriptor.name ||
    `${event.type ? event.type + ": " : "Step: "}${event.name}`;
  const text = summarize(children);

  return html`<${EventPanel}
    id=${`step-${event.name}`}
    classes="transcript-step"
    title="${title}"
    subTitle=${formatDateTime(new Date(event.timestamp))}
    icon=${descriptor.icon}
    style=${{ ...descriptor.style, ...style }}
    titleStyle=${{ ...descriptor.titleStyle }}
    collapse=${false}
    text=${text}
  >
    <${TranscriptComponent}
      id=${`step-${event.name}-transcript`}
      eventNodes=${children}
    />
  </EventPanel>
  `;
};

/**
 * Renders the StepEventView component.
 *
 * @param {import("./Types.mjs").EventNode[]} children - The event notes children of this step
 * @returns { string } The summary text
 */
const summarize = (children) => {
  if (children.length === 0) {
    return "(no events)";
  }

  const formatEvent = (event, count) => {
    if (count === 1) {
      return `${count} ${event} event`;
    } else {
      return `${count} ${event} events`;
    }
  };

  // Count the types
  const typeCount = {};
  children.forEach((child) => {
    const currentCount = typeCount[child.event.event] || 0;
    typeCount[child.event.event] = currentCount + 1;
  });

  // Try to summarize event types
  const numberOfTypes = Object.keys(typeCount).length;
  if (numberOfTypes < 3) {
    return Object.keys(typeCount)
      .map((key) => {
        return formatEvent(key, typeCount[key]);
      })
      .join(", ");
  }

  // To many types, just return the number of events
  if (children.length === 1) {
    return "1 event";
  } else {
    return `${children.length} events`;
  }
};

/** @type {Record<string, string>} */
const rootStepStyle = {};

/** @type {Record<string, string>} */
const rootTitleStyle = {
  fontWeight: "600",
};

/**
 * Returns a descriptor object containing icon and style based on the event type and name.
 *
 * @param {import("../../types/log").StepEvent} event - The event object.
 * @returns {{ icon?: string, style: Record<string, string>, endSpace: boolean, titleStyle: Record<string, string>, name?: string }} The descriptor with the icon and style for the event.
 */
const stepDescriptor = (event) => {
  const rootStepDescriptor = {
    style: rootStepStyle,
    endSpace: true,
    titleStyle: rootTitleStyle,
  };

  if (event.type === "solver") {
    switch (event.name) {
      case "chain_of_thought":
        return {
          ...rootStepDescriptor,
        };
      case "generate":
        return {
          ...rootStepDescriptor,
        };
      case "self_critique":
        return {
          ...rootStepDescriptor,
        };
      case "system_message":
        return {
          ...rootStepDescriptor,
        };
      case "use_tools":
        return {
          ...rootStepDescriptor,
        };
      case "multiple_choice":
        return {
          ...rootStepDescriptor,
        };
      default:
        return {
          ...rootStepDescriptor,
        };
    }
  } else if (event.type === "scorer") {
    return {
      ...rootStepDescriptor,
    };
  } else {
    switch (event.name) {
      case "sample_init":
        return {
          ...rootStepDescriptor,
          name: "Sample Init",
        };
      default:
        return {
          style: {},
          endSpace: false,
          titleStyle: {},
        };
    }
  }
};
