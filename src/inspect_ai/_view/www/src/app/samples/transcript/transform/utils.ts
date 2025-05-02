import { Events } from "../../../../@types/log";

export const ET_STEP = "step";
export const ACTION_BEGIN = "begin";

export const ET_SPAN_BEGIN = "span_begin";
export const ET_SPAN_END = "span_end";

export const hasSpans = (events: Events): boolean => {
  return events.some((event) => event.event === ET_SPAN_BEGIN);
};
