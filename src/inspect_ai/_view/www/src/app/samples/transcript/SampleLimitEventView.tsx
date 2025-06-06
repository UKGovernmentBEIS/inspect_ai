import clsx from "clsx";
import { FC } from "react";
import { SampleLimitEvent, Type15 } from "../../../@types/log";
import { ApplicationIcons } from "../../appearance/icons";
import { EventPanel } from "./event/EventPanel";
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
  const resolve_title = (type: Type15) => {
    switch (type) {
      case "custom":
        return "Custom Limit Exceeded";
      case "time":
        return "Time Limit Exceeded";
      case "message":
        return "Message Limit Exceeded";
      case "token":
        return "Token Limit Exceeded";
      case "operator":
        return "Operator Canceled";
      case "working":
        return "Execution Time Limit Exceeded";
    }
  };

  const resolve_icon = (type: Type15) => {
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
    }
  };

  const title = resolve_title(eventNode.event.type);
  const icon = resolve_icon(eventNode.event.type);

  return (
    <EventPanel
      eventNodeId={eventNode.id}
      depth={eventNode.depth}
      title={title}
      icon={icon}
      className={className}
    >
      <div className={clsx("text-size-smaller")}>{eventNode.event.message}</div>
    </EventPanel>
  );
};
