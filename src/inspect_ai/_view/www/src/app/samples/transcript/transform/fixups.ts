// This is a special name that signals a group of sandbox events.

import { Events, StepEvent } from "../../../../@types/log";

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
  // See if the events have an init step
  const hasInitStep =
    events.findIndex((e) => {
      return e.event === "step" && e.name === "init";
    }) !== -1;

  const initEventIndex = events.findIndex((e) => {
    return e.event === "sample_init";
  });
  const initEvent = events[initEventIndex];

  const fixedUp = [...events];
  if (!hasInitStep && initEvent) {
    fixedUp.splice(initEventIndex, 0, {
      timestamp: initEvent.timestamp,
      event: "step",
      action: "begin",
      type: null,
      name: "sample_init",
      pending: false,
      working_start: 0,
    });

    fixedUp.splice(initEventIndex + 2, 0, {
      timestamp: initEvent.timestamp,
      event: "step",
      action: "end",
      type: null,
      name: "sample_init",
      pending: false,
      working_start: 0,
    });
  }
  return fixedUp;
};

const groupSandboxEvents = (events: Events): Events => {
  const result: Events = [];
  const pendingSandboxEvents: Events = [];

  const pushPendingSandboxEvents = () => {
    const timestamp =
      pendingSandboxEvents[pendingSandboxEvents.length - 1].timestamp;
    result.push(createStepEvent(kSandboxSignalName, timestamp, "begin"));
    result.push(...pendingSandboxEvents);
    result.push(createStepEvent(kSandboxSignalName, timestamp, "end"));
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
});
