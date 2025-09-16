import { Events } from "../../../../@types/log";
import { kCollapsibleEventTypes } from "../types";

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

export const hasSpanChildren = (stream: Events): boolean => {
  //guard against invalid calls
  if (stream.length <= 1 || !kCollapsibleEventTypes.includes(stream[0].event)) {
    return false;
  }

  // is there a span_begin before the next span end?
  for (let i = 1; i < stream.length; i++) {
    const event = stream[i];
    if (event.event === SPAN_BEGIN) {
      return true;
    }

    if (event.event === SPAN_END) {
      break;
    }
  }

  return false;
};
