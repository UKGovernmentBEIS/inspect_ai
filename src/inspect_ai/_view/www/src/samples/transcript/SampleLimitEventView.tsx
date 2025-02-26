import { FC } from "react";
import { ApplicationIcons } from "../../appearance/icons";
import { SampleLimitEvent, Type8 } from "../../types/log";
import { EventPanel } from "./event/EventPanel";
import { TranscriptEventState } from "./types";

interface SampleLimitEventViewProps {
  id: string;
  event: SampleLimitEvent;
  eventState: TranscriptEventState;
  setEventState: (state: TranscriptEventState) => void;
  className?: string | string[];
}

/**
 * Renders the InfoEventView component.
 */
export const SampleLimitEventView: FC<SampleLimitEventViewProps> = ({
  id,
  event,
  eventState,
  setEventState,
  className,
}) => {
  const resolve_title = (type: Type8) => {
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

  const resolve_icon = (type: Type8) => {
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
    <EventPanel
      id={id}
      title={title}
      icon={icon}
      className={className}
      selectedNav={eventState.selectedNav || ""}
      setSelectedNav={(selectedNav) => {
        setEventState({ ...eventState, selectedNav });
      }}
      collapsed={eventState.collapsed}
      setCollapsed={(collapsed) => {
        setEventState({ ...eventState, collapsed });
      }}
    >
      {event.message}
    </EventPanel>
  );
};
