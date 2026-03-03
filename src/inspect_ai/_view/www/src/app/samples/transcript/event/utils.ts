import {
  formatDateTime,
  formatNumber,
  formatTime,
} from "../../../../utils/format";
import { kSandboxSignalName } from "../transform/fixups";
import { EventType } from "../types";

const sampleLimitTitles: Record<string, string> = {
  custom: "Custom Limit Exceeded",
  time: "Time Limit Exceeded",
  message: "Message Limit Exceeded",
  token: "Token Limit Exceeded",
  operator: "Operator Canceled",
  working: "Execution Time Limit Exceeded",
  cost: "Cost Limit Exceeded",
};

const approvalDecisionLabels: Record<string, string> = {
  approve: "Approved",
  reject: "Rejected",
  terminate: "Terminated",
  escalate: "Escalated",
  modify: "Modified",
};

/**
 * Returns the base title string for any event type.
 * Used by both event rendering components and search text extraction.
 */
export const eventTitle = (event: EventType): string => {
  switch (event.event) {
    case "model":
      return event.role
        ? `Model Call (${event.role}): ${event.model}`
        : `Model Call: ${event.model}`;
    case "tool": {
      let title = event.view?.title || event.function;
      if (event.view?.title) {
        title = title.replace(/\{\{(\w+)\}\}/g, (match, key: string) =>
          Object.hasOwn(event.arguments, key)
            ? String(event.arguments[key])
            : match,
        );
      }
      return `Tool: ${title}`;
    }
    case "error":
      return "Error";
    case "logger":
      return event.message.level;
    case "info":
      return "Info" + (event.source ? ": " + event.source : "");
    case "compaction": {
      const source =
        event.source && event.source !== "inspect" ? event.source : "";
      return "Compaction" + source;
    }
    case "step":
      if (event.name === kSandboxSignalName) return "Sandbox Events";
      if (event.name === "init") return "Init";
      if (event.name === "sample_init") return "Sample Init";
      return event.type
        ? `${event.type}: ${event.name}`
        : `Step: ${event.name}`;
    case "subtask":
      return event.type === "fork"
        ? `Fork: ${event.name}`
        : `Subtask: ${event.name}`;
    case "span_begin":
      if (event.span_id === kSandboxSignalName) return "Sandbox Events";
      if (event.name === "init") return "Init";
      if (event.name === "sample_init") return "Sample Init";
      return event.type
        ? `${event.type}: ${event.name}`
        : `Step: ${event.name}`;
    case "score":
      return (event.intermediate ? "Intermediate " : "") + "Score";
    case "score_edit":
      return "Edit Score";
    case "sample_init":
      return "Sample";
    case "sample_limit":
      return sampleLimitTitles[event.type] ?? event.type;
    case "input":
      return "Input";
    case "approval":
      return approvalDecisionLabels[event.decision] ?? event.decision;
    case "sandbox":
      return `Sandbox: ${event.action}`;
    default:
      return "";
  }
};

export const formatTiming = (timestamp: string, working_start?: number) => {
  if (working_start) {
    return `${formatDateTime(new Date(timestamp))}\n@ working time: ${formatTime(working_start)}`;
  } else {
    return formatDateTime(new Date(timestamp));
  }
};

export const formatTitle = (
  title: string,
  total_tokens?: number,
  working_start?: number | null,
) => {
  const subItems = [];
  if (total_tokens) {
    subItems.push(`${formatNumber(total_tokens)} tokens`);
  }
  if (working_start) {
    subItems.push(`${formatTime(working_start)}`);
  }
  const subtitle = subItems.length > 0 ? ` (${subItems.join(", ")})` : "";
  return `${title}${subtitle}`;
};
