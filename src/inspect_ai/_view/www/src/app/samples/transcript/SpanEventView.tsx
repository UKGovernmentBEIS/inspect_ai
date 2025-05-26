import clsx from "clsx";
import { FC } from "react";
import { SpanBeginEvent } from "../../../@types/log";
import { formatDateTime } from "../../../utils/format";
import { EventPanel } from "./event/EventPanel";
import { kSandboxSignalName } from "./transform/fixups";
import { EventNode, EventType } from "./types";

interface SpanEventViewProps {
  eventNode: EventNode<SpanBeginEvent>;
  children: EventNode<EventType>[];
  className?: string | string[];
}

/**
 * Renders the SpanEventView component.
 */
export const SpanEventView: FC<SpanEventViewProps> = ({
  eventNode,
  children,
  className,
}) => {
  const event = eventNode.event;
  const descriptor = spanDescriptor(event);
  const title =
    descriptor.name ||
    `${event.type ? event.type + ": " : "Step: "}${event.name}`;
  const text = summarize(children);

  return (
    <EventPanel
      eventNodeId={eventNode.id}
      depth={eventNode.depth}
      childIds={children.map((child) => child.id)}
      className={clsx("transcript-span", className)}
      title={title}
      subTitle={formatDateTime(new Date(event.timestamp))}
      text={text}
      icon={descriptor.icon}
    />
  );
};

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
const spanDescriptor = (
  event: SpanBeginEvent,
): { icon?: string; name?: string; endSpace?: boolean } => {
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
  } else if (event.event === "span_begin") {
    if (event.span_id === kSandboxSignalName) {
      return {
        ...rootStepDescriptor,
        name: "Sandbox Events",
      };
    } else if (event.name === "init") {
      return {
        ...rootStepDescriptor,
        name: "Init",
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
        };
      default:
        return {
          endSpace: false,
        };
    }
  }
};
