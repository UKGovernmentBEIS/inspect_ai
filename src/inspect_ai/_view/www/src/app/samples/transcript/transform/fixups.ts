// This is a special name that signals a group of sandbox events.

import {
  Events,
  SpanBeginEvent,
  SpanEndEvent,
  StepEvent,
} from "../../../../@types/log";
import { hasSpans } from "./utils";

// It will be caught elsewhere and rendered with a pretty name
export const kSandboxSignalName = "53787D8A-D3FC-426D-B383-9F880B70E4AA";

/**
 * Normalizes event content
 */
export const fixupEventStream = (
  events: Events,
  filterPending: boolean = true,
) => {
  // We ignore pending events sometimes (when an eval is complete) and
  // show them other times (when an eval is running)
  const collapsed = processPendingEvents(events, filterPending);

  // We need to inject a step event for sample_init if it doesn't exist
  const fixedUp = collapseSampleInit(collapsed);

  // Inject step events before and after groups of sandbox events
  return groupSandboxEvents(fixedUp);
};

const processPendingEvents = (events: Events, filter: boolean): Events => {
  // If filtering pending, just remove all pending events
  // otherise, collapse sequential pending events of the same
  // type
  return filter
    ? events.filter((e) => !e.pending)
    : events.reduce<Events>((acc, event) => {
        // Collapse sequential pending events of the same type
        if (!event.pending) {
          // Not a pending event
          acc.push(event);
        } else {
          // For pending events, replace previous pending or add new
          const lastIndex = acc.length - 1;
          if (
            lastIndex >= 0 &&
            acc[lastIndex].pending &&
            acc[lastIndex].event === event.event
          ) {
            // Replace previous pending with current one (if they're of the same type)
            acc[lastIndex] = event;
          } else {
            // First event or follows non-pending
            acc.push(event);
          }
        }
        return acc;
      }, []);
};

const collapseSampleInit = (events: Events): Events => {
  // Don't performance sample init logic if spans are present
  const hasSpans = events.some((e) => {
    return e.event === "span_begin" || e.event === "span_end";
  });
  if (hasSpans) {
    return events;
  }

  // Don't synthesize a sample init step if one already exists
  const hasInitStep =
    events.findIndex((e) => {
      return e.event === "step" && e.name === "init";
    }) !== -1;
  if (hasInitStep) {
    return events;
  }

  // Find a sample init event
  const initEventIndex = events.findIndex((e) => {
    return e.event === "sample_init";
  });
  const initEvent = events[initEventIndex];
  if (!initEvent) {
    return events;
  }

  // Splice in sample init step if needed
  const fixedUp = [...events];
  fixedUp.splice(initEventIndex, 0, {
    timestamp: initEvent.timestamp,
    event: "step",
    action: "begin",
    type: null,
    name: "sample_init",
    pending: false,
    working_start: 0,
    span_id: initEvent.span_id,
    uuid: null,
    metadata: null,
  });

  fixedUp.splice(initEventIndex + 2, 0, {
    timestamp: initEvent.timestamp,
    event: "step",
    action: "end",
    type: null,
    name: "sample_init",
    pending: false,
    working_start: 0,
    span_id: initEvent.span_id,
    uuid: null,
    metadata: null,
  });
  return fixedUp;
};

const groupSandboxEvents = (events: Events): Events => {
  const result: Events = [];
  const pendingSandboxEvents: Events = [];

  const useSpans = hasSpans(events);

  const pushPendingSandboxEvents = () => {
    const timestamp =
      pendingSandboxEvents[pendingSandboxEvents.length - 1].timestamp;
    if (useSpans) {
      result.push(createSpanBegin(kSandboxSignalName, timestamp, null));
    } else {
      result.push(createStepEvent(kSandboxSignalName, timestamp, "begin"));
    }
    result.push(...pendingSandboxEvents);
    if (useSpans) {
      result.push(createSpanEnd(kSandboxSignalName, timestamp));
    } else {
      result.push(createStepEvent(kSandboxSignalName, timestamp, "end"));
    }
    pendingSandboxEvents.length = 0;
  };

  for (const event of events) {
    if (event.event === "sandbox") {
      // Collect sandbox events
      pendingSandboxEvents.push(event);
      continue;
    }

    // Process any collected sandbox events
    if (pendingSandboxEvents.length > 0) {
      pushPendingSandboxEvents();
    }

    // Clear sandbox events and add the current event
    result.push(event);
  }

  // Handle any remaining sandbox events at the end
  if (pendingSandboxEvents.length > 0) {
    pushPendingSandboxEvents();
  }

  return result;
};

const createStepEvent = (
  name: string,
  timestamp: string,
  action: "begin" | "end",
): StepEvent => ({
  timestamp,
  event: "step",
  action,
  type: null,
  name,
  pending: false,
  working_start: 0,
  span_id: null,
  uuid: null,
  metadata: null,
});

const createSpanBegin = (
  name: string,
  timestamp: string,
  parent_id: string | null,
): SpanBeginEvent => {
  return {
    name,
    id: `${name}-begin`,
    span_id: name,
    parent_id,
    timestamp,
    event: "span_begin",
    type: null,
    pending: false,
    working_start: 0,
    uuid: null,
    metadata: null,
  };
};

const createSpanEnd = (name: string, timestamp: string): SpanEndEvent => {
  return {
    id: `${name}-end`,
    timestamp,
    event: "span_end",
    pending: false,
    working_start: 0,
    span_id: name,
    uuid: null,
    metadata: null,
  };
};
