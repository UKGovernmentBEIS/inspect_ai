import clsx from "clsx";
import { FC } from "react";
import { SpanBeginEvent } from "../../../@types/log";
import { formatDateTime } from "../../../utils/format";
import { EventPanel } from "./event/EventPanel";
import { TranscriptComponent } from "./TranscriptView";
import { kSandboxSignalName } from "./transform/fixups";
import { EventNode } from "./types";

interface SpanEventViewProps {
  id: string;
  event: SpanBeginEvent;
  children: EventNode[];
  className?: string | string[];
}

/**
 * Renders the SpanEventView component.
 */
export const SpanEventView: FC<SpanEventViewProps> = ({
  id,
  event,
  children,
  className,
}) => {
  const descriptor = spanDescriptor(event);
  const title =
    descriptor.name ||
    `${event.type ? event.type + ": " : "Step: "}${event.name}`;
  const text = summarize(children);

  return (
    <EventPanel
      id={`span-${event.name}-${id}`}
      className={clsx("transcript-span", className)}
      title={title}
      subTitle={formatDateTime(new Date(event.timestamp))}
      text={text}
      collapse={descriptor.collapse}
      icon={descriptor.icon}
    >
      <TranscriptComponent
        id={`span|${event.name}|${id}`}
        eventNodes={children}
      />
    </EventPanel>
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
): { icon?: string; name?: string; endSpace?: boolean; collapse?: boolean } => {
  const rootStepDescriptor = {
    endSpace: true,
  };

  if (event.type === "solver") {
    switch (event.name) {
      case "chain_of_thought":
        return {
          ...rootStepDescriptor,
          collapse: false,
        };
      case "generate":
        return {
          ...rootStepDescriptor,
          collapse: false,
        };
      case "self_critique":
        return {
          ...rootStepDescriptor,
          collapse: false,
        };
      case "system_message":
        return {
          ...rootStepDescriptor,
          collapse: true,
        };
      case "use_tools":
        return {
          ...rootStepDescriptor,
          collapse: false,
        };
      case "multiple_choice":
        return {
          ...rootStepDescriptor,
          collapse: false,
        };
      default:
        return {
          ...rootStepDescriptor,
          collapse: false,
        };
    }
  } else if (event.type === "scorer") {
    return {
      ...rootStepDescriptor,
      collapse: false,
    };
  } else if (event.event === "span_begin") {
    if (event.span_id === kSandboxSignalName) {
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
        collapse: false,
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
