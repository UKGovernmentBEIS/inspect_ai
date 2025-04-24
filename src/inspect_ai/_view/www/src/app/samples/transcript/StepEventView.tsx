import clsx from "clsx";
import { FC } from "react";
import { StepEvent } from "../../../@types/log";
import { formatDateTime } from "../../../utils/format";
import { EventPanel } from "./event/EventPanel";
import { TranscriptComponent } from "./TranscriptView";
import { kSandboxSignalName } from "./transform/fixups";
import { EventNode } from "./types";

interface StepEventViewProps {
  id: string;
  event: StepEvent;
  children: EventNode[];
  className?: string | string[];
}

/**
 * Renders the StepEventView component.
 */
export const StepEventView: FC<StepEventViewProps> = ({
  id,
  event,
  children,
  className,
}) => {
  const descriptor = stepDescriptor(event);
  const title =
    descriptor.name ||
    `${event.type ? event.type + ": " : "Step: "}${event.name}`;
  const text = summarize(children);

  return (
    <EventPanel
      id={`step-${event.name}-${id}`}
      className={clsx("transcript-step", className)}
      title={title}
      subTitle={formatDateTime(new Date(event.timestamp))}
      icon={descriptor.icon}
      collapse={descriptor.collapse}
      text={text}
    >
      <TranscriptComponent
        id={`step|${event.name}|${id}`}
        eventNodes={children}
      />
    </EventPanel>
  );
};

/**
 * Renders the StepEventView component.
 */
const summarize = (children: EventNode[]) => {
  if (children.length === 0) {
    return "(no events)";
  }

  const formatEvent = (event: string, count: number) => {
    if (count === 1) {
      return `${count} ${event} event`;
    } else {
      return `${count} ${event} events`;
    }
  };

  // Count the types
  const typeCount: Record<string, number> = {};
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

/**
 * Returns a descriptor object containing icon and style based on the event type and name.
 */
const stepDescriptor = (
  event: StepEvent,
): { icon?: string; name?: string; endSpace?: boolean; collapse?: boolean } => {
  const rootStepDescriptor = {
    endSpace: true,
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
          collapse: true,
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
  } else if (event.event === "step") {
    if (event.name === kSandboxSignalName) {
      return {
        ...rootStepDescriptor,
        name: "Sandbox Events",
        collapse: true,
      };
    } else if (event.name === "init") {
      return {
        ...rootStepDescriptor,
        name: "Init",
        collapse: true,
      };
    } else {
      return {
        ...rootStepDescriptor,
      };
    }
  } else {
    switch (event.name) {
      case "sample_init":
        return {
          ...rootStepDescriptor,
          name: "Sample Init",
          collapse: true,
        };
      default:
        return {
          endSpace: false,
        };
    }
  }
};
