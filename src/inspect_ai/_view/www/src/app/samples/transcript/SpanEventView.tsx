import clsx from "clsx";
import { FC, useMemo } from "react";
import { SpanBeginEvent } from "../../../@types/log";
import { formatDateTime } from "../../../utils/format";
import { EventPanel } from "./event/EventPanel";
import { eventTitle, formatTitle } from "./event/utils";
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
  const title = eventTitle(event);

  const text = useMemo(() => summarize(children), [children]);
  const childIds = useMemo(() => children.map((child) => child.id), [children]);

  return (
    <EventPanel
      eventNodeId={eventNode.id}
      depth={eventNode.depth}
      childIds={childIds}
      className={clsx("transcript-span", className)}
      title={formatTitle(title, undefined, event.working_start)}
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
): { icon?: string; endSpace?: boolean } => {
  const rootStepDescriptor = {
    endSpace: true,
  };

  if (event.type === "solver" || event.type === "scorer") {
    return { ...rootStepDescriptor };
  } else if (event.event === "span_begin") {
    return { ...rootStepDescriptor };
  } else {
    switch (event.name) {
      case "sample_init":
        return { ...rootStepDescriptor };
      default:
        return { endSpace: false };
    }
  }
};
