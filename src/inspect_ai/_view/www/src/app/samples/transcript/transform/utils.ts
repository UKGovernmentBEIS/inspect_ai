import { Events } from "../../../../@types/log";

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
