import { Events } from "../../../../@types/log";
import { EventNode, EventType } from "../types";

export const STEP = "step";
export const ACTION_BEGIN = "begin";

export const SPAN_BEGIN = "span_begin";
export const SPAN_END = "span_end";
export const TOOL = "tool";
export const SUBTASK = "subtask";
export const STORE = "store";
export const STATE = "state";

export const TYPE_TOOL = "tool";
export const TYPE_SUBTASK = "subtask";
export const TYPE_SOLVER = "solver";
export const TYPE_SOLVERS = "solvers";
export const TYPE_AGENT = "agent";
export const TYPE_HANDOFF = "handoff";
export const TYPE_SCORERS = "scorers";
export const TYPE_SCORER = "scorer";

export const hasSpans = (events: Events): boolean => {
  return events.some((event) => event.event === SPAN_BEGIN);
};

export function printTree(nodes: EventNode[], ancestors: boolean[] = []): void {
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i];
    const last = i === nodes.length - 1;

    const linePrefix = ancestors.map((l) => (l ? "    " : "│   ")).join("");
    const connector = last ? "└── " : "├── ";

    const detail = eventDetail(node.event);
    const shortId = node.id.length > 8 ? node.id.slice(0, 8) : node.id;
    const childCount =
      node.children.length > 0 ? ` {${node.children.length}}` : "";
    console.log(
      `${linePrefix}${connector}${node.event.event}${detail}${childCount} [depth: ${node.depth}] (${shortId})`,
    );

    if (node.children.length > 0) {
      printTree(node.children, [...ancestors, last]);
    }
  }
}

function truncate(str: string, max: number): string {
  return str.length > max ? str.slice(0, max) + "…" : str;
}

function eventDetail(event: EventType): string {
  switch (event.event) {
    case "sample_init": {
      const id = event.sample?.id;
      return id != null ? ` #${id}` : "";
    }
    case "sample_limit":
      return ` ${event.type}${event.limit != null ? `=${event.limit}` : ""}: "${truncate(event.message, 40)}"`;
    case "step":
      return ` ${event.action}${event.type ? ` [${event.type}]` : ""} "${event.name}"`;
    case "span_begin":
      return `${event.type ? ` [${event.type}]` : ""} "${event.name}"`;
    case "span_end":
      return ` ${event.id.length > 8 ? event.id.slice(0, 8) : event.id}`;
    case "model": {
      const stop = event.output?.choices?.[0]?.stop_reason;
      return ` (${event.model})${stop ? ` → ${stop}` : ""}`;
    }
    case "tool": {
      const idShort = event.id.length > 12 ? event.id.slice(0, 12) : event.id;
      const status = event.failed ? " FAILED" : event.error ? " ERROR" : "";
      return ` "${event.function}" (${idShort})${status}`;
    }
    case "subtask":
      return ` "${event.name}"${event.type ? ` [${event.type}]` : ""}`;
    case "state":
      return ` (${event.changes.length} change${event.changes.length !== 1 ? "s" : ""})`;
    case "store":
      return ` (${event.changes.length} change${event.changes.length !== 1 ? "s" : ""})`;
    case "score": {
      const val = event.score?.value;
      const inter = event.intermediate ? " intermediate" : "";
      return ` ${val != null ? String(val) : "?"}${inter}`;
    }
    case "score_edit":
      return ` "${event.score_name}"`;
    case "error":
      return ` "${truncate(event.error.message, 50)}"`;
    case "logger":
      return ` ${event.message.level}: "${truncate(event.message.message, 40)}"`;
    case "info":
      return event.source ? ` (${event.source})` : "";
    case "input":
      return ` "${truncate(event.input, 30)}"`;
    case "approval":
      return ` ${event.approver} → ${event.decision}`;
    case "sandbox": {
      const target = event.cmd
        ? `"${truncate(event.cmd, 30)}"`
        : event.file
          ? `"${event.file}"`
          : "";
      return ` ${event.action}${target ? ` ${target}` : ""}`;
    }
    case "compaction":
      return ` ${event.tokens_before ?? "?"} → ${event.tokens_after ?? "?"}`;
    default:
      return "";
  }
}
