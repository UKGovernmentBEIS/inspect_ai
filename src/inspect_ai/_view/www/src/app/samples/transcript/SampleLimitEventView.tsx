import clsx from "clsx";
import { FC } from "react";
import { SampleLimitEvent, Type17 } from "../../../@types/log";
import { formatDateTime } from "../../../utils/format";
import { ApplicationIcons } from "../../appearance/icons";
import { EventPanel } from "./event/EventPanel";
import { eventTitle, formatTitle } from "./event/utils";
import { EventNode } from "./types";

interface SampleLimitEventViewProps {
  eventNode: EventNode<SampleLimitEvent>;
  className?: string | string[];
}

/**
 * Renders the InfoEventView component.
 */
export const SampleLimitEventView: FC<SampleLimitEventViewProps> = ({
  eventNode,
  className,
}) => {
  const resolve_icon = (type: Type17) => {
    switch (type) {
      case "custom":
        return ApplicationIcons.limits.custom;
      case "time":
        return ApplicationIcons.limits.time;
      case "message":
        return ApplicationIcons.limits.messages;
      case "token":
        return ApplicationIcons.limits.tokens;
      case "operator":
        return ApplicationIcons.limits.operator;
      case "working":
        return ApplicationIcons.limits.execution;
      case "cost":
        return ApplicationIcons.limits.cost;
    }
  };

  const icon = resolve_icon(eventNode.event.type);

  return (
    <EventPanel
      eventNodeId={eventNode.id}
      depth={eventNode.depth}
      title={formatTitle(
        eventTitle(eventNode.event),
        undefined,
        eventNode.event.working_start,
      )}
      subTitle={formatDateTime(new Date(eventNode.event.timestamp))}
      icon={icon}
      className={className}
    >
      <div className={clsx("text-size-smaller")}>{eventNode.event.message}</div>
    </EventPanel>
  );
};
