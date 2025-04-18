import { FC } from "react";
import { ApprovalEvent } from "../../../@types/log";
import { ApplicationIcons } from "../../appearance/icons";
import { EventRow } from "./event/EventRow";

interface ApprovalEventViewProps {
  event: ApprovalEvent;
  className?: string | string[];
}

/**
 * Renders the ApprovalEventView component.
 */
export const ApprovalEventView: FC<ApprovalEventViewProps> = ({
  event,
  className,
}) => {
  return (
    <EventRow
      title={decisionLabel(event.decision)}
      icon={decisionIcon(event.decision)}
      className={className}
    >
      {event.explanation || ""}
    </EventRow>
  );
};

/**
 * Determines the label for a decision
 */
const decisionLabel = (decision: string): string => {
  switch (decision) {
    case "approve":
      return "Approved";
    case "reject":
      return "Rejected";
    case "terminate":
      return "Terminated";
    case "escalate":
      return "Escalated";
    case "modify":
      return "Modified";
    default:
      return decision;
  }
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
