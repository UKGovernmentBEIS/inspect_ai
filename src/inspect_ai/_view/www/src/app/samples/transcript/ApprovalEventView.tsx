import { FC } from "react";
import { ApprovalEvent } from "../../../@types/log";
import { ApplicationIcons } from "../../appearance/icons";
import { EventRow } from "./event/EventRow";
import { eventTitle } from "./event/utils";
import { EventNode } from "./types";

interface ApprovalEventViewProps {
  eventNode: EventNode<ApprovalEvent>;
  className?: string | string[];
}

/**
 * Renders the ApprovalEventView component.
 */
export const ApprovalEventView: FC<ApprovalEventViewProps> = ({
  eventNode,
  className,
}) => {
  const event = eventNode.event;
  return (
    <EventRow
      title={eventTitle(event)}
      icon={decisionIcon(event.decision)}
      className={className}
    >
      {event.explanation || ""}
    </EventRow>
  );
};

/**
 * Determines the icon for a decision
 */
const decisionIcon = (decision: string): string => {
  switch (decision) {
    case "approve":
      return ApplicationIcons.approvals.approve;
    case "reject":
      return ApplicationIcons.approvals.reject;
    case "terminate":
      return ApplicationIcons.approvals.terminate;
    case "escalate":
      return ApplicationIcons.approvals.escalate;
    case "modify":
      return ApplicationIcons.approvals.modify;
    default:
      return ApplicationIcons.approve;
  }
};
