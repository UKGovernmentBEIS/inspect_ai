import { FC } from "react";
import { SampleLimitEvent, Type10 } from "../../../@types/log";
import { ApplicationIcons } from "../../appearance/icons";
import { EventPanel } from "./event/EventPanel";

interface SampleLimitEventViewProps {
  id: string;
  event: SampleLimitEvent;
  className?: string | string[];
}

/**
 * Renders the InfoEventView component.
 */
export const SampleLimitEventView: FC<SampleLimitEventViewProps> = ({
  id,
  event,
  className,
}) => {
  const resolve_title = (type: Type10) => {
    switch (type) {
      case "custom":
        return "Custom Limit Exceeded";
      case "time":
        return "Time Limit Execeeded";
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

  const resolve_icon = (type: Type10) => {
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

  const title = resolve_title(event.type);
  const icon = resolve_icon(event.type);

  return (
    <EventPanel id={id} title={title} icon={icon} className={className}>
      {event.message}
    </EventPanel>
  );
};
