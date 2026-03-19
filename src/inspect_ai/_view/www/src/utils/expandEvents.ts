// Copied from inspect_scout expandEvents.ts — will be shared once the
// ts-mono monorepo conversion is complete.

import type { EvalSample, Events, EventsData, ModelEvent } from "../@types/log";

type Event = Events[number];
type ChatMessage = EvalSample["messages"][number];

/**
 * Expand range-encoded refs against a pool.
 * Each ref is [start, endExclusive] -> pool.slice(start, endExclusive).
 */
const expandRefs = <T>(refs: [number, number][], pool: T[]): T[] =>
  refs.flatMap(([start, end]) => pool.slice(start, end));

const isModelEvent = (event: Event): event is ModelEvent =>
  event.event === "model";

/**
 * Expand condensed ModelEvent input/call refs back to inline data.
 *
 * Pure function -- returns a new array; input is not mutated.
 * Non-ModelEvents and ModelEvents without refs pass through unchanged.
 */
export function expandEvents(
  events: Event[],
  eventsData: EventsData | null,
): Event[] {
  if (!eventsData) return events;

  const { messages, calls } = eventsData;
  const hasMessages = messages.length > 0;
  const hasCalls = calls.length > 0;
  if (!hasMessages && !hasCalls) return events;

  return events.map((event) => {
    if (!isModelEvent(event)) return event;

    let changed = false;
    let input: ChatMessage[] = event.input;
    let call: ModelEvent["call"] = event.call;

    // Expand input refs
    if (event.input_refs != null && hasMessages) {
      input = expandRefs(event.input_refs as [number, number][], messages);
      changed = true;
    }

    // Expand call refs
    if (call?.call_refs != null && hasCalls) {
      const key = call.call_key ?? "messages";
      const expandedMsgs = expandRefs(
        call.call_refs as [number, number][],
        calls,
      );
      call = {
        ...call,
        request: { ...call.request, [key]: expandedMsgs },
        call_refs: null,
        call_key: null,
      };
      changed = true;
    }

    return changed ? { ...event, input, input_refs: null, call } : event;
  });
}
